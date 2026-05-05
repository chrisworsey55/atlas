from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from graham.config import CACHE_DIR, EXCLUDED_SIC_CODES, MIN_AVG_DAILY_VOLUME_DOLLARS, SHELL_REVIEW_SIC_CODES, ensure_dirs
from graham.edgar import GrahamEdgarClient
from graham.models import Company
from graham.price import PriceClient


class GrahamUniverse:
    def __init__(self, edgar: GrahamEdgarClient | None = None, price_client: PriceClient | None = None):
        ensure_dirs()
        self.edgar = edgar or GrahamEdgarClient()
        self.price_client = price_client or PriceClient()

    def build(self) -> list[Company]:
        companies = self._seed_otc_companies()
        companies = self.filter_active(companies)
        companies = self.filter_shells(companies)
        companies = self.filter_liquidity(companies)
        self._write_cache(companies)
        return companies

    def refresh(self) -> list[Company]:
        return self.build()

    def get_cached(self) -> list[Company]:
        files = sorted(CACHE_DIR.glob("universe_*.json"))
        if not files:
            return []
        return [Company.from_dict(row) for row in json.loads(files[-1].read_text())]

    def filter_active(self, companies: Iterable[Company]) -> list[Company]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=548)).date().isoformat()
        active: list[Company] = []
        for company in companies:
            submissions = self.edgar.get_submissions_by_cik(company.cik)
            if not submissions:
                company.data_quality_flags.append("NO_SUBMISSIONS")
                continue
            company.sic_code = str(submissions.get("sic") or "") or company.sic_code
            company.sic_description = submissions.get("sicDescription") or company.sic_description
            latest = self.edgar.latest_10k_10q_by_filing_date(company.cik)
            if not latest:
                company.data_quality_flags.append("NO_10K_10Q")
                continue
            company.last_filing_date = latest.get("filing_date")
            company.last_filing_type = latest.get("form_type")
            company.last_accession = latest.get("accession_number")
            company.filing_url = latest.get("filing_url")
            if company.last_filing_date and company.last_filing_date >= cutoff:
                active.append(company)
        return active

    def filter_shells(self, companies: Iterable[Company]) -> list[Company]:
        filtered: list[Company] = []
        for company in companies:
            sic = str(company.sic_code or "")
            if sic in EXCLUDED_SIC_CODES:
                company.data_quality_flags.append("EXCLUDED_BLANK_CHECK")
                continue
            if sic in SHELL_REVIEW_SIC_CODES:
                company.data_quality_flags.append("SHELL_REVIEW_SIC")
            filtered.append(company)
        return filtered

    def filter_liquidity(self, companies: Iterable[Company]) -> list[Company]:
        filtered: list[Company] = []
        by_cik: dict[str, list[Company]] = defaultdict(list)
        for company in companies:
            by_cik[company.cik].append(company)
        for cik, rows in by_cik.items():
            best: Company | None = None
            for company in rows:
                price = self.price_client.get_price(company.ticker)
                company.current_price = price.current_price
                company.avg_daily_volume = price.avg_daily_volume
                company.avg_daily_volume_shares = price.avg_daily_volume_shares
                company.market_cap = price.market_cap
                company.days_to_build_500k_position = price.days_to_build_500k_position
                if price.data_quality != "OK":
                    company.data_quality_flags.append(price.data_quality)
                if best is None or (company.avg_daily_volume or 0) > (best.avg_daily_volume or 0):
                    best = company
            if not best:
                continue
            best.alternate_tickers = sorted({row.ticker for row in rows if row.ticker != best.ticker})
            if best.avg_daily_volume and best.avg_daily_volume >= MIN_AVG_DAILY_VOLUME_DOLLARS:
                filtered.append(best)
        return filtered

    def _seed_otc_companies(self) -> list[Company]:
        payload = self.edgar.get_company_tickers_exchange()
        fields = payload.get("fields", [])
        rows = payload.get("data", [])
        idx = {field: i for i, field in enumerate(fields)}
        companies: list[Company] = []
        for row in rows:
            if row[idx["exchange"]] != "OTC":
                continue
            companies.append(
                Company(
                    ticker=str(row[idx["ticker"]]).upper(),
                    cik=GrahamEdgarClient.normalize_cik(row[idx["cik"]]),
                    company_name=str(row[idx["name"]]),
                    exchange="OTC",
                    raw={"sec_row": row},
                )
            )
        return companies

    def _write_cache(self, companies: list[Company]) -> Path:
        date = datetime.now(timezone.utc).date().isoformat()
        path = CACHE_DIR / f"universe_{date}.json"
        path.write_text(json.dumps([company.to_dict() for company in companies], indent=2, sort_keys=True))
        return path


if __name__ == "__main__":
    universe = GrahamUniverse()
    built = universe.build()
    print(f"GRAHAM universe: {len(built)} liquid active OTC filers")
