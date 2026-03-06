"""
Fundamental Analysis Agent Runner
The valuation engine for ATLAS. Runs 5 valuation methods and triangulates intrinsic value.

Methods:
1. Discounted Cash Flow (DCF)
2. Comparable Company Analysis
3. Precedent Transactions
4. Sum of the Parts (SOTP)
5. Asset-Based / Liquidation Value
"""
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path

import anthropic
import yfinance as yf
import pandas as pd
import time
import random

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL
from agents.prompts.fundamental_agent import (
    SYSTEM_PROMPT,
    build_analysis_prompt,
    SECTOR_COMPARABLES,
)
from agents.chat_mixin import ChatMixin, FUNDAMENTAL_CHAT_PROMPT

logger = logging.getLogger(__name__)

# State file for persisting valuations
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
FUNDAMENTAL_STATE_FILE = STATE_DIR / "fundamental_valuations.json"


def format_large_number(value: float) -> str:
    """Format large numbers with B/M suffix."""
    if value is None:
        return "N/A"
    if abs(value) >= 1e12:
        return f"${value/1e12:.2f}T"
    if abs(value) >= 1e9:
        return f"${value/1e9:.2f}B"
    if abs(value) >= 1e6:
        return f"${value/1e6:.2f}M"
    return f"${value:,.0f}"


def safe_get(data: dict, key: str, default=None):
    """Safely get a value from a dict, handling None."""
    value = data.get(key)
    return value if value is not None else default


def calculate_growth(values: list) -> Optional[float]:
    """Calculate CAGR from a list of values."""
    if not values or len(values) < 2:
        return None
    try:
        start = float(values[0])
        end = float(values[-1])
        years = len(values) - 1
        if start <= 0 or end <= 0:
            return None
        return ((end / start) ** (1 / years) - 1) * 100
    except (ValueError, TypeError, ZeroDivisionError):
        return None


