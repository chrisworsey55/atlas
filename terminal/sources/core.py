from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from terminal.settings import settings


JANUS_REASON = "production janus_daily.json missing - local file stale 2026-04-24"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def file_age_seconds(path: Path) -> float | None:
    try:
        return datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    except OSError:
        return None


def source_path(*parts: str) -> Path:
    return settings.state_root.joinpath(*parts)


def response(status: str, source: Path | str | None, data: Any = None, **extra: Any) -> dict[str, Any]:
    payload = {
        "status": status,
        "as_of": now_iso(),
        "source": str(source) if source else None,
        "data": data if data is not None else {},
    }
    payload.update(extra)
    return payload


def not_wired(reason: str, source: Path | str | None = None) -> dict[str, Any]:
    return response("NOT_WIRED", source, {}, reason=reason)


def stale_meta(path: Path, threshold_seconds: int) -> dict[str, Any]:
    age = file_age_seconds(path)
    return {
        "file_mtime": mtime_iso(path),
        "staleness_seconds": age,
        "threshold_seconds": threshold_seconds,
        "stale": age is None or age > threshold_seconds,
    }


def portfolio_summary() -> dict[str, Any]:
    path = source_path("data", "state", "positions.json")
    data = read_json(path, {})
    if not data:
        return not_wired("positions.json missing or unreadable", path)
    positions = data.get("positions", []) if isinstance(data, dict) else []
    portfolio_value = float(data.get("portfolio_value") or data.get("total_value") or 0)
    cash = float(data.get("cash_balance") or data.get("cash") or 0)
    exposure = max(portfolio_value - cash, 0)
    pnl = portfolio_value - float(data.get("starting_value") or 1000000)
    cash_pct = (cash / portfolio_value * 100) if portfolio_value else 0
    out = {
        "portfolio_value": portfolio_value,
        "cash": cash,
        "cash_pct": cash_pct,
        "exposure": exposure,
        "positions_count": len(positions),
        "pnl": pnl,
        "last_updated": data.get("last_updated") or data.get("timestamp"),
    }
    return response("OK", path, out, **stale_meta(path, 14 * 3600))


def portfolio_positions() -> dict[str, Any]:
    path = source_path("data", "state", "positions.json")
    data = read_json(path, {})
    if not data:
        return not_wired("positions.json missing or unreadable", path)
    return response("OK", path, data.get("positions", []), **stale_meta(path, 14 * 3600))


def portfolio_pnl() -> dict[str, Any]:
    path = source_path("data", "state", "pnl_history.json")
    data = read_json(path, [])
    if data is None:
        return not_wired("pnl_history.json missing or unreadable", path)
    return response("OK", path, data[-60:] if isinstance(data, list) else data, **stale_meta(path, 24 * 3600))


def portfolio_decisions() -> dict[str, Any]:
    path = source_path("data", "state", "decisions.json")
    data = read_json(path, [])
    if data is None:
        return not_wired("decisions.json missing or unreadable", path)
    rows = data[-40:] if isinstance(data, list) else data
    return response("OK", path, rows, **stale_meta(path, 14 * 3600))


def portfolio_risk() -> dict[str, Any]:
    summary = portfolio_summary()
    if summary["status"] != "OK":
        return summary
    data = summary["data"]
    total = data.get("portfolio_value") or 0
    positions = portfolio_positions().get("data", [])
    weights = []
    for pos in positions if isinstance(positions, list) else []:
        value = pos.get("market_value") or pos.get("planned_value") or pos.get("value") or 0
        if not value:
            shares = pos.get("shares") or pos.get("quantity") or 0
            price = pos.get("current_price") or pos.get("price") or pos.get("entry_price") or 0
            value = shares * price
        if total:
            weights.append(float(value) / total)
    risk = {
        "gross_exposure_pct": (data.get("exposure", 0) / total * 100) if total else 0,
        "cash_pct": data.get("cash_pct", 0),
        "top_weight_pct": max(weights) * 100 if weights else 0,
        "position_count": len(weights),
    }
    return response("OK", summary["source"], risk, stale=summary.get("stale"), staleness_seconds=summary.get("staleness_seconds"))


def agents_overview() -> dict[str, Any]:
    views_path = source_path("data", "state", "agent_views.json")
    weights_path = source_path("data", "state", "agent_weights.json")
    score_path = source_path("data", "state", "agent_scorecards.json")
    views = read_json(views_path, {})
    weights = read_json(weights_path, {})
    scorecards = read_json(score_path, {})
    names = sorted(set(_agent_keys(views)) | set(_agent_keys(weights)) | set(_agent_keys(scorecards)))
    rows = []
    for name in names:
        score = _lookup_agent(scorecards, name)
        view = _lookup_agent(views, name)
        rows.append(
            {
                "name": name,
                "weight": _lookup_agent(weights, name),
                "conviction": _field(view, ["conviction", "confidence", "score"]),
                "rolling_sharpe": _field(score, ["rolling_sharpe", "sharpe", "sharpe_ratio"]),
                "last_view": _field(view, ["view", "recommendation", "stance", "summary"]),
            }
        )
    meta = stale_meta(views_path, 2 * 3600)
    return response("OK", views_path, {"agent_count": len(rows), "agents": rows}, **meta)


