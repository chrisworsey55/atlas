from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from terminal.settings import settings


JANUS_REASON = "production janus_daily.json missing - local file stale 2026-04-24"
SHANNON_REASON = "production SHANNON queue missing on Azure - deploy/run SHANNON ingestion before using F3 for trades"
SIMONS_REASON = "production SIMONS files missing on Azure - deploy/run SIMONS pattern engine before using F4 for trades"


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
        "data": json_safe(data if data is not None else {}),
    }
    payload.update(json_safe(extra))
    return payload


def json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        json.dumps(value, allow_nan=False)
        return value
    except TypeError:
        pass
    except ValueError:
        pass
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


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
    if not any(path.exists() for path in files):
        files = [
            settings.kalshi_root / "paper_trades" / "live" / "book_a_live.json",
            settings.kalshi_root / "paper_trades" / "live" / "book_b_live.json",
        ]
    data = {path.stem: read_json(path, {}) for path in files if path.exists()}
    if not data:
        return not_wired("Kalshi live position files missing", files[0])
    return response("OK", ", ".join(str(path) for path in files), data, stale=False)


def shannon_status() -> dict[str, Any]:
    queue = source_path("SHANNON", "queue", "candidates.parquet")
    log = source_path("SHANNON", "logs", "shannon.log")
    recs = source_path("data", "state", "recommendations_shannon.json")
    if not queue.exists():
        if log.exists():
            meta = stale_meta(log, 24 * 3600)
            message = "SHANNON ran recently but produced no candidates parquet" if not meta["stale"] else SHANNON_REASON
            return response("OK" if not meta["stale"] else "NOT_WIRED", log, {"message": message, "row_count": 0}, **meta)
        return not_wired(SHANNON_REASON, queue)
    meta = stale_meta(queue, 24 * 3600)
    meta["recommendations_mtime"] = mtime_iso(recs)
    meta["cron_found"] = False
    message = "SHANNON queue is current" if not meta["stale"] else "SHANNON queue is stale; no production cron found"
    return response("OK", queue, {"message": message}, **meta)


def shannon_queue() -> dict[str, Any]:
    path = source_path("SHANNON", "queue", "candidates.parquet")
    if not path.exists():
        log = source_path("SHANNON", "logs", "shannon.log")
        if log.exists() and not stale_meta(log, 24 * 3600)["stale"]:
            return response("OK", log, {"row_count": 0, "newest_as_of": None, "rows": []}, **stale_meta(log, 24 * 3600))
        return not_wired(SHANNON_REASON, path)
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
    if not rows:
        return not_wired(SHANNON_REASON, memos)
    return response("OK", memos, rows, stale=False)


def shannon_scouts() -> dict[str, Any]:
    base = source_path("SHANNON")
    if not base.exists():
        return not_wired(SHANNON_REASON, base)
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


def graham_screen() -> dict[str, Any]:
    graham_output = source_path("graham", "output")
    files = sorted(graham_output.glob("screener_*.json")) if graham_output.exists() else []
    if not files:
        return response("NOT_RUN", graham_output, {}, reason="No GRAHAM screener output exists")
    path = files[-1]
    payload = read_json(path, {})
    rows = payload.get("top_50") or payload.get("results") or []
    status = read_json(graham_output / "latest_status.json", {})
    date = payload.get("date") or status.get("last_run") or path.stem.replace("screener_", "")
    portfolio_path = status.get("portfolio_path") or f"graham/output/portfolio_candidates_{date}.md"
    return response(
        "OK",
        path,
        {
            "meta": {
                "date": date,
                "universe_count": status.get("universe_count"),
                "passing_count": payload.get("passing_count", len(rows)),
                "portfolio_path": portfolio_path,
            },
            "top_10": rows[:10],
        },
        **stale_meta(path, 8 * 86400),
    )


