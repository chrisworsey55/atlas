from __future__ import annotations

import json

from darwin_v2.equities_adapter import EquitiesAdapter, EquityForecast


def test_equities_adapter_resolves_binary_forecast(tmp_path) -> None:
    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    (price_dir / "NVDA.json").write_text(
        json.dumps(
            {
                "prices": {
                    "2026-01-02": {"open": 10, "high": 11, "low": 9, "close": 10, "adjClose": 10, "volume": 100},
                    "2026-01-05": {"open": 10, "high": 12, "low": 10, "close": 11, "adjClose": 11, "volume": 110},
                }
            }
        )
    )
    adapter = EquitiesAdapter(price_dir)
    forecast = EquityForecast(
        agent_id="agent",
        role="macro",
        ticker="NVDA",
        issued_date="2026-01-02",
        horizon_days=1,
        kind="binary",
        probability=0.6,
    )

    resolved = adapter.resolve_forecast(forecast)

    assert resolved is not None
    assert resolved.outcome == 1
    assert round(resolved.score, 2) == 0.16


def test_equities_adapter_scores_multiclass(tmp_path) -> None:
    price_dir = tmp_path / "prices"
    price_dir.mkdir()
    (price_dir / "AMD.json").write_text(
        json.dumps(
            {
                "prices": {
                    "2026-01-02": {"close": 100, "adjClose": 100},
                    "2026-01-05": {"close": 104, "adjClose": 104},
                }
            }
        )
    )
    adapter = EquitiesAdapter(price_dir)
    forecast = EquityForecast(
        agent_id="agent",
        role="quantitative",
        ticker="AMD",
        issued_date="2026-01-02",
        horizon_days=1,
        kind="multi_class",
        bucket_probabilities={"up_gt_3pct": 0.7, "up_0_3pct": 0.1, "down_0_3pct": 0.1, "down_gt_3pct": 0.1},
    )

    resolved = adapter.resolve_forecast(forecast)

    assert resolved is not None
    assert resolved.outcome == "up_gt_3pct"
    assert resolved.score < 0.15