def _agent_keys(data: Any) -> list[str]:
    if isinstance(data, dict):
        for key in ("agents", "views", "weights", "scorecards", "metrics"):
            if isinstance(data.get(key), dict):
                return list(data[key].keys())
            if isinstance(data.get(key), list):
                return [str(item.get("agent") or item.get("name")) for item in data[key] if isinstance(item, dict)]
        return [key for key, value in data.items() if isinstance(value, (dict, int, float, str))]
    if isinstance(data, list):
        return [str(item.get("agent") or item.get("name")) for item in data if isinstance(item, dict)]
    return []


def _lookup_agent(data: Any, name: str) -> Any:
    if isinstance(data, dict):
        if name in data:
            return data[name]
        for key in ("agents", "views", "weights", "scorecards", "metrics"):
            nested = data.get(key)
            if isinstance(nested, dict) and name in nested:
                return nested[name]
            if isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict) and (item.get("agent") == name or item.get("name") == name):
                        return item
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and (item.get("agent") == name or item.get("name") == name):
                return item
    return None


def _field(value: Any, keys: list[str]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                return value[key]
    return value if isinstance(value, (int, float, str)) else None


def agents_execution_log() -> dict[str, Any]:
    path = source_path("data", "state", "execution_log.json")
    data = read_json(path, [])
    if data is None:
        return not_wired("execution_log.json missing or unreadable", path)
    return response("OK", path, data[-30:] if isinstance(data, list) else data, **stale_meta(path, 2 * 3600))


def agents_prompts() -> dict[str, Any]:
    path = source_path("agents", "prompts")
    prompts = []
    if path.exists():
        for file in sorted(path.glob("*.py"))[:80]:
            prompts.append({"name": file.stem, "mtime": mtime_iso(file)})
    return response("OK", path, {"prompt_files": prompts, "count": len(prompts)}, stale=False)


def kalshi_summary() -> dict[str, Any]:
    candidates = [
        settings.kalshi_root / "paper_trades" / "combined_summary.json",
        settings.kalshi_root / "combined_summary.json",
        settings.repo_root / "simons" / "kalshi_state.json",
    ]
    path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    data = read_json(path, {})
    if not data:
        return not_wired("Kalshi summary file missing or unreadable", path)
    return response("OK", path, data, **stale_meta(path, 26 * 3600))


def kalshi_trades() -> dict[str, Any]:
    files = [
        settings.kalshi_root / "paper_trades" / "book_a_history.json",
        settings.kalshi_root / "paper_trades" / "book_b_history.json",
        settings.repo_root / "predict" / "paper_trades" / "trade_history.json",
    ]
    rows = []
    sources = []
    for path in files:
        data = read_json(path, [])
        if data:
            sources.append(str(path))
            rows.extend(data if isinstance(data, list) else data.get("trades", []))
    if not rows:
        return not_wired("Kalshi trade history missing or unreadable", files[0])
    return response("OK", ", ".join(sources), rows[-40:], stale=False)


def kalshi_positions() -> dict[str, Any]:
    files = [settings.kalshi_root / "live" / "book_a_live.json", settings.kalshi_root / "live" / "book_b_live.json"]
    data = {path.stem: read_json(path, {}) for path in files if path.exists()}
    if not data:
        return not_wired("Kalshi live position files missing", files[0])
    return response("OK", ", ".join(str(path) for path in files), data, stale=False)


def shannon_status() -> dict[str, Any]:
    queue = source_path("SHANNON", "queue", "candidates.parquet")
    recs = source_path("data", "state", "recommendations_shannon.json")
    meta = stale_meta(queue, 24 * 3600)
    meta["recommendations_mtime"] = mtime_iso(recs)
    meta["cron_found"] = False
    return response("OK" if queue.exists() else "NOT_WIRED", queue, {"message": "SHANNON queue is stale; no production cron found"}, **meta)


def shannon_queue() -> dict[str, Any]:
    path = source_path("SHANNON", "queue", "candidates.parquet")
    if not path.exists():
        return not_wired("SHANNON candidates.parquet missing", path)
    try:
        import pandas as pd

        frame = pd.read_parquet(path)
        rows = frame.tail(20).to_dict(orient="records")
        newest = str(frame["as_of"].max()) if "as_of" in frame.columns and not frame.empty else None
        data = {"row_count": len(frame), "newest_as_of": newest, "rows": rows}
    except Exception as exc:
        return response("ERROR", path, {}, reason=f"{type(exc).__name__}: {exc}", **stale_meta(path, 24 * 3600))
    return response("OK", path, data, **stale_meta(path, 24 * 3600))


def shannon_items() -> dict[str, Any]:
    memos = source_path("SHANNON", "memos")
    rows = [{"file": file.name, "mtime": mtime_iso(file)} for file in sorted(memos.glob("*.md"))[-20:]] if memos.exists() else []
    return response("OK", memos, rows, stale=not bool(rows))


def shannon_scouts() -> dict[str, Any]:
    base = source_path("SHANNON")
    data = {
        "memos": len(list((base / "memos").glob("*.md"))) if (base / "memos").exists() else 0,
        "filings_cache": len(list((base / "cache" / "filings").glob("*"))) if (base / "cache" / "filings").exists() else 0,
        "news_cache": len(list((base / "cache" / "news").glob("*"))) if (base / "cache" / "news").exists() else 0,
        "transcript_cache": len(list((base / "cache" / "transcripts").glob("*"))) if (base / "cache" / "transcripts").exists() else 0,
    }
    return response("OK", base, data, stale=False)


def intel_tracker() -> dict[str, Any]:
    path = source_path("state", "tracker_state.json")
    if not path.exists():
        path = source_path("tracker_state.json")
    data = read_json(path, {})
    if not data:
        return not_wired("tracker state file missing or unreadable", path)
    return response("OK", path, data, **stale_meta(path, 2 * 3600))


def intel_deadline() -> dict[str, Any]:
    deadline = datetime(2026, 5, 15, 23, 59, tzinfo=timezone.utc)
    remaining = deadline - datetime.now(timezone.utc)
    return response("OK", "tracker/config.py", {"deadline": deadline.isoformat(), "days_remaining": remaining.days}, stale=False)


def intel_entities() -> dict[str, Any]:
    return response(
        "OK",
        "tracker/config.py",
        {
            "funds": ["Altimeter", "Coatue", "Tiger Global", "Duquesne"],
            "politicians": ["Pelosi", "Khanna"],
        },
        stale=False,
    )


def intel_news() -> dict[str, Any]:
    path = source_path("data", "state", "news_briefs.json")
    data = read_json(path, {})
    if not data:
        return not_wired("news/geopolitical agent output not found", path)
    return response("OK", path, data, **stale_meta(path, 24 * 3600))


def simons_patterns() -> dict[str, Any]:
    path = source_path("simons", "simons_patterns.json")
    data = read_json(path, {})
    if not data:
        return not_wired("simons_patterns.json missing or unreadable", path)
    patterns = data.get("patterns") or data.get("confirmed_patterns") or []
    total = data.get("metadata", {}).get("total_confirmed") or data.get("total_confirmed") or len(patterns)
    return response("OK", path, {"pattern_count": total, "raw": data}, **stale_meta(path, 7 * 86400))


def simons_signals() -> dict[str, Any]:
    path = source_path("data", "simons")
    files = list(path.glob("*.json")) if path.exists() else []
    return response("OK", path, {"signal_file_count": len(files), "files": [file.name for file in files[-20:]]}, stale=False)


def simons_backtest() -> dict[str, Any]:
    path = source_path("simons", "simons_backtest_results.json")
    data = read_json(path, {})
    if not data:
        return not_wired("simons_backtest_results.json missing or unreadable", path)
    return response("OK", path, data, **stale_meta(path, 30 * 86400))


def backtest_darwin() -> dict[str, Any]:
    db = source_path("darwin_v2", "lineage", "lineage.sqlite")
    data = {"sqlite_exists": db.exists(), "prompt_count": 0, "scorecards": []}
    prompt_dir = source_path("darwin_v2", "lineage", "prompts")
    score_dir = source_path("darwin_v2", "lineage", "scorecards")
    if prompt_dir.exists():
        data["prompt_count"] = len(list(prompt_dir.glob("*.json")))
    if score_dir.exists():
        data["scorecards"] = [file.name for file in sorted(score_dir.glob("*.json"))[-20:]]
    if db.exists():
        try:
            conn = sqlite3.connect(db)
            data["tables"] = [row[0] for row in conn.execute("select name from sqlite_master where type='table'")]
            conn.close()
        except Exception as exc:
            data["sqlite_error"] = str(exc)
    return response("OK" if db.exists() or data["scorecards"] else "NOT_WIRED", db, data, **stale_meta(db, 7 * 86400))


def backtest_fitness() -> dict[str, Any]:
    path = source_path("darwin_v2", "lineage", "scorecards")
    rows = []
    if path.exists():
        for file in sorted(path.glob("*.json"))[-10:]:
            rows.append({"file": file.name, "mtime": mtime_iso(file), "data": read_json(file, {})})
    return response("OK" if rows else "NOT_WIRED", path, rows, stale=not bool(rows))


def backtest_equity() -> dict[str, Any]:
    path = source_path("data", "backtest", "results", "summary.json")
    data = read_json(path, {})
    if not data:
        return not_wired("backtest summary.json missing or unreadable", path)
    return response("OK", path, data, **stale_meta(path, 30 * 86400))


def backtest_ablations() -> dict[str, Any]:
    path = source_path("data", "backtest", "results")
    files = list(path.glob("*ablation*.json")) if path.exists() else []
    if not files:
        return not_wired("ablation outputs not found", path)
    return response("OK", path, [read_json(file, {}) for file in files], stale=False)


def janus_not_wired() -> dict[str, Any]:
    return not_wired(JANUS_REASON, source_path("data", "state", "janus_daily.json"))


def snapshot_age() -> dict[str, Any] | None:
    if settings.production:
        return None
    manifest = settings.repo_root / "terminal" / "dev_state" / "azure_snapshot" / "snapshot_manifest.json"
    data = read_json(manifest, {})
    if not data:
        return {"status": "NO_SNAPSHOT", "label": "SNAPSHOT: NONE"}
    created = data.get("created_at")
    try:
        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - created_dt
        return {"status": "OK", "created_at": created, "age_seconds": age.total_seconds(), "label": f"SNAPSHOT: {int(age.total_seconds() // 3600)}H"}
    except Exception:
        return {"status": "UNKNOWN", "created_at": created, "label": "SNAPSHOT: UNKNOWN"}


def health_sources() -> list[dict[str, Any]]:
    checks = [
        ("portfolio.positions", source_path("data", "state", "positions.json"), 14 * 3600),
        ("portfolio.decisions", source_path("data", "state", "decisions.json"), 14 * 3600),
        ("agents.views", source_path("data", "state", "agent_views.json"), 2 * 3600),
        ("agents.weights", source_path("data", "state", "agent_weights.json"), 14 * 3600),
        ("shannon.queue", source_path("SHANNON", "queue", "candidates.parquet"), 24 * 3600),
        ("simons.patterns", source_path("simons", "simons_patterns.json"), 7 * 86400),
        ("kalshi.summary", settings.kalshi_root / "paper_trades" / "combined_summary.json", 26 * 3600),
        ("tracker.state", source_path("state", "tracker_state.json"), 2 * 3600),
        ("backtest.summary", source_path("data", "backtest", "results", "summary.json"), 30 * 86400),
    ]
    rows = []
    for name, path, threshold in checks:
        meta = stale_meta(path, threshold)
        rows.append({"name": name, "status": "OK" if path.exists() else "MISSING", "source": str(path), **meta})
    rows.append({"name": "janus.daily", "status": "NOT_WIRED", "source": str(source_path("data", "state", "janus_daily.json")), "stale": True, "reason": JANUS_REASON})
    return rows


def cron_status() -> list[dict[str, Any]]:
    expected = [
        ("autonomous_loop_noon", "0 12 * * 1-5", "python3 -m agents.autonomous_loop --once"),
        ("darwinian_loop_noon", "5 12 * * 1-5", "python3 -m agents.darwinian_loop --once"),
        ("briefing_noon", "15 12 * * 1-5", "email briefing"),
        ("briefing_deliver_noon", "20 12 * * 1-5", "email briefing deliver"),
        ("autonomous_loop_close", "0 20 * * 1-5", "python3 -m agents.autonomous_loop --once"),
        ("darwinian_loop_close", "5 20 * * 1-5", "python3 -m agents.darwinian_loop --once"),
        ("briefing_close", "15 20 * * 1-5", "email briefing"),
        ("briefing_deliver_close", "20 20 * * 1-5", "email briefing deliver"),
        ("weekly_briefing", "weekly sunday", "weekly briefing"),
        ("kalshi_integrity", "55 21 * * *", "integrity"),
        ("kalshi_trading", "0 22 * * *", "trading"),
        ("kalshi_backup", "30 22 * * *", "backup"),
        ("kalshi_clear_flag", "5 23 * * *", "clear flag"),
        ("kalshi_contract_scan", "0 9 * * *", "contract scan"),
    ]
    crontab_text = os.popen("crontab -l 2>/dev/null").read()
    rows = []
    for name, schedule, command in expected:
        present = command in crontab_text or name.split("_")[0] in crontab_text
        rows.append({"name": name, "schedule": schedule, "command": command, "status": "PRESENT_UNVERIFIED" if present else "MISSING", "source": "crontab -l"})
    return rows