def simons_patterns() -> dict[str, Any]:
    path = source_path("simons", "simons_patterns.json")
    data = read_json(path, {})
    if not data:
        return not_wired(SIMONS_REASON, path)
    patterns = data.get("patterns") or data.get("confirmed_patterns") or []
    total = data.get("metadata", {}).get("total_confirmed") or data.get("total_confirmed") or len(patterns)
    return response("OK", path, {"pattern_count": total, "raw": data}, **stale_meta(path, 365 * 86400))


def simons_signals() -> dict[str, Any]:
    live_state = source_path("simons", "live_state.json")
    data = read_json(live_state, {})
    if data:
        return response("OK", live_state, data, **stale_meta(live_state, 36 * 3600))
    path = source_path("data", "simons")
    files = list(path.glob("*.json")) if path.exists() else []
    if not files:
        return not_wired("production SIMONS live_state.json missing on Azure", live_state)
    return response("OK", path, {"signal_file_count": len(files), "files": [file.name for file in files[-20:]]}, stale=False)


def simons_backtest() -> dict[str, Any]:
    path = source_path("simons", "simons_backtest_results.json")
    data = read_json(path, {})
    if not data:
        return not_wired(SIMONS_REASON, path)
    return response("OK", path, data, **stale_meta(path, 30 * 86400))


def backtest_darwin() -> dict[str, Any]:
    db = source_path("darwin_v3", "gene_pool.db")
    phase9 = source_path("darwin_v3", "phase9_daily.json")
    breeding = source_path("darwin_v3", "breeding_log.json")
    data = {
        "gene_pool_db_exists": db.exists(),
        "phase9_daily": read_json(phase9, {}),
        "breeding_log": read_json(breeding, {}),
        "postmortem_count": len(list(source_path("darwin_v3", "postmortems").glob("*.json")))
        if source_path("darwin_v3", "postmortems").exists()
        else 0,
    }
    if db.exists():
        try:
            conn = sqlite3.connect(db)
            data["tables"] = [row[0] for row in conn.execute("select name from sqlite_master where type='table'")]
            conn.close()
        except Exception as exc:
            data["sqlite_error"] = str(exc)
    if not db.exists() and not phase9.exists():
        return not_wired("Darwin v3 production gene pool/phase9 state missing", db)
    return response("OK", db if db.exists() else phase9, data, **stale_meta(phase9 if phase9.exists() else db, 36 * 3600))


def backtest_fitness() -> dict[str, Any]:
    paths = [
        source_path("darwin_v3", "phase9_daily.json"),
        source_path("data", "backtest", "results", "final_agent_weights.json"),
        source_path("darwin_v3", "breeding_log.json"),
    ]
    rows = [{"file": path.name, "mtime": mtime_iso(path), "data": read_json(path, {})} for path in paths if path.exists()]
    if not rows:
        return not_wired("Darwin/backtest fitness state missing", paths[0])
    newest_age = min((file_age_seconds(path) for path in paths if path.exists()), default=None)
    return response("OK", ", ".join(str(path) for path in paths if path.exists()), rows, stale=newest_age is None or newest_age > 36 * 3600, staleness_seconds=newest_age, threshold_seconds=36 * 3600)


def backtest_equity() -> dict[str, Any]:
    path = source_path("data", "backtest", "results", "summary.json")
    data = read_json(path, {})
    if not data:
        return not_wired("backtest summary.json missing or unreadable", path)
    return response("OK", path, data, **stale_meta(path, 30 * 86400))


def backtest_ablations() -> dict[str, Any]:
    path = source_path("data", "backtest", "results")
    files = list(path.glob("*ablation*.json")) if path.exists() else []
    if path.exists() and not files:
        return response(
            "OK",
            path,
            {"ablation_count": 0, "message": "no ablation result files found", "files": []},
            **stale_meta(path, 90 * 86400),
        )
    if not files:
        return not_wired("ablation outputs not found", path)
    return response(
        "OK",
        path,
        {"ablation_count": len(files), "files": [read_json(file, {}) for file in files]},
        stale=False,
    )


