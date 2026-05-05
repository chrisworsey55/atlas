from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL
from graham.config import MEMO_CACHE_DIR, MEMO_OUTPUT_DIR, ensure_dirs
from graham.models import NCAVResult


class GrahamMemoAgent:
    def __init__(self, use_llm: bool = True):
        ensure_dirs()
        self.use_llm = use_llm
        self.client = None
        if use_llm and ANTHROPIC_API_KEY:
            try:
                import anthropic

                self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            except Exception:
                self.client = None

    def generate_memo(self, result: NCAVResult) -> str:
        cached = self.get_cached_memo(result.cik, result.filing_date or "unknown")
        if cached:
            self._write_output(result, cached)
            return cached
        sections = self._generate_sections(result)
        memo = self._assemble_memo(result, sections)
        self._cache_path(result.cik, result.filing_date or "unknown").write_text(memo)
        self._write_output(result, memo)
        return memo

    def batch_generate(self, results: list[NCAVResult]) -> list[str]:
        cached: dict[str, str] = {}
        uncached: list[NCAVResult] = []
        for result in results:
            key = self._cache_key(result)
            memo = self.get_cached_memo(result.cik, result.filing_date or "unknown")
            if memo:
                cached[key] = memo
                self._write_output(result, memo)
            else:
                uncached.append(result)
        generated_sections = self._batch_sections(uncached) if uncached else {}
        for result in uncached:
            key = self._cache_key(result)
            sections = generated_sections.get(key) or self._generate_sections(result)
            memo = self._assemble_memo(result, sections)
            self._cache_path(result.cik, result.filing_date or "unknown").write_text(memo)
            self._write_output(result, memo)
            cached[key] = memo
        return [cached[self._cache_key(result)] for result in results if self._cache_key(result) in cached]

    def get_cached_memo(self, cik: str, filing_date: str) -> str | None:
        path = self._cache_path(cik, filing_date)
        return path.read_text() if path.exists() else None

    def _generate_sections(self, result: NCAVResult) -> str:
        if self.client:
            prompt = self._prompt(result)
            try:
                response = self.client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=900,
                    temperature=0.2,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
                if all(header in text for header in ["WHY IS IT CHEAP", "THE CATALYST", "THE RISKS"]):
                    return text.strip()
            except Exception:
                pass
        return self._fallback_sections(result)

    def _batch_sections(self, results: list[NCAVResult], timeout_seconds: int = 900) -> dict[str, str]:
        if not results or not self.client or not hasattr(getattr(self.client, "beta", None), "messages"):
            return {}
        try:
            requests = [
                {
                    "custom_id": self._cache_key(result),
                    "params": {
                        "model": CLAUDE_MODEL,
                        "max_tokens": 900,
                        "temperature": 0.2,
                        "messages": [{"role": "user", "content": self._prompt(result)}],
                    },
                }
                for result in results
            ]
            batch = self.client.beta.messages.batches.create(requests=requests)
            deadline = time.time() + timeout_seconds
            while time.time() < deadline:
                batch = self.client.beta.messages.batches.retrieve(batch.id)
                if getattr(batch, "processing_status", None) == "ended":
                    break
                time.sleep(10)
            if getattr(batch, "processing_status", None) != "ended":
                return {}
            sections: dict[str, str] = {}
            for item in self.client.beta.messages.batches.results(batch.id):
                custom_id = getattr(item, "custom_id", None)
                result_obj = getattr(item, "result", None)
                message = getattr(result_obj, "message", None)
                if not custom_id or not message:
                    continue
                text = "".join(block.text for block in message.content if getattr(block, "type", "") == "text").strip()
                if all(header in text for header in ["WHY IS IT CHEAP", "THE CATALYST", "THE RISKS"]):
                    sections[custom_id] = text
            return sections
        except Exception:
            return {}

    def _prompt(self, result: NCAVResult) -> str:
        return f"""You are analyzing {result.company_name} ({result.ticker}) for the
Graham net-net screen. Price is {self._fmt_ratio(result.price_to_ncav)}x NCAV —
a {self._fmt_pct(result.ncav_discount_pct)}% discount.
Filing: {result.filing_type} dated {result.filing_date}
Balance sheet summary:
Current assets: {result.current_assets}
Total liabilities: {result.total_liabilities}
Cash: {result.cash}
Receivables: {result.receivables}
Inventory: {result.inventory}
Revenue last 3 years: {result.revenue_history}
Business description (Item 1, first 300 words):
{self._clip(result.business_description, 1800)}
Risk factors (Item 1A, first 300 words):
{self._clip(result.risk_factors, 1800)}
Write exactly three sections:
═══ WHY IS IT CHEAP ═══
[3 sentences, specific to this company, not generic]
═══ THE CATALYST ═══
[3 sentences, what could close this discount]
═══ THE RISKS ═══
[Top 3 specific risks, named from the filing]
Output only these three sections with exact headers."""

    def _fallback_sections(self, result: NCAVResult) -> str:
        business = self._sentence(result.business_description) or "The latest filing provides limited business-description detail in the automated extract."
        risk = self._sentence(result.risk_factors) or "The automated extract did not capture detailed risk factors, so the original filing must be checked."
        return f"""═══ WHY IS IT CHEAP ═══
The market is pricing {result.ticker} at {self._fmt_ratio(result.price_to_ncav)}x NCAV despite reported current assets above liabilities. The likely discount reflects OTC micro-cap neglect, limited liquidity, and weak filing/data visibility. {business}
═══ THE CATALYST ═══
The discount could close through a buyout, liquidation of excess working capital, buybacks, or a return to more normal investor attention after fresh filings. Balance-sheet value realization is the core catalyst rather than an earnings forecast. Any improvement in liquidity or disclosure quality would make the NCAV discount easier for investors to underwrite.
═══ THE RISKS ═══
1. {risk}
2. Liquidity is limited, so building or exiting a position may take {result.days_to_build_500k_position or 'many'} trading days at 20% of average dollar volume.
3. The NCAV calculation depends on {result.data_source} data and must be verified against the original SEC filing before any investment decision."""

    def _assemble_memo(self, result: NCAVResult, sections: str) -> str:
        generated = datetime.now(timezone.utc).date().isoformat()
        return f"""GRAHAM MEMO — {result.ticker} — {result.company_name}
Generated: {generated} | Filing: {result.filing_date}
═══ THE NUMBER ═══
Current Price:        ${self._money(result.current_price)}
NCAV Per Share:       ${self._money(result.ncav_per_share)}
Price / NCAV:         {self._fmt_ratio(result.price_to_ncav)}x  ({self._fmt_pct(result.ncav_discount_pct)}% discount)
Market Cap:           ${self._money(result.market_cap)}
Avg Daily Volume:     ${self._money(result.avg_daily_volume)}
═══ THE BUSINESS ═══
What it does: {self._sentence(result.business_description) or 'Business description requires manual filing review.'}
Sector: {result.sic_description or result.sic_code or 'Unknown'}
Employees: {result.employee_count if result.employee_count is not None else 'Unknown'}
Revenue (TTM): ${self._money(result.revenue)}
Revenue trend: {self._revenue_trend(result.revenue_history)}
═══ THE BALANCE SHEET ═══
Current Assets:       ${self._money(result.current_assets)}
Cash:               ${self._money(result.cash)}
Receivables:        ${self._money(result.receivables)}
Inventory:          ${self._money(result.inventory)}
Total Liabilities:    ${self._money(result.total_liabilities)}
Current:            ${self._money(result.current_liabilities)}
Long-term debt:     ${self._money(result.long_term_debt)}
NCAV:                 ${self._money(result.ncav)}
{sections}
═══ LIQUIDITY NOTE ═══
At 20% of avg daily volume, a $500K position takes
approximately {result.days_to_build_500k_position or 'N/A'} trading days to build.
═══ VERDICT ═══
NCAV quality: {result.ncav_quality}
Memo confidence: {self._confidence(result)}
HUMAN REVIEW REQUIRED — This memo is a research starting
point, not an investment recommendation. Verify all figures
against the original SEC filing before acting.
Source: {result.filing_url or 'Unknown'}
"""

    def _write_output(self, result: NCAVResult, memo: str) -> Path:
        date = datetime.now(timezone.utc).date().isoformat()
        path = MEMO_OUTPUT_DIR / f"{self._safe(result.ticker)}_{date}.md"
        path.write_text(memo)
        return path

    def _cache_path(self, cik: str, filing_date: str) -> Path:
        return MEMO_CACHE_DIR / f"{cik}_{filing_date}.txt"

    @staticmethod
    def _cache_key(result: NCAVResult) -> str:
        return f"{result.cik}_{result.filing_date or 'unknown'}"

    @staticmethod
    def _safe(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", value)

    @staticmethod
    def _clip(value: str | None, limit: int) -> str:
        return (value or "")[:limit]

    @staticmethod
    def _sentence(value: str | None) -> str | None:
        if not value:
            return None
        clean = re.sub(r"\s+", " ", value).strip()
        parts = re.split(r"(?<=[.!?])\s+", clean)
        return " ".join(parts[:2])[:500]

    @staticmethod
    def _money(value: float | None) -> str:
        if value is None:
            return "N/A"
        return f"{value:,.2f}"

    @staticmethod
    def _fmt_ratio(value: float | None) -> str:
        return "N/A" if value is None else f"{value:.2f}"

    @staticmethod
    def _fmt_pct(value: float | None) -> str:
        return "N/A" if value is None else f"{value:.1f}"

    @staticmethod
    def _revenue_trend(history: list[float]) -> str:
        if len(history) < 2:
            return "unknown"
        latest, prior = history[0], history[-1]
        if latest > prior * 1.05:
            return "growing"
        if latest < prior * 0.95:
            return "declining"
        return "flat"

    @staticmethod
    def _confidence(result: NCAVResult) -> str:
        if result.data_quality_flag == "XBRL_OK" and not result.is_stale:
            return "HIGH"
        if result.data_quality_flag == "HTML_FALLBACK" and not result.is_stale:
            return "MEDIUM"
        return "LOW"
