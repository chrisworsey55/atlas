from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from graham.config import MEMO_OUTPUT_DIR, OUTPUT_DIR, ensure_dirs
from graham.models import NCAVResult


class GrahamOutputGenerator:
    def __init__(self):
        ensure_dirs()

    def generate(
        self,
        ranked: list[NCAVResult],
        universe_count: int,
        date: str | None = None,
        previous_ranked: list[NCAVResult] | None = None,
    ) -> dict[str, str]:
        date = date or datetime.now(timezone.utc).date().isoformat()
        screener_path = self.write_screener(ranked, date)
        portfolio_path = self.write_portfolio_candidates(ranked[:40], universe_count, date)
        summary_path = self.write_weekly_summary(ranked, universe_count, date, previous_ranked or [])
        return {"screener": str(screener_path), "portfolio": str(portfolio_path), "summary": str(summary_path)}

    def write_screener(self, ranked: list[NCAVResult], date: str) -> Path:
        path = OUTPUT_DIR / f"screener_{date}.json"
        payload = {
            "status": "OK",
            "date": date,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "passing_count": len(ranked),
            "top_50": [result.to_dict() for result in ranked[:50]],
            "results": [result.to_dict() for result in ranked],
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        return path

    def write_portfolio_candidates(self, candidates: list[NCAVResult], universe_count: int, date: str) -> Path:
        path = OUTPUT_DIR / f"portfolio_candidates_{date}.md"
        high_count = sum(1 for result in candidates if result.ncav_quality == "HIGH")
        lines = [
            f"GRAHAM NET-NET SCREEN — {date}",
            f"Universe: {universe_count} OTC filers scanned",
            f"Passed screen (<0.67x NCAV): {len(candidates)}",
            f"High quality (cash-heavy): {high_count}",
            "",
        ]
        for quality in ["HIGH", "MEDIUM", "LOW"]:
            rows = [result for result in candidates if result.ncav_quality == quality]
            lines.append(f"{quality} QUALITY CANDIDATES")
            lines.append("")
            lines.extend(self._table(rows))
            lines.append("")
        warnings = [result for result in candidates if (result.days_to_build_500k_position or 0) > 20]
        lines.append("LIQUIDITY WARNINGS")
        lines.append("The following candidates require >20 trading days to")
        lines.append("build a $500K position:")
        lines.append("")
        if warnings:
            lines.extend(f"- {r.ticker}: {r.days_to_build_500k_position} trading days" for r in warnings)
        else:
            lines.append("- None")
        path.write_text("\n".join(lines) + "\n")
        return path

    def write_weekly_summary(self, ranked: list[NCAVResult], universe_count: int, date: str, previous_ranked: list[NCAVResult]) -> Path:
        previous = {result.ticker for result in previous_ranked}
        current = {result.ticker for result in ranked}
        new = sorted(current - previous) if previous_ranked else []
        top_rows = "\n".join(
            f"{r.rank or i}. {r.ticker} {self._fmt_pct(r.ncav_discount_pct)}% discount {r.ncav_quality}"
            for i, r in enumerate(ranked[:5], start=1)
        )
        summary = f"""GRAHAM WEEKLY — {date}
Universe scanned: {universe_count}
Passed NCAV screen: {len(ranked)}
High quality: {sum(1 for result in ranked if result.ncav_quality == 'HIGH')}
New this week: {', '.join(new) if new else 'N/A'}
Top 5 by discount:
{top_rows}
"""
        path = OUTPUT_DIR / f"weekly_summary_{date}.txt"
        path.write_text(summary)
        latest = OUTPUT_DIR / "latest_status.json"
        latest.write_text(
            json.dumps(
                {
                    "status": "OK",
                    "last_run": date,
                    "universe_count": universe_count,
                    "passing_count": len(ranked),
                    "high_quality_count": sum(1 for result in ranked if result.ncav_quality == "HIGH"),
                    "screener_path": f"graham/output/screener_{date}.json",
                    "portfolio_path": f"graham/output/portfolio_candidates_{date}.md",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return path

    def _table(self, rows: list[NCAVResult]) -> list[str]:
        if not rows:
            return ["No candidates."]
        lines = [
            "| Rank | Ticker | Company | Price | NCAV/sh | Disc% | Vol($K) | Days |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in rows:
            lines.append(
                "| {rank} | {ticker} | {company} | {price} | {ncav} | {disc} | {vol} | {days} |".format(
                    rank=row.rank or "",
                    ticker=row.ticker,
                    company=(row.company_name or "")[:48],
                    price=self._money(row.current_price),
                    ncav=self._money(row.ncav_per_share),
                    disc=self._fmt_pct(row.ncav_discount_pct),
                    vol=self._money((row.avg_daily_volume or 0) / 1000),
                    days=row.days_to_build_500k_position or "",
                )
            )
        return lines

    @staticmethod
    def _money(value: float | None) -> str:
        return "N/A" if value is None else f"{value:,.2f}"

    @staticmethod
    def _fmt_pct(value: float | None) -> str:
        return "N/A" if value is None else f"{value:.1f}"

