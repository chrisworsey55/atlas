"""
Institutional Flow Agent
Analyzes 13F filings from tracked hedge funds to produce flow intelligence.
"""
import json
import logging
from typing import Optional
from datetime import datetime
from pathlib import Path

import anthropic

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL
from data.thirteenf_client import ThirteenFClient
from agents.prompts.institutional_flow import (
    SYSTEM_PROMPT,
    build_flow_analysis_prompt,
)

logger = logging.getLogger(__name__)


class InstitutionalFlowAgent:
    """
    Agent that analyzes hedge fund 13F holdings and produces flow intelligence.
    """
    
    def __init__(self):
        self.thirteenf = ThirteenFClient(use_edgartools=True)
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    def analyze(self, use_ai: bool = True, cache_hours: int = 24) -> dict:
        """
        Produce an institutional flow briefing.
        
        Args:
            use_ai: If True, use Claude to synthesize insights. If False, just return raw data.
            cache_hours: How long to use cached 13F data.
        
        Returns:
            Structured flow briefing JSON.
        """
        logger.info("Fetching 13F holdings for all tracked funds...")
        
        # 1. Get holdings for all funds
        all_holdings = self.thirteenf.get_all_fund_holdings(cache_hours=cache_hours)
        
        if not all_holdings:
            logger.error("No 13F holdings data available")
            return {"error": "No holdings data available"}
        
        logger.info(f"Got holdings for {len(all_holdings)} funds")
        
        # 2. Build basic consensus report (rule-based)
        basic_report = self.thirteenf.build_consensus_report(all_holdings)
        
        if not use_ai:
            return basic_report
        
        # 3. Use Claude to synthesize deeper insights
        logger.info("Calling Claude for flow synthesis...")
        
        user_prompt = build_flow_analysis_prompt(all_holdings)
        
        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            # Fall back to basic report
            logger.info("Falling back to rule-based report")
            return basic_report
        
        # 4. Parse Claude's response
        try:
            if "```json" in raw_response:
                json_str = raw_response.split("```json")[1].split("```")[0]
            elif "```" in raw_response:
                json_str = raw_response.split("```")[1].split("```")[0]
            else:
                json_str = raw_response
            
            ai_report = json.loads(json_str.strip())
            ai_report["generated_at"] = datetime.utcnow().isoformat()
            ai_report["model_used"] = CLAUDE_MODEL
            ai_report["funds_analyzed"] = len(all_holdings)
            
            logger.info("Flow briefing generated successfully")
            return ai_report
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response: {e}")
            # Fall back to basic report
            return basic_report
    
    def persist_holdings(self, all_holdings: dict):
        """
        Save 13F holdings to database.
        """
        try:
            from database import get_session, AtlasInstitutionalHolding
            from config.universe import TRACKED_FUNDS
            
            session = get_session()
            count = 0
            
            try:
                for fund_name, df in all_holdings.items():
                    if df is None or len(df) == 0:
                        continue
                    
                    fund_info = TRACKED_FUNDS.get(fund_name, {})
                    quarter = df['quarter'].iloc[0] if 'quarter' in df.columns else None
                    filing_date = df['filing_date'].iloc[0] if 'filing_date' in df.columns else None
                    
                    # Calculate total portfolio value for percentage calculation
                    total_value = df['value'].sum() if 'value' in df.columns else 0
                    
                    for _, row in df.iterrows():
                        holding = AtlasInstitutionalHolding(
                            fund_name=fund_name,
                            fund_cik=fund_info.get("cik"),
                            ticker=self._match_ticker(row.get('name')),
                            cusip=row.get('cusip'),
                            company_name=row.get('name'),
                            shares=row.get('shares'),
                            value=row.get('value'),
                            quarter=quarter,
                            filing_date=datetime.strptime(filing_date, "%Y-%m-%d").date() if filing_date else None,
                            portfolio_pct=(row.get('value', 0) / total_value * 100) if total_value > 0 else None,
                        )
                        session.merge(holding)  # Upsert based on unique constraint
                        count += 1
                
                session.commit()
                logger.info(f"Persisted {count} holdings across {len(all_holdings)} funds")
                
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to persist holdings: {e}")
            finally:
                session.close()
                
        except ImportError:
            logger.warning("Database not configured, skipping persistence")
    
    def _match_ticker(self, name: str) -> Optional[str]:
        """Match company name to ticker."""
        if not name:
            return None
        return self.thirteenf._name_to_ticker(name)


def run_flow_analysis(use_ai: bool = True, persist: bool = False) -> dict:
    """
    Run institutional flow analysis and optionally persist results.
    """
    agent = InstitutionalFlowAgent()
    
    # Get and optionally persist holdings
    if persist:
        all_holdings = agent.thirteenf.get_all_fund_holdings(cache_hours=1)  # Fresh fetch
        agent.persist_holdings(all_holdings)
    
    # Generate briefing
    return agent.analyze(use_ai=use_ai)


if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    
    parser = argparse.ArgumentParser(description="ATLAS Institutional Flow Agent")
    parser.add_argument("--no-ai", action="store_true", help="Skip AI synthesis, use rule-based only")
    parser.add_argument("--persist", action="store_true", help="Save holdings to database")
    parser.add_argument("--test", action="store_true", help="Quick test with single fund")
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("ATLAS Institutional Flow Agent")
    print("="*60 + "\n")
    
    if args.test:
        # Quick test - just Berkshire
        client = ThirteenFClient()
        print("Testing with Berkshire Hathaway 13F...")
        df = client.get_fund_holdings("Berkshire Hathaway (Buffett)")
        if df is not None:
            print(f"\nBerkshire holdings: {len(df)} positions")
            print("\nTop 5 by value:")
            if 'value' in df.columns:
                top5 = df.nlargest(5, 'value')
                for _, row in top5.iterrows():
                    print(f"  {row.get('name', 'N/A')[:30]:30} ${row.get('value', 0):>15,.0f}")
        else:
            print("Could not fetch holdings")
    else:
        report = run_flow_analysis(use_ai=not args.no_ai, persist=args.persist)
        
        print("\n" + "="*60)
        print("INSTITUTIONAL FLOW BRIEFING")
        print("="*60)
        print(json.dumps(report, indent=2))
