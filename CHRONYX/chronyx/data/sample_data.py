"""Données SIMULÉES pour le mode hors-ligne (tests, démonstration du dashboard).

ATTENTION : ces données sont générées aléatoirement. Elles servent à vérifier
que le code fonctionne, PAS à juger la rentabilité d'une stratégie. Tout
résultat de backtest sur ces données est marqué « SIMULÉ ».
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .symbol_spec import TIMEFRAME_MINUTES

# Prix de départ FICTIFS (ordre de grandeur seulement).
_START_PRICE = {"XAUUSD": 4000.0, "EURUSD": 1.08, "GBPUSD": 1.27, "USDJPY": 150.0, "AUDUSD": 0.66,
                "USDCAD": 1.36, "USDCHF": 0.88, "EURJPY": 162.0, "GBPJPY": 190.0}
_DAILY_VOL = {"XAUUSD": 0.011, "GBPJPY": 0.008}


def generate_ohlc(symbol: str = "XAUUSD", timeframe: str = "M5", bars: int = 3000, seed: int = 42,
                  end: pd.Timestamp | None = None, spread_points: int = 20) -> pd.DataFrame:
    """Marche aléatoire avec régimes (tendance / range) et volatilité intrajournalière.

    Les week-ends sont exclus. Les prix sont des prix BID, comme dans MT5.
    """
    rng = np.random.default_rng(seed)
    minutes = TIMEFRAME_MINUTES[timeframe]
    end = end or pd.Timestamp("2026-10-30 21:00", tz="UTC")
    idx = pd.date_range(end=end, periods=int(bars * 1.5) + 10, freq=f"{minutes}min", tz="UTC")
    idx = idx[idx.dayofweek < 5][-bars:]

    daily_vol = _DAILY_VOL.get(symbol, 0.005)
    bar_vol = daily_vol * np.sqrt(minutes / 1440)
    hours = idx.hour.to_numpy()
    session_mult = np.where((hours >= 7) & (hours < 17), 1.3, 0.7)

    # régimes : dérive changeante par blocs
    block = max(50, bars // 20)
    drift = np.repeat(rng.choice([-1, 0, 0, 1], size=bars // block + 1) * bar_vol * 0.15, block)[:bars]
    rets = drift + rng.standard_normal(bars) * bar_vol * session_mult
    close = _START_PRICE.get(symbol, 1.0) * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[close[0]], close[:-1]])
    wick = np.abs(rng.standard_normal(bars)) * bar_vol * close * 0.6
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - np.abs(rng.standard_normal(bars)) * bar_vol * close * 0.6

    digits = 2 if symbol == "XAUUSD" else (3 if symbol.endswith("JPY") else 5)
    df = pd.DataFrame({
        "time": idx, "open": open_.round(digits), "high": high.round(digits), "low": low.round(digits),
        "close": close.round(digits), "tick_volume": rng.integers(50, 500, bars), "spread": spread_points,
    })
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    df.attrs["simulated"] = True
    return df


def resample(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Agrège des bougies vers un timeframe supérieur (sans regarder dans le futur :
    l'horodatage d'une bougie agrégée est son OUVERTURE, comme dans MT5)."""
    rule = f"{TIMEFRAME_MINUTES[timeframe]}min"
    out = (df.set_index("time")
             .resample(rule, label="left", closed="left")
             .agg({"open": "first", "high": "max", "low": "min", "close": "last",
                   "tick_volume": "sum", "spread": "mean"})
             .dropna(subset=["open"])
             .reset_index())
    out.attrs.update(df.attrs)
    return out
