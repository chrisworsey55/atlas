from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from config.settings import EDGAR_BASE_URL
from data.edgar_client import EdgarClient
from data.edgar_realtime_client import EDGARRealtimeClient
from graham.config import CACHE_DIR, ensure_dirs


class GrahamEdgarClient(EdgarClient):
    """GRAHAM-specific SEC helpers built on ATLAS EdgarClient."""

    COMPANY_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

    def __init__(self):
        ensure_dirs()
        super().__init__()
        self.realtime = EDGARRealtimeClient()

    @staticmethod
    def normalize_cik(cik: str | int) -> str:
        return str(cik).lstrip("0").zfill(10)

    def _cached_json(self, path: Path, max_age_seconds: int | None = None) -> dict[str, Any] | None:
        if not path.exists():
            return None
        if max_age_seconds is not None and time.time() - path.stat().st_mtime > max_age_seconds:
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True))

    def get_company_tickers_exchange(self, max_age_seconds: int = 7 * 86400) -> dict[str, Any]:
        path = CACHE_DIR / "company_tickers_exchange.json"
        cached = self._cached_json(path, max_age_seconds)
        if cached:
            return cached
        data = self._get(self.COMPANY_TICKERS_EXCHANGE_URL) or {}
        if data:
            self._write_json(path, data)
        return data

    def get_submissions_by_cik(self, cik: str | int, max_age_seconds: int = 7 * 86400) -> dict[str, Any] | None:
        cik_norm = self.normalize_cik(cik)
        path = CACHE_DIR / "submissions" / f"{cik_norm}.json"
        cached = self._cached_json(path, max_age_seconds)
        if cached:
            return cached
        data = self._get(f"{EDGAR_BASE_URL}/submissions/CIK{cik_norm}.json")
        if data:
            self._write_json(path, data)
        return data

    def get_company_facts_by_cik(self, cik: str | int, max_age_seconds: int = 30 * 86400) -> dict[str, Any] | None:
        cik_norm = self.normalize_cik(cik)
        path = CACHE_DIR / "companyfacts" / f"{cik_norm}.json"
        cached = self._cached_json(path, max_age_seconds)
        if cached:
            return cached
        data = self._get(f"{EDGAR_BASE_URL}/api/xbrl/companyfacts/CIK{cik_norm}.json")
        if data:
            self._write_json(path, data)
        return data

    def recent_filings_from_submissions(self, submissions: dict[str, Any], forms: set[str] | None = None) -> list[dict[str, Any]]:
        forms = forms or {"10-K", "10-Q"}
        cik = self.normalize_cik(submissions.get("cik", ""))
        recent = submissions.get("filings", {}).get("recent", {})
        rows: list[dict[str, Any]] = []
        for i, accession in enumerate(recent.get("accessionNumber", [])):
            form = self._nth(recent, "form", i)
            if form not in forms:
                continue
            primary_doc = self._nth(recent, "primaryDocument", i) or ""
            accession_clean = accession.replace("-", "")
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession_clean}/{primary_doc}"
            rows.append(
                {
                    "cik": cik,
                    "accession_number": accession,
                    "accession_clean": accession_clean,
                    "filing_date": self._nth(recent, "filingDate", i),
                    "report_date": self._nth(recent, "reportDate", i),
                    "form_type": form,
                    "primary_document": primary_doc,
                    "description": self._nth(recent, "primaryDocDescription", i),
                    "filing_url": filing_url,
                }
            )
        return sorted(rows, key=lambda row: row.get("filing_date") or "", reverse=True)

    @staticmethod
    def _nth(data: dict[str, list[Any]], key: str, index: int) -> Any:
        values = data.get(key, [])
        return values[index] if index < len(values) else None

    def latest_10k_10q_by_filing_date(self, cik: str | int) -> dict[str, Any] | None:
        submissions = self.get_submissions_by_cik(cik)
        if not submissions:
            return None
        filings = self.recent_filings_from_submissions(submissions)
        return filings[0] if filings else None

    def fact_for_accession(
        self,
        companyfacts: dict[str, Any] | None,
        tag: str,
        accession: str | None,
        unit: str = "USD",
        forms: set[str] | None = None,
    ) -> float | None:
        if not companyfacts:
            return None
        forms = forms or {"10-K", "10-Q"}
        units = companyfacts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {})
        values = units.get(unit) or units.get("shares") or []
        candidates = [v for v in values if v.get("form") in forms]
        if accession:
            accn_matches = [v for v in candidates if v.get("accn") == accession]
            if accn_matches:
                candidates = accn_matches
        candidates = sorted(candidates, key=lambda v: (v.get("filed") or "", v.get("end") or ""), reverse=True)
        for value in candidates:
            if value.get("val") is not None:
                return float(value["val"])
        return None

    def annual_fact_history(self, companyfacts: dict[str, Any] | None, tag: str, unit: str = "USD", limit: int = 3) -> list[float]:
        if not companyfacts:
            return []
        values = companyfacts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get(unit, [])
        annual = [v for v in values if v.get("form") == "10-K" and v.get("val") is not None]
        annual = sorted(annual, key=lambda v: (v.get("filed") or "", v.get("end") or ""), reverse=True)
        return [float(v["val"]) for v in annual[:limit]]

    def download_filing_html(self, filing: dict[str, Any]) -> str | None:
        url = filing.get("filing_url")
        if not url:
            return None
        cik = filing.get("cik", "").lstrip("0")
        accession = filing.get("accession_clean") or filing.get("accession_number", "").replace("-", "")
        path = CACHE_DIR / "filings" / f"{cik}_{accession}.html"
        if path.exists():
            return path.read_text(errors="ignore")
        html = self._get_text(url)
        if not html:
            html = self._discover_and_download_primary_doc(filing)
        if html:
            path.write_text(html)
        return html

    def _discover_and_download_primary_doc(self, filing: dict[str, Any]) -> str | None:
        cik = str(filing.get("cik", "")).lstrip("0")
        accession = filing.get("accession_number", "")
        accession_clean = filing.get("accession_clean") or accession.replace("-", "")
        index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{accession}-index.htm"
        index_html = self._get_text(index_url)
        if not index_html:
            return None
        soup = BeautifulSoup(index_html, "html.parser")
        candidates: list[str] = []
        base_path = f"/Archives/edgar/data/{cik}/{accession_clean}"
        for link in soup.find_all("a"):
            href = link.get("href", "")
            if not href:
                continue
            if "/ix?doc=" in href:
                match = re.search(r"/ix\?doc=([^&]+)", href)
                if match:
                    candidates.insert(0, match.group(1))
            elif href.lower().endswith((".htm", ".html")) and "index" not in href.lower():
                candidates.append(href)
        for href in candidates:
            if href.startswith("http"):
                url = href
            elif href.startswith("/"):
                url = f"https://www.sec.gov{href}"
            else:
                url = f"https://www.sec.gov{base_path}/{href}"
            html = self._get_text(url)
            if html and ("balance" in html.lower() or "assets" in html.lower()):
                return html
        return None

