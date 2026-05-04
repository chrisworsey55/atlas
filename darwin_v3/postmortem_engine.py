"""Post-mortem engine for Darwin v3."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Callable, Iterable

from .config import REPO_ROOT


@dataclass(frozen=True)
class TradeRecord:
    date: str
    ticker: str
    action: str
    shares: int
    price: float
    agent: str
    thesis: str
    status: str
    close_price: float | None = None
    pnl: float | None = None

    @property
    def is_closed_loss(self) -> bool:
        if self.status.upper() != "CLOSED":
            return False
        if self.pnl is not None:
            return self.pnl < 0
        if self.close_price is not None:
            signed = self.close_price - self.price
            if self.action.upper() in {"SELL", "SHORT"}:
                signed = self.price - self.close_price
            return signed < 0
        return False

    @property
    def pnl_pct(self) -> float | None:
        if self.pnl is not None:
            notional = self.price * self.shares
            return (self.pnl / notional) * 100 if notional else None
        if self.close_price is None:
            return None
        if self.action.upper() in {"SELL", "SHORT"}:
            return ((self.price - self.close_price) / self.price) * 100 if self.price else None
        return ((self.close_price - self.price) / self.price) * 100 if self.price else None


@dataclass(frozen=True)
class PostMortemResult:
    path: Path
    payload: dict
    cached: bool


class PostMortemEngine:
    """Detects triggers and writes structured post-mortems."""

    def __init__(
        self,
        repo_root: Path | None = None,
        output_dir: Path | None = None,
        cache_dir: Path | None = None,
        llm_runner: Callable[[str], dict] | None = None,
        simulation_date: date | None = None,
    ) -> None:
        self.repo_root = repo_root or REPO_ROOT
        self.output_dir = output_dir or (self.repo_root / "darwin_v3" / "postmortems")
        self.cache_dir = cache_dir or (self.output_dir / "cache")
        self.simulation_date = simulation_date or datetime.now(tz=UTC).date()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._llm_runner = llm_runner or self._default_llm_runner

    def load_trades(
        self,
        trade_sources: Iterable[Path] | None = None,
        simulation_date: date | None = None,
    ) -> list[TradeRecord]:
        sources = list(trade_sources or self._default_trade_sources())
        cutoff = simulation_date or self.simulation_date
        trades: list[TradeRecord] = []
        for source in sources:
            if source.suffix == ".json" and source.exists():
                data = json.loads(source.read_text())
                for item in data:
                    if isinstance(item, dict) and item.get("status"):
                        trade = self._trade_from_dict(item)
                        if trade.date <= cutoff.isoformat():
                            trades.append(trade)
        return trades

    def find_triggers(
        self,
        trades: Iterable[TradeRecord],
        simulation_date: date | None = None,
    ) -> list[tuple[str, TradeRecord]]:
        triggered: list[tuple[str, TradeRecord]] = []
        cutoff = simulation_date or self.simulation_date
        for trade in trades:
            if trade.date > cutoff.isoformat():
                continue
            for trigger in self._trade_triggers(trade):
                triggered.append((trigger, trade))
        return triggered

    def generate_postmortem(
        self,
        trade: TradeRecord,
        regime: str = "unknown",
        vix: float | None = None,
        simulation_date: date | None = None,
    ) -> PostMortemResult:
        trigger = self._primary_trigger(trade)
        prompt = self._build_prompt(trade, trigger, regime=regime, vix=vix)
        cache_key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        if cache_path.exists():
            payload = json.loads(cache_path.read_text())
            cached = True
        else:
            payload = self._llm_runner(prompt)
            cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
            cached = False
        result = self._normalize_payload(trade, trigger, payload, regime)
        out_path = self.output_dir / f"{trade.agent}_{trade.date}_{trigger}.json"
        out_path.write_text(json.dumps(result, indent=2, sort_keys=True))
        return PostMortemResult(path=out_path, payload=result, cached=cached)

    def run_from_default_sources(
        self,
        regime: str = "unknown",
        vix: float | None = None,
        simulation_date: date | None = None,
    ) -> list[PostMortemResult]:
        results: list[PostMortemResult] = []
        cutoff = simulation_date or self.simulation_date
        for trigger, trade in self.find_triggers(self.load_trades(simulation_date=cutoff), simulation_date=cutoff):
            if trade.is_closed_loss:
                results.append(self.generate_postmortem(trade, regime=regime, vix=vix, simulation_date=cutoff))
        return results

    def _trade_from_dict(self, item: dict) -> TradeRecord:
        return TradeRecord(
            date=str(item.get("date", "")),
            ticker=str(item.get("ticker", "")).upper(),
            action=str(item.get("action", "")).upper(),
            shares=int(item.get("shares", 0) or 0),
            price=float(item.get("price", 0.0) or 0.0),
            agent=str(item.get("agent", "unknown")),
            thesis=str(item.get("thesis", "")),
            status=str(item.get("status", "OPEN")),
            close_price=float(item["close_price"]) if item.get("close_price") is not None else None,
            pnl=float(item["pnl"]) if item.get("pnl") is not None else None,
        )

    def _default_trade_sources(self) -> list[Path]:
        return [
            self.repo_root / "data" / "trade_journal" / "2026-03_trades.json",
            self.repo_root / "data" / "state" / "decisions_v2.json",
            self.repo_root / "data" / "state" / "decisions.json",
        ]

    def _trade_triggers(self, trade: TradeRecord) -> list[str]:
        triggers: list[str] = []
        pnl_pct = trade.pnl_pct
        if trade.status.upper() == "CLOSED" and pnl_pct is not None and pnl_pct <= -3.0:
            triggers.append("single_trade_loss_over_3pct")
        if self._agent_sharpe(trade.agent) is not None and self._agent_sharpe(trade.agent) < -0.5:
            triggers.append("agent_5d_sharpe_below_-0.5")
        if self._contradicted_three_days(trade.agent, trade.ticker):
            triggers.append("contradicted_3_days")
        if self._agent_weight(trade.agent) < 0.5:
            triggers.append("weight_below_0.5")
        return triggers

    def _primary_trigger(self, trade: TradeRecord) -> str:
        triggers = self._trade_triggers(trade)
        return triggers[0] if triggers else "manual_review"

    def _agent_sharpe(self, agent: str) -> float | None:
        scorecards = self.repo_root / "data" / "state" / "agent_scorecards.json"
        if not scorecards.exists():
            return None
        data = json.loads(scorecards.read_text())
        metrics = data.get(agent, {}).get("metrics") if isinstance(data, dict) else None
        if not metrics:
            return None
        return metrics.get("sharpe_ratio")

    def _agent_weight(self, agent: str) -> float:
        weights_file = self.repo_root / "data" / "state" / "agent_weights.json"
        if not weights_file.exists():
            return 1.0
        data = json.loads(weights_file.read_text())
        value = data.get(agent, 1.0) if isinstance(data, dict) else 1.0
        return float(value) if isinstance(value, (int, float)) else 1.0

    def _contradicted_three_days(self, agent: str, ticker: str) -> bool:
        journal = self.repo_root / "data" / "trade_journal" / "2026-03_trades.json"
        if not journal.exists():
            return False
        data = json.loads(journal.read_text())
        matching = [item for item in data if isinstance(item, dict) and str(item.get("agent", "")).lower() == agent.lower()]
        if len(matching) < 3:
            return False
        last_three = matching[-3:]
        return all(self._trade_from_dict(item).is_closed_loss for item in last_three)

    def _build_prompt(self, trade: TradeRecord, trigger: str, regime: str, vix: float | None) -> str:
        sharpe = self._agent_sharpe(trade.agent)
        return (
            f"You are {trade.agent}. You recommended {trade.action} on {trade.ticker} on {trade.date}. "
            f"The position returned {trade.pnl_pct:.2f}%."
            f"\nTrigger: {trigger}"
            f"\nRecent 5-day Sharpe: {sharpe if sharpe is not None else 'unknown'}"
            f"\nRegime: {regime}"
            f"\nVIX: {vix if vix is not None else 'unknown'}"
            f"\nConviction/thesis: {trade.thesis}"
            "\nAnswer with JSON having diagnosis, missed_signals, knowledge_gaps, regime_mismatch, "
            "suggested_donors, spawn_candidate, spawn_description."
        )

    def _normalize_payload(self, trade: TradeRecord, trigger: str, payload: dict, regime: str) -> dict:
        diagnosis = payload.get("diagnosis") or payload.get("analysis") or "No diagnosis returned."
        missed_signals = payload.get("missed_signals") or []
        knowledge_gaps = payload.get("knowledge_gaps") or []
        regime_mismatch = bool(payload.get("regime_mismatch", False))
        suggested_donors = payload.get("suggested_donors") or []
        spawn_candidate = bool(payload.get("spawn_candidate", False))
        spawn_description = payload.get("spawn_description")
        return {
            "agent_id": trade.agent,
            "agent_version": payload.get("agent_version"),
            "trigger": trigger,
            "date": trade.date,
            "trade_context": {
                "ticker": trade.ticker,
                "direction": trade.action,
                "entry_date": trade.date,
                "exit_date": trade.date,
                "return_pct": trade.pnl_pct,
                "agent_conviction": payload.get("agent_conviction"),
            },
            "diagnosis": diagnosis,
            "missed_signals": missed_signals,
            "knowledge_gaps": knowledge_gaps,
            "regime_mismatch": regime_mismatch,
            "suggested_donors": suggested_donors,
            "spawn_candidate": spawn_candidate,
            "spawn_description": spawn_description,
            "rewrite_triggered": False,
            "rewrite_used_donor": None,
            "post_rewrite_sharpe": None,
            "regime": regime,
            "source_trade": {
                "status": trade.status,
                "shares": trade.shares,
                "price": trade.price,
                "close_price": trade.close_price,
                "pnl": trade.pnl,
            },
        }

    def _default_llm_runner(self, prompt: str) -> dict:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return self._offline_fallback(prompt)
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text if response.content else "{}"
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                match = next((chunk for chunk in [text] if chunk.strip().startswith("{")), None)
                return json.loads(match) if match else self._offline_fallback(prompt)
        except Exception:
            return self._offline_fallback(prompt)

    def _offline_fallback(self, prompt: str) -> dict:
        # Deterministic fallback for environments where the API is unavailable.
        return {
            "diagnosis": "Failed trade review generated offline because Claude was unavailable.",
            "missed_signals": ["risk management", "entry timing"],
            "knowledge_gaps": ["need better regime awareness"],
            "regime_mismatch": "Regime" in prompt,
            "suggested_donors": [],
            "spawn_candidate": False,
            "spawn_description": None,
        }


def run_postmortems_from_default_sources(
    repo_root: Path | None = None,
    regime: str = "unknown",
    vix: float | None = None,
    llm_runner: Callable[[str], dict] | None = None,
    simulation_date: date | None = None,
) -> list[PostMortemResult]:
    engine = PostMortemEngine(repo_root=repo_root, llm_runner=llm_runner, simulation_date=simulation_date)
    return engine.run_from_default_sources(regime=regime, vix=vix, simulation_date=simulation_date)
