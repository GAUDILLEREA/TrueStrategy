import numpy as np
import pandas as pd
import pytest

from chronyx.backtest.engine import BacktestConfig, run_backtest
from chronyx.backtest.metrics import compute_metrics, max_drawdown, robustness_score
from chronyx.data.symbol_spec import indicative_spec

from conftest import make_bars

EUR = indicative_spec("EURUSD")


def prepared(rows, signal_bar=0, direction="long", sl=0.0010, spread=0):
    df = make_bars(rows, spread=spread)
    df["long_signal"] = False
    df["short_signal"] = False
    df.loc[signal_bar, "long_signal" if direction == "long" else "short_signal"] = True
    df["sl_distance"] = sl
    return df


CFG = dict(initial_balance=10_000, risk_pct=1.0, rr=2.0, slippage_points=0, max_margin_pct=100)


def test_entry_next_open_with_spread_and_tp_hit():
    rows = [(1.1000, 1.1002, 1.0998, 1.1000), (1.1000, 1.1005, 1.0995, 1.1003), (1.1003, 1.1030, 1.1001, 1.1025),
            (1.1025, 1.1026, 1.1020, 1.1022)]
    r = run_backtest(prepared(rows, spread=10), EUR, BacktestConfig(**CFG))
    t = r.trades.iloc[0]
    assert t.entry == pytest.approx(1.1000 + 10 * EUR.point)      # ouverture bougie suivante + spread (ask)
    assert t.exit_reason == "TP"
    assert t.pnl > 0


def test_sl_assumed_first_when_both_touched():
    rows = [(1.1, 1.1, 1.1, 1.1), (1.1, 1.1001, 1.0999, 1.1), (1.1, 1.1050, 1.0950, 1.1), (1.1, 1.1, 1.1, 1.1)]
    r = run_backtest(prepared(rows), EUR, BacktestConfig(**CFG))
    assert r.trades.iloc[0].exit_reason == "SL"
    assert r.trades.iloc[0].r_multiple == pytest.approx(-1.0, abs=0.05)


def test_gap_through_stop_exits_at_worse_open():
    rows = [(1.1, 1.1, 1.1, 1.1), (1.1, 1.1001, 1.0999, 1.1), (1.0950, 1.0960, 1.0940, 1.0950), (1.095, 1.095, 1.095, 1.095)]
    r = run_backtest(prepared(rows), EUR, BacktestConfig(**CFG))
    t = r.trades.iloc[0]
    assert t.exit_reason == "gap SL"
    assert t.exit == pytest.approx(1.0950)
    assert t.r_multiple < -1.0                                      # pire que le stop


def test_commission_and_slippage_reduce_pnl():
    rows = [(1.1000, 1.1002, 1.0998, 1.1000), (1.1000, 1.1005, 1.0995, 1.1003), (1.1003, 1.1030, 1.1001, 1.1025),
            (1.1025, 1.1026, 1.1020, 1.1022)]
    free = run_backtest(prepared(rows), EUR, BacktestConfig(**CFG)).trades.iloc[0].pnl
    costly = run_backtest(prepared(rows), EUR, BacktestConfig(**{**CFG, "commission_per_lot_rt": 7.0,
                                                                  "slippage_points": 3})).trades.iloc[0].pnl
    assert costly < free


def test_short_trade_exits_at_ask():
    rows = [(1.1, 1.1, 1.1, 1.1), (1.1000, 1.1001, 1.0999, 1.1000), (1.1000, 1.1001, 1.0970, 1.0975),
            (1.0975, 1.0976, 1.0970, 1.0972)]
    r = run_backtest(prepared(rows, direction="short", spread=5), EUR, BacktestConfig(**CFG))
    t = r.trades.iloc[0]
    assert t.direction == "SELL" and t.exit_reason == "TP"


def test_refused_trades_are_not_taken():
    rows = [(1.1, 1.1, 1.1, 1.1)] * 4
    r = run_backtest(prepared(rows), EUR, BacktestConfig(**{**CFG, "initial_balance": 50, "risk_pct": 0.25}))
    assert r.trades.empty and r.refused == 1 and "lot_min" in r.refusal_reasons


def test_metrics():
    trades = pd.DataFrame({"pnl": [10.0, -5.0, 20.0, -5.0], "r_multiple": [2, -1, 4, -1], "commission": [0] * 4,
                           "swap": [0] * 4})
    eq = pd.DataFrame({"time": pd.date_range("2026-11-02", periods=5, freq="D", tz="UTC"),
                       "equity": [100, 110, 105, 125, 120]})
    m = compute_metrics(trades, eq, 100)
    assert m["profit_factor"] == pytest.approx(3.0)
    assert m["win_rate"] == 50.0
    assert m["expectancy"] == pytest.approx(5.0)
    assert max_drawdown(eq["equity"])[0] == pytest.approx(5.0)


def test_robustness_requires_enough_trades_and_flags_simulation():
    few = [{"trades": 5, "profit_factor": 3.0, "profit_net": 10, "max_drawdown_pct": 1}] * 4
    assert robustness_score(few)["score"] == 0.0
    many = [{"trades": 50, "profit_factor": 1.5, "profit_net": 10, "max_drawdown_pct": 3}] * 4
    assert "SIMULÉES" in robustness_score(many, simulated=True)["verdict"]
    assert "Prometteur" in robustness_score(many)["verdict"]