class FundamentalAgent(ChatMixin):
    """
    Fundamental analysis agent that values companies using 5 methods.
    """

    CHAT_SYSTEM_PROMPT = FUNDAMENTAL_CHAT_PROMPT
    desk_name = "fundamental"

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._ensure_state_dir()

    def _ensure_state_dir(self):
        """Ensure state directory exists."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _load_valuations(self) -> List[dict]:
        """Load all valuations from state file."""
        if FUNDAMENTAL_STATE_FILE.exists():
            try:
                with open(FUNDAMENTAL_STATE_FILE, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load valuations: {e}")
        return []

    def _save_valuation(self, valuation: dict):
        """Save valuation to state file."""
        valuations = self._load_valuations()
        valuations.append(valuation)
        # Keep last 100 valuations
        valuations = valuations[-100:]

        with open(FUNDAMENTAL_STATE_FILE, "w") as f:
            json.dump(valuations, f, indent=2, default=str)

        logger.info(f"[{self.desk_name}] Saved valuation for {valuation.get('ticker')}")

    def load_latest_brief(self) -> Optional[dict]:
        """Load the most recent valuation for chat context."""
        valuations = self._load_valuations()
        if valuations:
            return valuations[-1]
        return None

    def gather_financials(self, ticker: str) -> dict:
        """
        Gather comprehensive financial data from yfinance.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Structured financial data dict
        """
        logger.info(f"[{self.desk_name}] Gathering financials for {ticker}...")

        # Retry logic with exponential backoff for rate limits
        max_retries = 3
        base_delay = 5

        for attempt in range(max_retries):
            try:
                stock = yf.Ticker(ticker)
                info = stock.info or {}

                # Check for rate limit indicator
                if not info or (info.get("regularMarketPrice") is None and info.get("currentPrice") is None):
                    raise Exception("Empty response - possible rate limit")

                break  # Success, exit retry loop

            except Exception as e:
                error_msg = str(e).lower()
                if "rate" in error_msg or "too many" in error_msg or "empty response" in error_msg:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 2)
                        logger.warning(f"  Rate limited, waiting {delay:.1f}s before retry {attempt + 2}/{max_retries}")
                        time.sleep(delay)
                        continue
                raise  # Re-raise if not rate limit or out of retries

        info = stock.info or {}

        # Basic info
        financials = {
            "ticker": ticker,
            "company_name": info.get("longName") or info.get("shortName", ticker),
            "sector": info.get("sector", "Unknown"),
            "industry": info.get("industry", "Unknown"),
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "share_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
        }

        # Income Statement
        try:
            income_stmt = stock.financials
            quarterly_income = stock.quarterly_financials

            # Get TTM revenue
            revenue_ttm = info.get("totalRevenue")
            revenue_prev = None

            # Try to get historical revenue for growth
            if income_stmt is not None and not income_stmt.empty:
                if "Total Revenue" in income_stmt.index:
                    rev_series = income_stmt.loc["Total Revenue"]
                    if len(rev_series) >= 2:
                        revenue_prev = rev_series.iloc[1]

            # Calculate growth
            revenue_growth = None
            if revenue_ttm and revenue_prev and revenue_prev > 0:
                revenue_growth = ((revenue_ttm - revenue_prev) / revenue_prev) * 100

            gross_profit = info.get("grossProfits")
            gross_margin = None
            if gross_profit and revenue_ttm and revenue_ttm > 0:
                gross_margin = (gross_profit / revenue_ttm) * 100

            operating_income = info.get("operatingIncome")
            operating_margin = info.get("operatingMargins")
            if operating_margin:
                operating_margin = operating_margin * 100

            net_income = info.get("netIncomeToCommon")
            net_margin = info.get("profitMargins")
            if net_margin:
                net_margin = net_margin * 100

            ebitda = info.get("ebitda")

            eps = info.get("trailingEps")
            eps_forward = info.get("forwardEps")

            financials["income_statement"] = {
                "revenue_ttm": format_large_number(revenue_ttm),
                "revenue_growth_yoy": f"{revenue_growth:.1f}%" if revenue_growth else "N/A",
                "gross_profit": format_large_number(gross_profit),
                "gross_margin": f"{gross_margin:.1f}%" if gross_margin else "N/A",
                "operating_income": format_large_number(operating_income),
                "operating_margin": f"{operating_margin:.1f}%" if operating_margin else "N/A",
                "net_income": format_large_number(net_income),
                "net_margin": f"{net_margin:.1f}%" if net_margin else "N/A",
                "ebitda": format_large_number(ebitda),
                "eps": f"${eps:.2f}" if eps else "N/A",
                "eps_forward": f"${eps_forward:.2f}" if eps_forward else "N/A",
            }
        except Exception as e:
            logger.warning(f"Error gathering income statement: {e}")
            financials["income_statement"] = {}

        # Balance Sheet
        try:
            balance = stock.balance_sheet

            cash = info.get("totalCash")
            total_debt = info.get("totalDebt")
            net_debt = (total_debt - cash) if (total_debt and cash) else None

            total_assets = None
            total_liabilities = None
            total_equity = None
            goodwill = None

            if balance is not None and not balance.empty:
                if "Total Assets" in balance.index:
                    total_assets = balance.loc["Total Assets"].iloc[0]
                if "Total Liabilities Net Minority Interest" in balance.index:
                    total_liabilities = balance.loc["Total Liabilities Net Minority Interest"].iloc[0]
                elif "Total Liab" in balance.index:
                    total_liabilities = balance.loc["Total Liab"].iloc[0]
                if "Total Stockholder Equity" in balance.index:
                    total_equity = balance.loc["Total Stockholder Equity"].iloc[0]
                elif "Stockholders Equity" in balance.index:
                    total_equity = balance.loc["Stockholders Equity"].iloc[0]
                if "Goodwill" in balance.index:
                    goodwill = balance.loc["Goodwill"].iloc[0]

            book_value = info.get("bookValue")
            debt_to_equity = info.get("debtToEquity")
            current_ratio = info.get("currentRatio")

            # Calculate tangible book
            tangible_book = None
            if book_value and goodwill and financials.get("shares_outstanding"):
                tangible_book = book_value - (goodwill / financials["shares_outstanding"])

            financials["balance_sheet"] = {
                "cash_and_equivalents": format_large_number(cash),
                "total_debt": format_large_number(total_debt),
                "net_debt": format_large_number(net_debt),
                "total_assets": format_large_number(total_assets),
                "total_liabilities": format_large_number(total_liabilities),
                "total_equity": format_large_number(total_equity),
                "goodwill": format_large_number(goodwill),
                "book_value_per_share": f"${book_value:.2f}" if book_value else "N/A",
                "tangible_book_value": f"${tangible_book:.2f}" if tangible_book else "N/A",
                "current_ratio": f"{current_ratio:.2f}" if current_ratio else "N/A",
                "debt_to_equity": f"{debt_to_equity:.2f}" if debt_to_equity else "N/A",
            }

            # Debt/EBITDA
            if total_debt and ebitda and ebitda > 0:
                financials["balance_sheet"]["debt_to_ebitda"] = f"{total_debt/ebitda:.2f}x"

        except Exception as e:
            logger.warning(f"Error gathering balance sheet: {e}")
            financials["balance_sheet"] = {}

        # Cash Flow
        try:
            cashflow = stock.cashflow

            operating_cf = info.get("operatingCashflow")
            fcf = info.get("freeCashflow")

            capex = None
            if cashflow is not None and not cashflow.empty:
                if "Capital Expenditure" in cashflow.index:
                    capex = abs(cashflow.loc["Capital Expenditure"].iloc[0])
                elif "Capital Expenditures" in cashflow.index:
                    capex = abs(cashflow.loc["Capital Expenditures"].iloc[0])

            fcf_margin = None
            if fcf and revenue_ttm and revenue_ttm > 0:
                fcf_margin = (fcf / revenue_ttm) * 100

            fcf_per_share = None
            if fcf and financials.get("shares_outstanding"):
                fcf_per_share = fcf / financials["shares_outstanding"]

            fcf_yield = None
            if fcf and financials.get("market_cap") and financials["market_cap"] > 0:
                fcf_yield = (fcf / financials["market_cap"]) * 100

            dividends = None
            if cashflow is not None and not cashflow.empty:
                if "Cash Dividends Paid" in cashflow.index:
                    dividends = abs(cashflow.loc["Cash Dividends Paid"].iloc[0])
                elif "Dividends Paid" in cashflow.index:
                    dividends = abs(cashflow.loc["Dividends Paid"].iloc[0])

            buybacks = None
            if cashflow is not None and not cashflow.empty:
                if "Repurchase Of Capital Stock" in cashflow.index:
                    buybacks = abs(cashflow.loc["Repurchase Of Capital Stock"].iloc[0])

            financials["cash_flow"] = {
                "operating_cash_flow": format_large_number(operating_cf),
                "capex": format_large_number(capex),
                "free_cash_flow": format_large_number(fcf),
                "fcf_margin": f"{fcf_margin:.1f}%" if fcf_margin else "N/A",
                "fcf_per_share": f"${fcf_per_share:.2f}" if fcf_per_share else "N/A",
                "fcf_yield": f"{fcf_yield:.1f}%" if fcf_yield else "N/A",
                "dividends_paid": format_large_number(dividends),
                "buybacks": format_large_number(buybacks),
            }

        except Exception as e:
            logger.warning(f"Error gathering cash flow: {e}")
            financials["cash_flow"] = {}

        # Valuation Multiples
        try:
            pe = info.get("trailingPE")
            forward_pe = info.get("forwardPE")
            peg = info.get("pegRatio")
            ps = info.get("priceToSalesTrailing12Months")
            pb = info.get("priceToBook")
            ev_ebitda = info.get("enterpriseToEbitda")
            ev_revenue = info.get("enterpriseToRevenue")
            dividend_yield = info.get("dividendYield")
            if dividend_yield:
                dividend_yield = dividend_yield * 100

            financials["valuation_multiples"] = {
                "pe_ratio": f"{pe:.1f}x" if pe else "N/A",
                "forward_pe": f"{forward_pe:.1f}x" if forward_pe else "N/A",
                "peg_ratio": f"{peg:.2f}" if peg else "N/A",
                "ps_ratio": f"{ps:.2f}x" if ps else "N/A",
                "pb_ratio": f"{pb:.2f}x" if pb else "N/A",
                "ev_ebitda": f"{ev_ebitda:.1f}x" if ev_ebitda else "N/A",
                "ev_revenue": f"{ev_revenue:.2f}x" if ev_revenue else "N/A",
                "dividend_yield": f"{dividend_yield:.2f}%" if dividend_yield else "N/A",
            }
        except Exception as e:
            logger.warning(f"Error gathering multiples: {e}")
            financials["valuation_multiples"] = {}

        # Historical Data (5 years)
        try:
            income_hist = stock.financials
            cf_hist = stock.cashflow

            rev_history = []
            fcf_history = []

            if income_hist is not None and not income_hist.empty:
                if "Total Revenue" in income_hist.index:
                    for val in income_hist.loc["Total Revenue"].values[:5]:
                        if pd.notna(val):
                            rev_history.append(format_large_number(val))

            if cf_hist is not None and not cf_hist.empty:
                if "Free Cash Flow" in cf_hist.index:
                    for val in cf_hist.loc["Free Cash Flow"].values[:5]:
                        if pd.notna(val):
                            fcf_history.append(format_large_number(val))

            financials["historical"] = {
                "revenue_5yr": rev_history[::-1] if rev_history else [],  # Reverse to chronological
                "fcf_5yr": fcf_history[::-1] if fcf_history else [],
            }
        except Exception as e:
            logger.warning(f"Error gathering historical data: {e}")
            financials["historical"] = {}

        # Analyst Estimates
        try:
            target_mean = info.get("targetMeanPrice")
            target_high = info.get("targetHighPrice")
            target_low = info.get("targetLowPrice")
            num_analysts = info.get("numberOfAnalystOpinions")
            earnings_growth = info.get("earningsGrowth")
            revenue_growth_est = info.get("revenueGrowth")

            financials["analyst_estimates"] = {
                "target_price_mean": f"${target_mean:.2f}" if target_mean else "N/A",
                "target_price_high": f"${target_high:.2f}" if target_high else "N/A",
                "target_price_low": f"${target_low:.2f}" if target_low else "N/A",
                "num_analysts": num_analysts,
                "earnings_growth_est": f"{earnings_growth*100:.1f}%" if earnings_growth else "N/A",
                "revenue_growth_est": f"{revenue_growth_est*100:.1f}%" if revenue_growth_est else "N/A",
            }
        except Exception as e:
            logger.warning(f"Error gathering analyst estimates: {e}")
            financials["analyst_estimates"] = {}

        return financials

    def gather_comparables(self, ticker: str, sector: str) -> List[dict]:
        """
        Gather comparable company data for relative valuation.

        Args:
            ticker: Target ticker (to exclude from comps)
            sector: Sector for finding comparables

        Returns:
            List of comparable company data dicts
        """
        logger.info(f"[{self.desk_name}] Gathering comparable companies for {sector}...")

        # Get potential comparables
        comp_tickers = SECTOR_COMPARABLES.get(sector, [])
        if not comp_tickers:
            # Try to find sector matches
            for sec, tickers in SECTOR_COMPARABLES.items():
                if sec.lower() in sector.lower() or sector.lower() in sec.lower():
                    comp_tickers = tickers
                    break

        # Filter out target ticker and limit to 5
        comp_tickers = [t for t in comp_tickers if t != ticker][:5]

        comparables = []
        for comp_ticker in comp_tickers:
            try:
                stock = yf.Ticker(comp_ticker)
                info = stock.info or {}

                comparables.append({
                    "ticker": comp_ticker,
                    "name": info.get("shortName", comp_ticker),
                    "market_cap": format_large_number(info.get("marketCap")),
                    "ev_ebitda": info.get("enterpriseToEbitda"),
                    "ev_revenue": info.get("enterpriseToRevenue"),
                    "pe_ratio": info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                    "pb_ratio": info.get("priceToBook"),
                    "gross_margin": f"{info.get('grossMargins', 0)*100:.1f}%" if info.get("grossMargins") else "N/A",
                    "operating_margin": f"{info.get('operatingMargins', 0)*100:.1f}%" if info.get("operatingMargins") else "N/A",
                    "revenue_growth": f"{info.get('revenueGrowth', 0)*100:.1f}%" if info.get("revenueGrowth") else "N/A",
                })
            except Exception as e:
                logger.warning(f"Error gathering comp data for {comp_ticker}: {e}")

        return comparables

    def analyze(self, ticker: str = None, financials: dict = None,
                persist: bool = True) -> Optional[dict]:
        """
        Run full fundamental analysis on a company.

        Args:
            ticker: Stock ticker (if financials not provided)
            financials: Pre-structured financial data (optional)
            persist: If True, save result to state file

        Returns:
            Structured valuation dict or None if analysis fails
        """
        # Gather financials if not provided
        if financials is None:
            if ticker is None:
                raise ValueError("Must provide either ticker or financials")
            financials = self.gather_financials(ticker)
        else:
            ticker = financials.get("ticker")

        logger.info(f"[{self.desk_name}] Running fundamental analysis on {ticker}...")

        # Gather comparable companies
        sector = financials.get("sector", "Technology")
        comparables = self.gather_comparables(ticker, sector)

        # Build the prompt
        user_prompt = build_analysis_prompt(financials, comparables)

        # Call Claude
        logger.info(f"[{self.desk_name}] Calling Claude for {ticker} valuation...")
        try:
            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )
            raw_response = response.content[0].text
        except Exception as e:
            logger.error(f"[{self.desk_name}] Claude API error: {e}")
            return None

        # Parse JSON response
        try:
            if "```json" in raw_response:
                json_str = raw_response.split("```json")[1].split("```")[0]
            elif "```" in raw_response:
                json_str = raw_response.split("```")[1].split("```")[0]
            else:
                json_str = raw_response

            valuation = json.loads(json_str.strip())
            valuation["desk"] = self.desk_name
            valuation["analyzed_at"] = datetime.utcnow().isoformat()
            valuation["model_used"] = CLAUDE_MODEL

            verdict = valuation.get("synthesis", {}).get("verdict", "UNKNOWN")
            confidence = valuation.get("synthesis", {}).get("confidence", 0)
            logger.info(f"[{self.desk_name}] {ticker}: {verdict} (confidence: {confidence}%)")

            # Persist if requested
            if persist:
                self._save_valuation(valuation)

            return valuation

        except json.JSONDecodeError as e:
            logger.error(f"[{self.desk_name}] Failed to parse Claude response: {e}")
            logger.debug(f"Raw response: {raw_response[:1000]}...")
            return None

    def screen(self, tickers: List[str], persist: bool = True) -> List[dict]:
        """
        Quick screen multiple tickers.

        Args:
            tickers: List of tickers to screen
            persist: If True, save results

        Returns:
            List of valuation dicts
        """
        results = []
        for ticker in tickers:
            try:
                valuation = self.analyze(ticker, persist=persist)
                if valuation:
                    results.append(valuation)
            except Exception as e:
                logger.error(f"Error analyzing {ticker}: {e}")

        return results

    def get_brief_for_cio(self, ticker: str) -> Optional[dict]:
        """
        Get a brief valuation summary for the CIO agent.

        Args:
            ticker: Stock ticker

        Returns:
            Dict with valuation summary
        """
        # Check for recent valuation in state
        valuations = self._load_valuations()
        for v in reversed(valuations):
            if v.get("ticker") == ticker:
                analyzed_at = v.get("analyzed_at", "")
                try:
                    analysis_time = datetime.fromisoformat(analyzed_at)
                    age_hours = (datetime.utcnow() - analysis_time).total_seconds() / 3600
                    if age_hours < 24:  # Use cached if less than 24 hours old
                        logger.info(f"[{self.desk_name}] Using cached valuation from {age_hours:.1f} hours ago")
                        synthesis = v.get("synthesis", {})
                        return {
                            "desk": self.desk_name,
                            "ticker": ticker,
                            "verdict": synthesis.get("verdict"),
                            "confidence": synthesis.get("confidence"),
                            "intrinsic_value_midpoint": synthesis.get("intrinsic_value_midpoint"),
                            "current_price": v.get("current_price"),
                            "upside_pct": synthesis.get("upside_to_midpoint_pct"),
                            "margin_of_safety_pct": synthesis.get("margin_of_safety_pct"),
                            "brief": v.get("brief_for_cio"),
                            "analyzed_at": analyzed_at,
                        }
                except (ValueError, TypeError):
                    pass

        # Run fresh analysis
        valuation = self.analyze(ticker, persist=True)
        if valuation:
            synthesis = valuation.get("synthesis", {})
            return {
                "desk": self.desk_name,
                "ticker": ticker,
                "verdict": synthesis.get("verdict"),
                "confidence": synthesis.get("confidence"),
                "intrinsic_value_midpoint": synthesis.get("intrinsic_value_midpoint"),
                "current_price": valuation.get("current_price"),
                "upside_pct": synthesis.get("upside_to_midpoint_pct"),
                "margin_of_safety_pct": synthesis.get("margin_of_safety_pct"),
                "brief": valuation.get("brief_for_cio"),
                "analyzed_at": valuation.get("analyzed_at"),
            }
        return None


def run_fundamental_analysis(ticker: str, persist: bool = True) -> Optional[dict]:
    """Convenience function to run fundamental analysis."""
    agent = FundamentalAgent()
    return agent.analyze(ticker, persist=persist)


def print_valuation_summary(valuation: dict):
    """Print a formatted summary of the valuation."""
    ticker = valuation.get("ticker", "UNKNOWN")
    company = valuation.get("company_name", "")
    synthesis = valuation.get("synthesis", {})

    print("\n" + "=" * 70)
    print(f"FUNDAMENTAL VALUATION: {ticker} - {company}")
    print("=" * 70)

    print(f"\nCurrent Price: ${valuation.get('current_price', 'N/A')}")
    print(f"Market Cap: {format_large_number(valuation.get('market_cap'))}")

    # DCF
    dcf = valuation.get("dcf_valuation", {})
    print(f"\n--- DCF VALUATION ---")
    print(f"Base Case: ${dcf.get('base_case', 'N/A')}")
    print(f"Bull Case: ${dcf.get('bull_case', 'N/A')}")
    print(f"Bear Case: ${dcf.get('bear_case', 'N/A')}")
    assumptions = dcf.get("key_assumptions", {})
    if assumptions:
        print(f"  WACC: {assumptions.get('wacc', 'N/A')}")
        print(f"  Terminal Growth: {assumptions.get('terminal_growth', 'N/A')}")

    # Comps
    comps = valuation.get("comps_valuation", {})
    print(f"\n--- COMPARABLE ANALYSIS ---")
    print(f"Fair Value Range: ${comps.get('fair_value_range_low', 'N/A')} - ${comps.get('fair_value_range_high', 'N/A')}")
    print(f"Premium/Discount: {comps.get('premium_or_discount', 'N/A')}")

    # SOTP
    sotp = valuation.get("sotp_valuation", {})
    if sotp.get("per_share_value"):
        print(f"\n--- SUM OF THE PARTS ---")
        print(f"Per Share Value: ${sotp.get('per_share_value', 'N/A')}")

    # Asset-Based
    asset = valuation.get("asset_based_valuation", {})
    print(f"\n--- ASSET-BASED ---")
    print(f"Book Value/Share: {asset.get('book_value_per_share', 'N/A')}")
    print(f"Tangible Book: {asset.get('tangible_book_per_share', 'N/A')}")
    print(f"Relevance: {asset.get('relevance', 'N/A')}")

    # Synthesis
    print(f"\n--- SYNTHESIS ---")
    print(f"Intrinsic Value Range: ${synthesis.get('intrinsic_value_low', 'N/A')} - ${synthesis.get('intrinsic_value_high', 'N/A')}")
    print(f"Midpoint: ${synthesis.get('intrinsic_value_midpoint', 'N/A')}")
    print(f"Upside/Downside: {synthesis.get('upside_to_midpoint_pct', 'N/A')}%")
    print(f"Margin of Safety: {synthesis.get('margin_of_safety_pct', 'N/A')}%")
    print(f"\nVERDICT: {synthesis.get('verdict', 'UNKNOWN')}")
    print(f"Confidence: {synthesis.get('confidence', 0)}%")

    # Risks and Catalysts
    risks = synthesis.get("key_risks", [])
    if risks:
        print(f"\nKey Risks:")
        for r in risks[:3]:
            print(f"  - {r}")

    catalysts = synthesis.get("key_catalysts", [])
    if catalysts:
        print(f"\nKey Catalysts:")
        for c in catalysts[:3]:
            print(f"  - {c}")

    # CIO Brief
    print(f"\n--- CIO BRIEF ---")
    print(valuation.get("brief_for_cio", "N/A"))


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(description="ATLAS Fundamental Analysis Agent")
    parser.add_argument("--ticker", help="Single ticker to analyze")
    parser.add_argument("--input", help="JSON file with financials to analyze")
    parser.add_argument("--screen", help="Comma-separated list of tickers to screen")
    parser.add_argument("--portfolio", action="store_true", help="Analyze portfolio holdings")
    parser.add_argument("--no-persist", action="store_true", help="Don't save results")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("ATLAS Fundamental Analysis Agent - The Valuation Engine")
    print("=" * 70 + "\n")

    agent = FundamentalAgent()

    if args.input:
        # Load financials from JSON file
        with open(args.input, "r") as f:
            financials = json.load(f)
        result = agent.analyze(financials=financials, persist=not args.no_persist)
        if result:
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print_valuation_summary(result)

    elif args.screen:
        # Screen multiple tickers
        tickers = [t.strip() for t in args.screen.split(",")]
        print(f"Screening {len(tickers)} tickers: {', '.join(tickers)}\n")
        results = agent.screen(tickers, persist=not args.no_persist)

        print("\n" + "=" * 70)
        print("SCREENING RESULTS")
        print("=" * 70)
        for r in results:
            synth = r.get("synthesis", {})
            print(f"\n{r.get('ticker')}: {synth.get('verdict')} | "
                  f"Confidence: {synth.get('confidence')}% | "
                  f"Upside: {synth.get('upside_to_midpoint_pct')}%")
            print(f"  Intrinsic: ${synth.get('intrinsic_value_low')}-${synth.get('intrinsic_value_high')} "
                  f"vs Current: ${r.get('current_price')}")

    elif args.ticker:
        # Analyze single ticker
        print(f"Analyzing {args.ticker}...\n")
        result = agent.analyze(args.ticker, persist=not args.no_persist)
        if result:
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print_valuation_summary(result)
                print("\n" + "-" * 70)
                print("Full JSON output available with --json flag")

    elif args.portfolio:
        # Analyze portfolio (import from config)
        try:
            from config.universe import UNIVERSE
            tickers = list(UNIVERSE.keys())[:10]  # Top 10
            print(f"Analyzing portfolio ({len(tickers)} stocks)...\n")
            results = agent.screen(tickers, persist=not args.no_persist)
            for r in results:
                print_valuation_summary(r)
        except ImportError:
            print("Could not import portfolio universe")

    else:
        print("Usage examples:")
        print("  python -m agents.fundamental_agent --ticker AVGO")
        print("  python -m agents.fundamental_agent --screen AVGO,NVDA,AMD,LLY,PFE")
        print("  python -m agents.fundamental_agent --input data/financials/avgo.json")
        print("  python -m agents.fundamental_agent --portfolio")
