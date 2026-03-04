"""
Sector Desk Agent Runner
Generic runner that pairs a desk prompt with data and calls Claude.
Supports multiple desk types: Semiconductor, Biotech, etc.
"""
import json
import logging
from typing import Optional
from datetime import datetime, date
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL
from data.edgar_client import EdgarClient
from data.price_client import PriceClient

# Import desk prompts
from agents.prompts.semiconductor_desk import (
    SYSTEM_PROMPT as SEMI_SYSTEM_PROMPT,
    build_analysis_prompt as semi_build_prompt,
)
from agents.prompts.biotech_desk import (
    SYSTEM_PROMPT as BIOTECH_SYSTEM_PROMPT,
    build_analysis_prompt as biotech_build_prompt,
)
from agents.prompts.financials_desk import (
    SYSTEM_PROMPT as FINANCIALS_SYSTEM_PROMPT,
    build_analysis_prompt as financials_build_prompt,
)
from agents.prompts.energy_desk import (
    SYSTEM_PROMPT as ENERGY_SYSTEM_PROMPT,
    build_analysis_prompt as energy_build_prompt,
)
from agents.prompts.consumer_desk import (
    SYSTEM_PROMPT as CONSUMER_SYSTEM_PROMPT,
    build_analysis_prompt as consumer_build_prompt,
)
from agents.prompts.industrials_desk import (
    SYSTEM_PROMPT as INDUSTRIALS_SYSTEM_PROMPT,
    build_analysis_prompt as industrials_build_prompt,
)

logger = logging.getLogger(__name__)


