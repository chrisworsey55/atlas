from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from graham.config import CACHE_DIR, STALE_FILING_DAYS, ensure_dirs
from graham.edgar import GrahamEdgarClient
from graham.models import Company, NCAVResult
from graham.price import PriceClient
from graham.universe import GrahamUniverse


class NCAVCalculator:
    def __init__(self, edgar: GrahamEdgarClient | None = None, price_client: PriceClient | None = None):
        ensure_dirs()
        self.edgar = edgar or GrahamEdgarClient()
        self.price_client = price_client or PriceClient()
        self.company_map = {company.cik: company for company in GrahamUniverse(edgar=self.edgar, price_client=self.price_client).get_cached()}

    def calculate(self, cik: str) -> NCAVResult:
        cik = GrahamEdgarClient.normalize_cik(cik)
        company = self.company_map.get(cik)
        submissions = self.edgar.get_submissions_by_cik(cik)
        latest = self.edgar.latest_10k_10q_by_filing_date(cik)
        ticker = company.ticker if company else self._first_ticker(submissions)
        name = company.company_name if company else (submissions or {}).get("name", cik)
        result = NCAVResult(
            cik=cik,
            ticker=ticker or cik,
            company_name=name,
            filing_date=latest.get("filing_date") if latest else None,
            filing_type=latest.get("form_type") if latest else None,
            is_stale=self._is_stale(latest.get("filing_date") if latest else None),
            data_quality_flag="PENDING",
            sic_code=(company.sic_code if company else str((submissions or {}).get("sic") or "") or None),
            sic_description=(company.sic_description if company else (submissions or {}).get("sicDescription")),
            filing_url=latest.get("filing_url") if latest else None,
        )
        if not latest:
            result.data_quality_flag = "MANUAL_REVIEW"
            return result

        if company and company.current_price:
            self._attach_company_price(result, company)
        else:
            price = self.price_client.get_price(result.ticker)
            result.current_price = price.current_price
            result.market_cap = price.market_cap
            result.avg_daily_volume = price.avg_daily_volume
            result.days_to_build_500k_position = price.days_to_build_500k_position

        facts = self.edgar.get_company_facts_by_cik(cik)
        if facts:
            self._populate_from_xbrl(result, facts, latest.get("accession_number"))

        if not self._has_required_ncav(result):
            html_values = self._parse_html_filing(latest)
            if html_values:
                self._populate_from_html(result, html_values)

        self._finalize(result)
        return result

    def batch_calculate(self, ciks: list[str]) -> list[NCAVResult]:
        results = [self.calculate(cik) for cik in ciks]
        self._write_cache(results)
        return results

    def _populate_from_xbrl(self, result: NCAVResult, facts: dict[str, Any], accession: str | None) -> None:
        result.current_assets = self._fact(facts, "us-gaap", "AssetsCurrent", accession, "USD")
        result.total_liabilities = self._fact(facts, "us-gaap", "Liabilities", accession, "USD")
        result.shares_outstanding = (
            self._fact(facts, "us-gaap", "CommonStockSharesOutstanding", accession, "shares")
            or self._fact(facts, "dei", "EntityCommonStockSharesOutstanding", accession, "shares")
        )
        result.cash = self._fact(facts, "us-gaap", "CashAndCashEquivalentsAtCarryingValue", accession, "USD")
        result.receivables = (
            self._fact(facts, "us-gaap", "AccountsReceivableNetCurrent", accession, "USD")
            or self._fact(facts, "us-gaap", "ReceivablesNetCurrent", accession, "USD")
        )
        result.inventory = self._fact(facts, "us-gaap", "InventoryNet", accession, "USD")
        result.current_liabilities = self._fact(facts, "us-gaap", "LiabilitiesCurrent", accession, "USD")
        result.long_term_debt = (
            self._fact(facts, "us-gaap", "LongTermDebtNoncurrent", accession, "USD")
            or self._fact(facts, "us-gaap", "LongTermDebt", accession, "USD")
        )
        result.revenue = (
            self._fact(facts, "us-gaap", "Revenues", accession, "USD")
            or self._fact(facts, "us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", accession, "USD")
        )
        result.revenue_history = self.edgar.annual_fact_history(facts, "Revenues") or self.edgar.annual_fact_history(
            facts, "RevenueFromContractWithCustomerExcludingAssessedTax"
        )
        result.data_source = "XBRL"
        result.data_quality_flag = "XBRL_OK" if self._has_required_ncav(result) else "XBRL_GAPS"

    def _fact(self, facts: dict[str, Any], taxonomy: str, tag: str, accession: str | None, unit: str) -> float | None:
        units = facts.get("facts", {}).get(taxonomy, {}).get(tag, {}).get("units", {})
        values = units.get(unit) or units.get("USD") or units.get("shares") or []
        values = [value for value in values if value.get("form") in {"10-K", "10-Q"} and value.get("val") is not None]
        if accession:
            accn_values = [value for value in values if value.get("accn") == accession]
            if accn_values:
                values = accn_values
        values = sorted(values, key=lambda value: (value.get("filed") or "", value.get("end") or ""), reverse=True)
        return float(values[0]["val"]) if values else None

    def _parse_html_filing(self, filing: dict[str, Any]) -> dict[str, float | str] | None:
        html = self.edgar.download_filing_html(filing)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        values: dict[str, float | str] = {}
        for table in soup.find_all("table"):
            table_text = table.get_text(" ", strip=True).lower()
            if not any(term in table_text for term in ["current assets", "total liabilities", "balance sheet"]):
                continue
            scale = self._detect_scale(table_text)
            for row in table.find_all("tr"):
                cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
                if len(cells) < 2:
                    continue
                label = self._clean_label(" ".join(cells[:-1]))
                nums = [self._parse_number(cell, scale) for cell in cells[1:]]
                nums = [num for num in nums if num is not None]
                if not nums:
                    continue
                value = nums[0]
                self._assign_html_value(values, label, value)
        text = soup.get_text(" ", strip=True)
        if "shares_outstanding" not in values:
            share_match = re.search(r"([0-9][0-9,\.]+)\s+shares\s+(?:of\s+)?(?:common\s+stock\s+)?(?:outstanding|issued and outstanding)", text, re.I)
            if share_match:
                values["shares_outstanding"] = self._parse_number(share_match.group(1), 1) or 0
        values["business_description"] = self._extract_item_text(text, "item 1", "item 1a", 900)
        values["risk_factors"] = self._extract_item_text(text, "item 1a", "item 2", 900)
        return values if values else None

    def _assign_html_value(self, values: dict[str, float | str], label: str, value: float) -> None:
        label_lower = label.lower()
        if "total current assets" in label_lower or label_lower.strip() == "current assets":
            values.setdefault("current_assets", value)
        elif "total liabilities" in label_lower and "current" not in label_lower and "stockholders" not in label_lower:
            values.setdefault("total_liabilities", value)
        elif "common stock" in label_lower and "outstanding" in label_lower and value > 0:
            values.setdefault("shares_outstanding", value)
        elif "cash and cash equivalents" in label_lower or label_lower == "cash":
            values.setdefault("cash", value)
        elif "accounts receivable" in label_lower or "receivables" in label_lower:
            values.setdefault("receivables", value)
        elif "inventor" in label_lower:
            values.setdefault("inventory", value)
        elif "total current liabilities" in label_lower:
            values.setdefault("current_liabilities", value)
        elif "long-term debt" in label_lower or "long term debt" in label_lower:
            values.setdefault("long_term_debt", value)
        elif label_lower in {"revenue", "revenues", "net sales", "sales"}:
            values.setdefault("revenue", value)

    def _populate_from_html(self, result: NCAVResult, values: dict[str, float | str]) -> None:
        for attr in [
            "current_assets",
            "total_liabilities",
            "shares_outstanding",
            "cash",
            "receivables",
            "inventory",
            "current_liabilities",
            "long_term_debt",
            "revenue",
            "business_description",
            "risk_factors",
        ]:
            value = values.get(attr)
            if value is not None and getattr(result, attr) in (None, "", []):
                setattr(result, attr, value)
        result.data_source = "HTML_FALLBACK" if result.data_source == "UNKNOWN" else f"{result.data_source}+HTML_FALLBACK"
        result.data_quality_flag = "HTML_FALLBACK" if self._has_required_ncav(result) else "MANUAL_REVIEW"

    def _finalize(self, result: NCAVResult) -> None:
        if not self._has_required_ncav(result):
            result.data_quality_flag = "MANUAL_REVIEW"
            return
        assert result.current_assets is not None
        assert result.total_liabilities is not None
        assert result.shares_outstanding is not None
        result.ncav = result.current_assets - result.total_liabilities
        if result.shares_outstanding > 0:
            result.ncav_per_share = result.ncav / result.shares_outstanding
        if result.current_price and result.ncav_per_share and result.ncav_per_share > 0:
            result.price_to_ncav = result.current_price / result.ncav_per_share
            result.ncav_discount_pct = (1 - result.price_to_ncav) * 100
        result.ncav_quality = self._quality(result)
        if result.data_quality_flag == "PENDING":
            result.data_quality_flag = "OK"

    def _quality(self, result: NCAVResult) -> str:
        if result.cash is not None and result.receivables is not None and result.total_liabilities is not None:
            if result.cash + result.receivables > result.total_liabilities:
                return "HIGH"
        if result.ncav is not None and result.total_liabilities is not None:
            margin = result.ncav / result.total_liabilities if result.total_liabilities else math.inf
            if margin < 0.10:
                return "LOW"
        return "MEDIUM" if result.current_assets and result.total_liabilities and result.current_assets > result.total_liabilities else "LOW"

    @staticmethod
    def _has_required_ncav(result: NCAVResult) -> bool:
        return bool(result.current_assets and result.total_liabilities is not None and result.shares_outstanding and result.shares_outstanding > 0)

    @staticmethod
    def _parse_number(text: str, scale: float = 1) -> float | None:
        clean = text.replace("$", "").replace(",", "").strip()
        if not clean or clean in {"-", "—", "–"}:
            return None
        negative = clean.startswith("(") and clean.endswith(")")
        clean = clean.strip("()")
        match = re.search(r"-?\d+(?:\.\d+)?", clean)
        if not match:
            return None
        value = float(match.group(0)) * scale
        return -value if negative else value

    @staticmethod
    def _detect_scale(text: str) -> float:
        if "in thousands" in text or "$ in thousands" in text or "amounts in thousands" in text:
            return 1_000
        if "in millions" in text or "$ in millions" in text or "amounts in millions" in text:
            return 1_000_000
        return 1

    @staticmethod
    def _clean_label(text: str) -> str:
        return re.sub(r"\s+", " ", text.replace("$", " ")).strip(" :.-")

    @staticmethod
    def _extract_item_text(text: str, start: str, end: str, max_chars: int) -> str | None:
        lower = text.lower()
        start_idx = lower.find(start)
        if start_idx < 0:
            return None
        end_idx = lower.find(end, start_idx + len(start))
        snippet = text[start_idx:end_idx if end_idx > start_idx else start_idx + max_chars]
        return re.sub(r"\s+", " ", snippet[:max_chars]).strip()

    @staticmethod
    def _is_stale(filing_date: str | None) -> bool:
        if not filing_date:
            return True
        try:
            filed = datetime.fromisoformat(filing_date).replace(tzinfo=timezone.utc)
            return filed < datetime.now(timezone.utc) - timedelta(days=STALE_FILING_DAYS)
        except ValueError:
            return True

    @staticmethod
    def _first_ticker(submissions: dict[str, Any] | None) -> str | None:
        tickers = (submissions or {}).get("tickers") or []
        return tickers[0] if tickers else None

    @staticmethod
    def _attach_company_price(result: NCAVResult, company: Company) -> None:
        result.current_price = company.current_price
        result.market_cap = company.market_cap
        result.avg_daily_volume = company.avg_daily_volume
        result.days_to_build_500k_position = company.days_to_build_500k_position

    def _write_cache(self, results: list[NCAVResult]) -> Path:
        date = datetime.now(timezone.utc).date().isoformat()
        path = CACHE_DIR / f"ncav_{date}.json"
        path.write_text(json.dumps([result.to_dict() for result in results], indent=2, sort_keys=True))
        return path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Calculate GRAHAM NCAV")
    parser.add_argument("ciks", nargs="+")
    args = parser.parse_args()
    calc = NCAVCalculator()
    for item in calc.batch_calculate(args.ciks):
        print(json.dumps(item.to_dict(), indent=2))