def janus_not_wired() -> dict[str, Any]:
    return not_wired(JANUS_REASON, source_path("data", "state", "janus_daily.json"))


def janus_regime() -> dict[str, Any]:
    path = source_path("data", "state", "janus_daily.json")
    data = read_json(path, {})
    if not data:
        return janus_not_wired()
    return response("OK", path, data, **stale_meta(path, 24 * 3600))


def janus_weights() -> dict[str, Any]:
    janus = janus_regime()
    if janus["status"] != "OK":
        return janus
    weights_path = source_path("data", "state", "agent_weights.json")
    weights = read_json(weights_path, {})
    data = {
        "janus": janus["data"],
        "agent_weights": weights,
    }
    return response("OK", f"{janus['source']}, {weights_path}", data, **stale_meta(weights_path, 14 * 3600))


def janus_reweighting() -> dict[str, Any]:
    history_path = source_path("data", "state", "janus_history.json")
    history = read_json(history_path, [])
    if not history:
        daily = janus_regime()
        if daily["status"] != "OK":
            return daily
        return response("OK", daily["source"], {"latest": daily["data"]}, stale=daily.get("stale"))
    latest = history[-1] if isinstance(history, list) else history
    return response("OK", history_path, {"latest": latest, "count": len(history) if isinstance(history, list) else None}, **stale_meta(history_path, 24 * 3600))


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
        ("portfolio.positions", source_path("data", "state", "positions.json"), 18 * 3600, True),
        ("portfolio.decisions", source_path("data", "state", "decisions.json"), 18 * 3600, True),
        ("agents.views", source_path("data", "state", "agent_views.json"), 18 * 3600, True),
        ("agents.weights", source_path("data", "state", "agent_weights.json"), 36 * 3600, True),
        ("shannon.run", source_path("SHANNON", "logs", "shannon.log"), 24 * 3600, True),
        ("simons.patterns", source_path("simons", "simons_patterns.json"), 365 * 86400, True),
        ("simons.live_state", source_path("simons", "live_state.json"), 36 * 3600, True),
        ("kalshi.summary", settings.kalshi_root / "paper_trades" / "combined_summary.json", 26 * 3600, True),
        ("tracker.state", source_path("state", "tracker_state.json"), 18 * 3600, True),
        ("backtest.summary", source_path("data", "backtest", "results", "summary.json"), 90 * 86400, False),
        ("darwin_v3.phase9", source_path("darwin_v3", "phase9_daily.json"), 36 * 3600, True),
    ]
    rows = []
    for name, path, threshold, critical in checks:
        meta = stale_meta(path, threshold)
        rows.append({"name": name, "status": "OK" if path.exists() else "MISSING", "source": str(path), "critical": critical, **meta})
    janus_path = source_path("data", "state", "janus_daily.json")
    if janus_path.exists():
        rows.append({"name": "janus.daily", "status": "OK", "source": str(janus_path), "critical": True, **stale_meta(janus_path, 24 * 3600)})
    else:
        rows.append({"name": "janus.daily", "status": "NOT_WIRED", "source": str(janus_path), "critical": True, "stale": True, "reason": JANUS_REASON})
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
    snapshot_crontab = settings.state_root / "crontab.txt"
    if settings.production or not snapshot_crontab.exists():
        crontab_text = os.popen("crontab -l 2>/dev/null").read()
        crontab_source = "crontab -l"
    else:
        crontab_text = snapshot_crontab.read_text(encoding="utf-8")
        crontab_source = str(snapshot_crontab)
    rows = []
    for name, schedule, command in expected:
        present = command in crontab_text or name.split("_")[0] in crontab_text
        rows.append({"name": name, "schedule": schedule, "command": command, "status": "PRESENT_UNVERIFIED" if present else "MISSING", "source": crontab_source})
    return rows