class SectorDeskAgent:
    """
    Generic sector desk agent that can be specialized with different prompts.
    """
    
    def __init__(self, desk_name: str, system_prompt: str, prompt_builder: callable):
        self.desk_name = desk_name
        self.system_prompt = system_prompt
        self.prompt_builder = prompt_builder
        self.edgar = EdgarClient()
        self.prices = PriceClient()
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    def analyze(self, ticker: str, days_back: int = 180, filing_types: list = None,
                persist: bool = False) -> Optional[dict]:
        """
        Run full analysis on a ticker.
        Returns structured brief or None if analysis fails.
        
        Args:
            ticker: Stock ticker symbol
            days_back: How far back to search for filings
            filing_types: List of filing types to consider
            persist: If True, save result to database
        """
        if filing_types is None:
            filing_types = ["10-K", "10-Q", "8-K"]
        
        logger.info(f"[{self.desk_name}] Analyzing {ticker}...")
        
        # 1. Get recent filings
        filings = self.edgar.get_recent_filings(ticker, filing_types, days_back)
        if not filings:
            logger.warning(f"[{self.desk_name}] No filings found for {ticker}")
            return None
        
        # Get the most recent 10-K or 10-Q (prefer 10-K)
        primary_filing = None
        for f in filings:
            if f["form_type"] == "10-K":
                primary_filing = f
                break
        if not primary_filing:
            for f in filings:
                if f["form_type"] == "10-Q":
                    primary_filing = f
                    break
        if not primary_filing:
            primary_filing = filings[0]  # Fall back to any filing
        
        logger.info(f"[{self.desk_name}] Using {primary_filing['form_type']} from {primary_filing['filing_date']}")
        
        # 2. Download filing text
        filing_text = self.edgar.download_filing_text(primary_filing, max_chars=50000)
        if not filing_text:
            logger.warning(f"[{self.desk_name}] Could not download filing text for {ticker}")
            filing_text = "Filing text not available"
        
        # 3. Get XBRL financials
        xbrl_data = self.edgar.get_key_financials(ticker) or {}
        xbrl_data["filing_date"] = primary_filing["filing_date"]
        
        # 4. Get price data
        price = self.prices.get_current_price(ticker)
        info = self.prices.get_sector_info(ticker)
        return_30d = self.prices.get_returns(ticker, 30)
        price_data = {
            "price": price,
            "market_cap": info.get("market_cap"),
            "pe_ratio": info.get("pe_ratio"),
            "return_30d": return_30d,
        }
        
        # 5. Build the user prompt
        user_prompt = self.prompt_builder(
            ticker=ticker,
            filing_text=filing_text,
            xbrl_financials=xbrl_data,
            price_data=price_data,
            previous_analysis=None,  # TODO: fetch from DB
        )
        
        # 6. Call Claude
        logger.info(f"[{self.desk_name}] Calling Claude for {ticker} analysis...")
        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=self.system_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"[{self.desk_name}] Claude API error: {e}")
            return None
        
        # 7. Parse JSON response
        try:
            # Handle potential markdown code blocks
            if "```json" in raw_response:
                json_str = raw_response.split("```json")[1].split("```")[0]
            elif "```" in raw_response:
                json_str = raw_response.split("```")[1].split("```")[0]
            else:
                json_str = raw_response
            
            analysis = json.loads(json_str.strip())
            analysis["desk"] = self.desk_name
            analysis["analyzed_at"] = datetime.utcnow().isoformat()
            analysis["filing_used"] = primary_filing["form_type"]
            analysis["filing_date"] = primary_filing["filing_date"]
            analysis["model_used"] = CLAUDE_MODEL
            
            logger.info(f"[{self.desk_name}] {ticker}: {analysis.get('signal', 'UNKNOWN')} (confidence: {analysis.get('confidence', 0):.2f})")
            
            # 8. Persist to database if requested
            if persist:
                self._persist_brief(ticker, analysis, primary_filing)
            
            return analysis
            
        except json.JSONDecodeError as e:
            logger.error(f"[{self.desk_name}] Failed to parse Claude response: {e}")
            logger.debug(f"Raw response: {raw_response[:500]}...")
            return None
    
    def _persist_brief(self, ticker: str, analysis: dict, filing: dict):
        """
        Save the analysis brief to the database.
        """
        try:
            from database import get_session, AtlasCompany, AtlasDeskBrief
            from sqlalchemy.exc import IntegrityError
            
            session = get_session()
            
            try:
                # Get or create company
                company = session.query(AtlasCompany).filter_by(ticker=ticker).first()
                if not company:
                    from config.universe import UNIVERSE
                    company_info = UNIVERSE.get(ticker, {})
                    company = AtlasCompany(
                        ticker=ticker,
                        cik=filing.get("cik"),
                        name=company_info.get("name", ticker),
                        sector=company_info.get("sector"),
                    )
                    session.add(company)
                    session.flush()
                
                # Create desk brief
                brief = AtlasDeskBrief(
                    company_id=company.id,
                    desk_name=self.desk_name,
                    analysis_date=date.today(),
                    brief_json=analysis,
                    signal_direction=analysis.get("signal"),
                    confidence=analysis.get("confidence"),
                    filing_type=filing.get("form_type"),
                    filing_date=datetime.strptime(filing.get("filing_date"), "%Y-%m-%d").date() if filing.get("filing_date") else None,
                    cio_briefing=analysis.get("brief_for_cio"),
                    bull_case=analysis.get("bull_case"),
                    bear_case=analysis.get("bear_case"),
                    model_used=analysis.get("model_used"),
                )
                session.add(brief)
                session.commit()
                
                logger.info(f"[{self.desk_name}] Persisted brief for {ticker} (id={brief.id})")
                
            except IntegrityError:
                session.rollback()
                logger.warning(f"[{self.desk_name}] Brief already exists for {ticker} today, skipping")
            except Exception as e:
                session.rollback()
                logger.error(f"[{self.desk_name}] Failed to persist brief: {e}")
            finally:
                session.close()
                
        except ImportError:
            logger.warning("Database not configured, skipping persistence")


# Pre-configured desk instances
class SemiconductorDesk(SectorDeskAgent):
    """Semiconductor sector specialist desk."""
    def __init__(self):
        super().__init__(
            desk_name="Semiconductor",
            system_prompt=SEMI_SYSTEM_PROMPT,
            prompt_builder=semi_build_prompt,
        )


class BiotechDesk(SectorDeskAgent):
    """Biotech/Pharmaceutical sector specialist desk."""
    def __init__(self):
        super().__init__(
            desk_name="Biotech",
            system_prompt=BIOTECH_SYSTEM_PROMPT,
            prompt_builder=biotech_build_prompt,
        )


class FinancialsDesk(SectorDeskAgent):
    """Financials sector specialist desk (banks, insurance, fintech)."""
    def __init__(self):
        super().__init__(
            desk_name="Financials",
            system_prompt=FINANCIALS_SYSTEM_PROMPT,
            prompt_builder=financials_build_prompt,
        )


class EnergyDesk(SectorDeskAgent):
    """Energy sector specialist desk (oil, gas, utilities)."""
    def __init__(self):
        super().__init__(
            desk_name="Energy",
            system_prompt=ENERGY_SYSTEM_PROMPT,
            prompt_builder=energy_build_prompt,
        )


