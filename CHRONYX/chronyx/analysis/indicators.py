"""Indicateurs techniques (calcul vectorisé, sans look-ahead).

Chaque valeur à l'index i n'utilise que les données jusqu'à i inclus.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    out = out.where(loss != 0, 100.0)  # que des hausses => RSI 100
    return out.where(gain.notna())


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - prev_close).abs(),
                      (df["low"] - prev_close).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def swing_levels(df: pd.DataFrame, window: int = 5, max_levels: int = 6) -> dict[str, list[float]]:
    """Supports / résistances à partir des pivots confirmés.

    Un pivot à l'index i n'est confirmé qu'après `window` bougies : on ne
    considère donc que les pivots jusqu'à len-1-window (pas de look-ahead).
    """
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    res, sup = [], []
    for i in range(window, n - window):
        seg_h = highs[i - window:i + window + 1]
        seg_l = lows[i - window:i + window + 1]
        if highs[i] == seg_h.max():
            res.append(float(highs[i]))
        if lows[i] == seg_l.min():
            sup.append(float(lows[i]))
    return {"resistances": res[-max_levels:], "supports": sup[-max_levels:]}


def add_indicators(df: pd.DataFrame, ema_fast: int = 20, ema_mid: int = 50, ema_slow: int = 200,
                   rsi_period: int = 14, atr_period: int = 14) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = ema(out["close"], ema_fast)
    out["ema_mid"] = ema(out["close"], ema_mid)
    out["ema_slow"] = ema(out["close"], ema_slow)
    out["rsi"] = rsi(out["close"], rsi_period)
    out["atr"] = atr(out, atr_period)
    out = pd.concat([out, macd(out["close"])], axis=1)
    return out
