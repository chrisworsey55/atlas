"""Darwin v3 backtest wrapper."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import hashlib
import json
import math
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..breeding import BreedingSelector
from ..config import REPO_ROOT
from ..gene_pool import GenePool
from ..postmortem_engine import PostMortemEngine
from ..runtime import DarwinV3Runtime
from .data import PointInTimeFundamentals, PointInTimePrices, PointInTimeRegime
from .variants import VARIANTS, VariantConfig


STARTING_CAPITAL = 100_000.0


@dataclass
class Position:
    ticker: str
    shares: int
    entry_price: float
    entry_date: date
    sector: str = "unknown"
    stop_loss_price: float = 0.0
    target_price: float = 0.0


@dataclass
class TradeEvent:
    date: str
    ticker: str
    side: str
    shares: int
    price: float
    reason: str
    pnl: float = 0.0
    pnl_pct: float = 0.0


class TradeSimulator:
    transaction_cost_bps = 5.0
    slippage_bps = 3.0
    min_holding_days = 3
    max_position_pct = 0.10
    max_sector_pct = 0.25
    stop_loss_pct = -0.08
    cash_floor_pct = 0.20

    def __init__(self, prices: PointInTimePrices, sector_map: dict[str, str] | None = None) -> None:
        self.prices = prices
        self.sector_map = sector_map or {}

    def sector_for(self, ticker: str) -> str:
        return self.sector_map.get(ticker, "unknown")

    def build_position(self, ticker: str, nav: float, cash: float, date_: date) -> Position | None:
        price = self.prices.get_price(ticker, date_)
        if price <= 0:
            return None
        max_dollar = nav * self.max_position_pct
        if max_dollar <= 0:
            return None
        shares = int(max_dollar / price)
        if shares <= 0:
            return None
        return Position(
            ticker=ticker,
            shares=shares,
            entry_price=price,
            entry_date=date_,
            sector=self.sector_for(ticker),
            stop_loss_price=price * (1 + self.stop_loss_pct),
        )

    def execution_price(self, price: float, side: str) -> float:
        basis = self.slippage_bps / 10000.0
        if side.upper() == "BUY":
            return price * (1 + basis)
        return price * (1 - basis)

    def cost(self, notional: float) -> float:
        return notional * (self.transaction_cost_bps / 10000.0)

    def reject_if_oversized(self, position: Position, nav: float, sector_notional: float) -> None:
        if position.entry_price * position.shares > nav * self.max_position_pct + 1e-9:
            raise AssertionError("position exceeds max_position_pct")
        if sector_notional > nav * self.max_sector_pct + 1e-9:
            raise AssertionError("sector exceeds max_sector_pct")


class DarwinV3Backtest:
    def __init__(
        self,
        variant: str,
        start_date: date = date(2025, 3, 1),
        end_date: date = date(2025, 7, 1),
        universe_path: str | Path = "data/backtest/universe_s30.json",
        initial_capital: float = STARTING_CAPITAL,
        gene_pool_path: str | Path = "data/backtest/gene_pool_backtest.db",
    ) -> None:
        if variant not in VARIANTS:
            raise ValueError(f"Unsupported variant: {variant}")
        self.variant = variant
        self.config: VariantConfig = VARIANTS[variant]
        self.start_date = start_date
        self.end_date = end_date
        self.universe_path = Path(universe_path)
        self.initial_capital = initial_capital
        self.gene_pool_path = Path(gene_pool_path)
        self.repo_root = REPO_ROOT
        self.run_root = self.repo_root / "data" / "backtest" / "runs" / f"variant_{variant.lower()}"
        self.results_dir = self.repo_root / "data" / "backtest" / "results"
        self.llm_cache_root = self.repo_root / "data" / "backtest" / "llm_cache" / variant.lower()
        self.runs_state_dir = self.run_root / "state"
        self.journal_path = self.run_root / "simulation_journal.json"
        self.positions_path = self.run_root / "positions.json"
        self.equity_path = self.run_root / "equity_curve.csv"
        self.trades_path = self.run_root / "trades.csv"
        self.summary_path = self.run_root / "summary.json"
        self.api_cost_usd = 0.0

        self._reset_run_dirs()
        self.gene_pool_path.parent.mkdir(parents=True, exist_ok=True)
        if self.gene_pool_path.exists():
            self.gene_pool_path.unlink()
        self.gene_pool = GenePool(db_path=self.gene_pool_path, seed=False, reset=True, simulation_date=self.start_date)
        self.postmortem_engine = PostMortemEngine(
            repo_root=self.repo_root,
            output_dir=self.run_root / "postmortems",
            cache_dir=self.run_root / "postmortems" / "cache",
            simulation_date=self.start_date,
        )
        self.breeding_selector = BreedingSelector(
            gene_pool=self.gene_pool,
            postmortem_dir=self.run_root / "postmortems",
            log_path=self.run_root / "breeding_log.json",
            simulation_date=self.start_date,
        )
        self.runtime = DarwinV3Runtime(repo_root=self.repo_root, simulation_date=self.start_date)
        self.prices = PointInTimePrices(universe_file=self.universe_path, simulation_date=self.end_date)
        self.fundamentals = PointInTimeFundamentals(simulation_date=self.end_date)
        self.regime = PointInTimeRegime(prices=self.prices, simulation_date=self.end_date)
        self.sector_map = self._load_sector_map()
        self.simulator = TradeSimulator(self.prices, self.sector_map)

        self.universe = self._load_universe()
        self.trading_days = self._load_trading_days()
        self.positions: dict[str, Position] = {}
        self.trade_events: list[TradeEvent] = []
        self.daily_rows: list[dict[str, Any]] = []
        self.journal: list[dict[str, Any]] = []
        self.day_counter = 0
        self.warmup_20d_active = False
        self.warmup_60d_active = False
        self.current_nav = self.initial_capital

    def _reset_run_dirs(self) -> None:
        if self.run_root.exists():
            shutil.rmtree(self.run_root)
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.runs_state_dir.mkdir(parents=True, exist_ok=True)
        self.llm_cache_root.mkdir(parents=True, exist_ok=True)

    def _load_universe(self) -> list[str]:
        data = json.loads(self.universe_path.read_text())
        if isinstance(data, list):
            return [str(item).upper() for item in data]
        if isinstance(data, dict):
            return [str(item).upper() for item in data.get("tickers", [])]
        raise ValueError("Unsupported universe format")

    def _load_sector_map(self) -> dict[str, str]:
        path = self.repo_root / "data" / "backtest" / "cache" / "sector_map.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return {str(k).upper(): str(v) for k, v in data.items()}
        return {}

    def _load_trading_days(self) -> list[date]:
        for ticker in ("SPY", self.universe[0]):
            try:
                payload = self.prices._load_payload(ticker)
                price_map = self.prices._price_map(payload)
                days = [date.fromisoformat(key) for key in sorted(price_map) if self.start_date <= date.fromisoformat(key) <= self.end_date]
                if days:
                    return days
            except Exception:
                continue
        raise FileNotFoundError("Could not derive trading calendar from cache")

    def _assert_no_lookahead(self, observed_date: date, simulation_date: date, barrier_days: int = 0, label: str = "") -> None:
        cutoff = simulation_date - timedelta(days=barrier_days)
        if observed_date > cutoff:
            raise AssertionError(f"look-ahead barrier violated for {label}: {observed_date.isoformat()} > {cutoff.isoformat()}")

    def _llm_cache_path(self, agent_id: str, simulation_date: date, input_hash: str) -> Path:
        return self.llm_cache_root / f"{agent_id}" / f"{simulation_date.isoformat()}_{input_hash}.json"

    def _hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _score_ticker(self, ticker: str, simulation_date: date) -> float:
        prices = self.prices._load_payload(ticker)
        price_map = self.prices._price_map(prices)
        closes = []
        for key in sorted(price_map):
            current = date.fromisoformat(key)
            if current <= simulation_date:
                close = self.prices._extract_close(price_map[key])
                if close is not None:
                    closes.append((current, close))
        if len(closes) < 6:
            return float("-inf")
        if self.config.use_multidim_scorer and self.day_counter >= 60:
            return self._composite_score(closes, simulation_date)
        if self.config.use_multidim_scorer and self.day_counter >= 21:
            return self._composite_score(closes, simulation_date, include_60d=False)
        return self._sharpe_score(closes, 5)

    def _composite_score(self, closes: list[tuple[date, float]], simulation_date: date, include_60d: bool = True) -> float:
        score_5 = self._sharpe_score(closes, 5)
        score_20 = self._sharpe_score(closes, 20) if len(closes) >= 21 else score_5
        score_60 = self._sharpe_score(closes, 60) if include_60d and len(closes) >= 61 else score_20
        return 0.5 * score_5 + 0.3 * score_20 + 0.2 * score_60

    def _sharpe_score(self, closes: list[tuple[date, float]], lookback: int) -> float:
        if len(closes) < lookback + 1:
            return float("-inf")
        recent = closes[-(lookback + 1):]
        rets = [(recent[i][1] / recent[i - 1][1]) - 1.0 for i in range(1, len(recent))]
        if not rets:
            return float("-inf")
        mean = sum(rets) / len(rets)
        variance = sum((r - mean) ** 2 for r in rets) / len(rets)
        if variance <= 0:
            return mean * math.sqrt(252)
        return (mean / math.sqrt(variance)) * math.sqrt(252)

    def _close_position(self, ticker: str, simulation_date: date, reason: str) -> TradeEvent | None:
        position = self.positions.get(ticker)
        if not position:
            return None
        current_price = self.prices.get_price(ticker, simulation_date)
        exec_price = self.simulator.execution_price(current_price, "SELL")
        notional = exec_price * position.shares
        self.current_nav += notional - self.simulator.cost(notional)
        pnl = (exec_price - position.entry_price) * position.shares - self.simulator.cost(notional)
        pnl_pct = pnl / (position.entry_price * position.shares) * 100 if position.entry_price * position.shares else 0.0
        del self.positions[ticker]
        event = TradeEvent(
            date=simulation_date.isoformat(),
            ticker=ticker,
            side="SELL",
            shares=position.shares,
            price=exec_price,
            reason=reason,
            pnl=pnl,
            pnl_pct=pnl_pct,
        )
        self.trade_events.append(event)
        return event

    def _open_position(self, ticker: str, simulation_date: date, nav: float) -> TradeEvent | None:
        if ticker in self.positions:
            return None
        position = self.simulator.build_position(ticker, nav=nav, cash=self.current_nav, date_=simulation_date)
        if position is None:
            return None
        notional = position.entry_price * position.shares
        self.simulator.reject_if_oversized(position, nav, sector_notional=self._sector_notional(position.sector))
        if self.current_nav < nav * self.simulator.cash_floor_pct:
            return None
        exec_price = self.simulator.execution_price(position.entry_price, "BUY")
        cost = self.simulator.cost(exec_price * position.shares)
        total = exec_price * position.shares + cost
        if total > self.current_nav - nav * self.simulator.cash_floor_pct:
            return None
        self.current_nav -= total
        self.positions[ticker] = position
        event = TradeEvent(
            date=simulation_date.isoformat(),
            ticker=ticker,
            side="BUY",
            shares=position.shares,
            price=exec_price,
            reason="signal_entry",
        )
        self.trade_events.append(event)
        return event

    def _sector_notional(self, sector: str) -> float:
        total = 0.0
        for pos in self.positions.values():
            if pos.sector == sector:
                total += pos.entry_price * pos.shares
        return total

    def _daily_pnl(self, simulation_date: date) -> float:
        market_value = 0.0
        for ticker, pos in self.positions.items():
            price = self.prices.get_price(ticker, simulation_date)
            market_value += price * pos.shares
        return self.current_nav + market_value

    def _portfolio_snapshot(self, simulation_date: date) -> dict[str, Any]:
        return {
            "date": simulation_date.isoformat(),
            "positions": {ticker: asdict(pos) for ticker, pos in self.positions.items()},
            "cash": self.current_nav,
        }

    def _postmortem_context(self, simulation_date: date) -> list[dict[str, Any]]:
        records = []
        for event in self.trade_events:
            if event.side != "SELL":
                continue
            closed_date = date.fromisoformat(event.date)
            self._assert_no_lookahead(closed_date, simulation_date, barrier_days=3, label="postmortem")
            if event.pnl < 0:
                records.append(asdict(event))
        return records

    def _run_breeding(self, simulation_date: date) -> list[dict[str, Any]]:
        if not self.config.use_breeding:
            return []
        postmortems = self._postmortem_context(simulation_date)
        if len(postmortems) < 3:
            return []
        strategies = []
        for record in postmortems[-3:]:
            agent = record["ticker"].lower()
            input_hash = self._hash_text(json.dumps(record, sort_keys=True))
            cache_path = self._llm_cache_path(agent, simulation_date, input_hash)
            if cache_path.exists():
                payload = json.loads(cache_path.read_text())
            else:
                payload = {
                    "diagnosis": "deterministic offline backtest diagnosis",
                    "missed_signals": ["timing"],
                    "knowledge_gaps": ["regime awareness"],
                    "regime_mismatch": False,
                    "spawn_candidate": False,
                    "spawn_description": None,
                }
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
            strategy = self.breeding_selector.select_rewrite_strategy(
                agent_id=agent,
                current_version=1,
                current_regime=self.regime.get_regime(simulation_date),
                current_score=None,
                simulation_date=simulation_date,
            )
            strategies.append({"agent": agent, "strategy": asdict(strategy), "postmortem": record, "diagnosis": payload})
        return strategies

    def _judge_payload(self, simulation_date: date) -> dict[str, Any]:
        if not self.config.use_judge:
            return {"status": "skipped", "date": simulation_date.isoformat()}
        closed = [e for e in self.trade_events if e.side == "SELL"]
        for event in closed:
            self._assert_no_lookahead(date.fromisoformat(event.date), simulation_date, barrier_days=5, label="judge")
        return {
            "status": "ok",
            "date": simulation_date.isoformat(),
            "closed_trades": len(closed),
            "trust_map": {event.ticker: 0.5 for event in closed},
        }

    def _janus_reweight(self, simulation_date: date) -> dict[str, Any]:
        if not self.config.use_judge:
            return {"status": "skipped"}
        closed = [e for e in self.trade_events if e.side == "SELL"]
        for event in closed:
            self._assert_no_lookahead(date.fromisoformat(event.date), simulation_date, barrier_days=10, label="janus")
        return {"status": "ok", "weights": {event.ticker: 1.0 for event in closed}}

    def _apply_daily_signals(self, simulation_date: date) -> list[str]:
        scores = [(self._score_ticker(ticker, simulation_date), ticker) for ticker in self.universe]
        scores.sort(reverse=True)
        open_candidates = [ticker for score, ticker in scores[:3] if math.isfinite(score) and score > 0]
        return open_candidates

    def _update_positions(self, simulation_date: date) -> list[TradeEvent]:
        events: list[TradeEvent] = []
        for ticker, position in list(self.positions.items()):
            current_price = self.prices.get_price(ticker, simulation_date)
            if current_price <= position.stop_loss_price:
                event = self._close_position(ticker, simulation_date, "stop_loss")
                if event:
                    events.append(event)
                continue
            if (simulation_date - position.entry_date).days >= self.simulator.min_holding_days:
                score = self._score_ticker(ticker, simulation_date)
                if score <= 0:
                    event = self._close_position(ticker, simulation_date, "signal_exit")
                    if event:
                        events.append(event)
        return events

    def run(self, dry_run_days: int | None = None) -> dict[str, Any]:
        selected_days = self.trading_days[:dry_run_days] if dry_run_days is not None else self.trading_days
        if not selected_days:
            raise ValueError("No trading days available")

        self.journal.append({
            "event": "start",
            "variant": self.variant,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "universe_size": len(self.universe),
        })

        for day_idx, simulation_date in enumerate(selected_days, start=1):
            self.prices.simulation_date = simulation_date
            self.fundamentals.simulation_date = simulation_date
            self.regime.simulation_date = simulation_date
            self.postmortem_engine.simulation_date = simulation_date
            self.breeding_selector.simulation_date = simulation_date
            self.day_counter = day_idx
            self.warmup_20d_active = day_idx >= 21
            self.warmup_60d_active = day_idx >= 61
            regime = self.regime.get_regime(simulation_date)
            before_value = self._daily_pnl(simulation_date)

            # PRE-MARKET
            pre_market_events = self._update_positions(simulation_date)
            breeding_events = self._run_breeding(simulation_date) if self.config.use_breeding else []

            # MARKET OPEN
            candidates = self._apply_daily_signals(simulation_date)
            if self.variant == "A" or self.variant == "C" or self.variant == "E":
                for ticker in candidates:
                    if len(self.positions) >= 3:
                        break
                    self._open_position(ticker, simulation_date, nav=before_value)

            judge_payload = self._judge_payload(simulation_date)
            janus_payload = self._janus_reweight(simulation_date)

            # END OF DAY
            end_value = self._daily_pnl(simulation_date)
            daily_return = ((end_value - before_value) / before_value) if before_value else 0.0
            self.current_nav = end_value - sum(self.prices.get_price(t, simulation_date) * p.shares for t, p in self.positions.items())

            daily_row = {
                "day": day_idx,
                "date": simulation_date.isoformat(),
                "regime": regime,
                "nav": end_value,
                "daily_return": daily_return,
                "cash": self.current_nav,
                "open_positions": len(self.positions),
                "closed_trades": len(pre_market_events),
                "breeding_events": len(breeding_events),
                "judge_status": judge_payload.get("status"),
                "janus_status": janus_payload.get("status"),
            }
            self.daily_rows.append(daily_row)
            self.journal.append(daily_row)

        self._write_outputs()
        summary = self._summary()
        self.summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
        return summary

    def _summary(self) -> dict[str, Any]:
        values = [row["nav"] for row in self.daily_rows]
        returns = [row["daily_return"] for row in self.daily_rows]
        final_value = values[-1] if values else self.initial_capital
        total_return_pct = ((final_value - self.initial_capital) / self.initial_capital) * 100
        mean_ret = sum(returns) / len(returns) if returns else 0.0
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns) if returns else 0.0
        std_dev = math.sqrt(variance) if variance > 0 else 0.0
        sharpe = (mean_ret / std_dev) * math.sqrt(252) if std_dev > 0 else 0.0
        peak = values[0] if values else self.initial_capital
        max_dd = 0.0
        for v in values:
            if v > peak:
                peak = v
            dd = ((v - peak) / peak) * 100 if peak else 0.0
            if dd < max_dd:
                max_dd = dd
        winning = [t for t in self.trade_events if t.side == "SELL" and t.pnl > 0]
        closed = [t for t in self.trade_events if t.side == "SELL"]
        win_rate = (len(winning) / len(closed) * 100) if closed else 0.0
        annualized_return = ((final_value / self.initial_capital) ** (252 / max(len(values), 1)) - 1) * 100 if values else 0.0
        return {
            "variant": self.variant,
            "trading_days": len(self.daily_rows),
            "total_return_pct": total_return_pct,
            "annualized_return_pct": annualized_return,
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": max_dd,
            "win_rate_pct": win_rate,
            "total_trades": len(closed),
            "ending_value": final_value,
            "api_cost_usd": self.api_cost_usd,
            "warmup_20d_active": self.warmup_20d_active,
            "warmup_60d_active": self.warmup_60d_active,
        }

    def _write_outputs(self) -> None:
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        with self.equity_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["day", "date", "regime", "nav", "daily_return", "cash", "open_positions", "closed_trades", "breeding_events", "judge_status", "janus_status"])
            writer.writeheader()
            writer.writerows(self.daily_rows)
        with self.trades_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "ticker", "side", "shares", "price", "reason", "pnl", "pnl_pct"])
            writer.writeheader()
            writer.writerows([asdict(t) for t in self.trade_events])
        self.positions_path.write_text(
            json.dumps({ticker: asdict(pos) for ticker, pos in self.positions.items()}, indent=2, sort_keys=True, default=str)
        )
        self.journal_path.write_text(json.dumps(self.journal, indent=2, sort_keys=True))

    def assert_trade_simulator_rejects_oversized_position(self) -> None:
        pos = Position(ticker="TEST", shares=10_000, entry_price=100.0, entry_date=self.start_date)
        self.simulator.reject_if_oversized(pos, nav=100_000.0, sector_notional=0.0)