class ConsumerDesk(SectorDeskAgent):
    """Consumer sector specialist desk (retail, CPG, restaurants)."""
    def __init__(self):
        super().__init__(
            desk_name="Consumer",
            system_prompt=CONSUMER_SYSTEM_PROMPT,
            prompt_builder=consumer_build_prompt,
        )


class IndustrialsDesk(SectorDeskAgent):
    """Industrials sector specialist desk (manufacturing, aerospace, logistics)."""
    def __init__(self):
        super().__init__(
            desk_name="Industrials",
            system_prompt=INDUSTRIALS_SYSTEM_PROMPT,
            prompt_builder=industrials_build_prompt,
        )


def get_desk(desk_name: str) -> SectorDeskAgent:
    """
    Factory function to get the appropriate desk by name.
    """
    desks = {
        "semiconductor": SemiconductorDesk,
        "biotech": BiotechDesk,
        "financials": FinancialsDesk,
        "energy": EnergyDesk,
        "consumer": ConsumerDesk,
        "industrials": IndustrialsDesk,
    }
    desk_class = desks.get(desk_name.lower())
    if not desk_class:
        raise ValueError(f"Unknown desk: {desk_name}. Available: {list(desks.keys())}")
    return desk_class()


def get_desk_for_sector(sector: str) -> SectorDeskAgent:
    """
    Map a sector name from universe.py to the appropriate desk.
    """
    sector_to_desk = {
        "Technology": "semiconductor",  # Default tech to semi, could be refined
        "Healthcare": "biotech",
        "Financials": "financials",
        "Energy": "energy",
        "Consumer": "consumer",
        "Industrials": "industrials",
        "Materials": "industrials",
        "Communications": "consumer",  # Media/entertainment
        "Real Estate": "financials",
        "Utilities": "energy",
    }
    desk_name = sector_to_desk.get(sector, "semiconductor")  # Default fallback
    return get_desk(desk_name)


def run_semiconductor_analysis(tickers: list[str] = None, persist: bool = False) -> list[dict]:
    """
    Run semiconductor desk analysis on a list of tickers.
    """
    from config.universe import SEMICONDUCTOR_UNIVERSE
    
    if tickers is None:
        tickers = SEMICONDUCTOR_UNIVERSE[:5]  # Start with top 5
    
    desk = SemiconductorDesk()
    results = []
    
    for ticker in tickers:
        try:
            analysis = desk.analyze(ticker, persist=persist)
            if analysis:
                results.append(analysis)
        except Exception as e:
            logger.error(f"Error analyzing {ticker}: {e}")
    
    return results


def run_biotech_analysis(tickers: list[str] = None, persist: bool = False) -> list[dict]:
    """
    Run biotech desk analysis on a list of tickers.
    """
    from config.universe import BIOTECH_UNIVERSE
    
    if tickers is None:
        tickers = BIOTECH_UNIVERSE[:5]  # Start with top 5
    
    desk = BiotechDesk()
    results = []
    
    for ticker in tickers:
        try:
            analysis = desk.analyze(ticker, persist=persist)
            if analysis:
                results.append(analysis)
        except Exception as e:
            logger.error(f"Error analyzing {ticker}: {e}")
    
    return results


if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    
    parser = argparse.ArgumentParser(description="ATLAS Sector Desk Analysis")
    parser.add_argument("--desk", choices=["semiconductor", "biotech"], default="semiconductor",
                       help="Which desk to run")
    parser.add_argument("--ticker", help="Single ticker to analyze")
    parser.add_argument("--persist", action="store_true", help="Save results to database")
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print(f"ATLAS {args.desk.title()} Desk - Analysis")
    print("="*60 + "\n")
    
    desk = get_desk(args.desk)
    
    if args.ticker:
        result = desk.analyze(args.ticker, persist=args.persist)
        if result:
            print("\n" + "="*60)
            print("ANALYSIS RESULT")
            print("="*60)
            print(json.dumps(result, indent=2))
    else:
        # Run on default tickers
        if args.desk == "semiconductor":
            results = run_semiconductor_analysis(persist=args.persist)
        else:
            results = run_biotech_analysis(persist=args.persist)
        
        print(f"\nAnalyzed {len(results)} companies")
        for r in results:
            print(f"  {r['ticker']}: {r['signal']} ({r['confidence']:.0%})")
