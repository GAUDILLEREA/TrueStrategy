import numpy as np
import pandas as pd

from chronyx.analysis.indicators import atr, ema, rsi, swing_levels
from chronyx.analysis.regime import classify
from chronyx.data.quality import check_ohlc
from chronyx.data.sample_data import generate_ohlc, resample
from chronyx.strategies.base import merge_higher_timeframe
from chronyx.strategies.trend_scalping import TrendScalping

from conftest import make_bars


def test_indicator_ranges():
    df = generate_ohlc("EURUSD", "M5", 600)
    r = rsi(df["close"]).dropna()
    assert ((r >= 0) & (r <= 100)).all()
    assert (atr(df).dropna() > 0).all()
    assert ema(df["close"], 20).iloc[:19].isna().all()


def test_indicators_have_no_lookahead():
    df = generate_ohlc("XAUUSD", "M5", 800)
    full = TrendScalping().prepare(df, resample(df, "H1"))
    cut = 600
    part = TrendScalping().prepare(df.iloc[:cut], resample(df.iloc[:cut], "H1"))
    cols = ["ema_fast", "ema_mid", "ema_slow", "rsi", "atr", "long_signal", "short_signal"]
    pd.testing.assert_frame_equal(full[cols].iloc[:cut].reset_index(drop=True), part[cols].reset_index(drop=True))


def test_htf_merge_uses_only_closed_bars():
    ltf = make_bars([(1, 1, 1, 1)] * 24, start="2026-11-02 08:00")          # M5 de 08:00 à 09:55
    htf = pd.DataFrame({"time": pd.to_datetime(["2026-11-02 07:00", "2026-11-02 08:00", "2026-11-02 09:00"], utc=True),
                        "close": [7.0, 8.0, 9.0]})
    m = merge_higher_timeframe(ltf, htf, "M5", "H1", ["close"])
    # La bougie M5 08:50 (clôture 08:55) ne doit voir que la bougie H1 07:00 (clôturée à 08:00)
    assert m.loc[m["time"] == pd.Timestamp("2026-11-02 08:50", tz="UTC"), "htf_close"].item() == 7.0
    # La bougie M5 08:55 clôture à 09:00 : la H1 de 08:00 vient de clôturer
    assert m.loc[m["time"] == pd.Timestamp("2026-11-02 08:55", tz="UTC"), "htf_close"].item() == 8.0


def test_swing_levels_and_regime():
    df = TrendScalping().prepare(generate_ohlc("XAUUSD", "M5", 1000))
    lv = swing_levels(df.tail(300))
    assert lv["supports"] and lv["resistances"]
    reg = classify(df)
    assert reg.trend in ("haussière", "baissière", "latérale")
    assert 0 <= reg.atr_pct_rank <= 100


def test_explain_last_gives_reasons():
    df = generate_ohlc("XAUUSD", "M5", 1000)
    s = TrendScalping()
    sig = s.explain_last(s.prepare(df, resample(df, "H1")), "XAUUSD", 1.5)
    assert len(sig.confirmations) + len(sig.missing) == 5
    if sig.direction:
        assert sig.stop_loss is not None and sig.invalidation


def test_quality_detects_problems():
    df = generate_ohlc("EURUSD", "M5", 300)
    assert check_ohlc(df, "M5", check_freshness=False).ok
    bad = df.copy()
    bad.loc[10, "high"] = bad.loc[10, "low"] - 1
    bad.loc[20, "close"] = np.nan
    rep = check_ohlc(bad, "M5", check_freshness=False)
    assert not rep.ok and len(rep.issues) >= 2
    # données anciennes
    rep = check_ohlc(df, "M5", now=df["time"].iloc[-1].to_pydatetime() + pd.Timedelta(hours=2))
    if df["time"].iloc[-1].dayofweek < 5:
        assert any("anciennes" in i for i in rep.issues)
    assert not check_ohlc(df.head(50), "M5", check_freshness=False).ok
