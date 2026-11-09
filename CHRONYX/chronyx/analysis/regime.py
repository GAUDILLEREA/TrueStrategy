"""Classification simple (à base de règles) du régime de marché.

Version 1 : règles transparentes. Le module IA (phase 10) viendra apprendre
ces régimes à partir des données, avec validation chronologique.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Regime:
    trend: str          # "haussière" | "baissière" | "latérale"
    volatility: str     # "faible" | "normale" | "forte"
    atr_pct_rank: float  # percentile de l'ATR actuel sur l'historique récent (0-100)
    favorable_scalping: bool
    comment: str


def classify(df: pd.DataFrame, lookback: int = 500) -> Regime:
    """df doit contenir ema_fast/ema_mid/ema_slow/atr (voir add_indicators)."""
    last = df.iloc[-1]
    if pd.isna(last.get("ema_slow")) or pd.isna(last.get("atr")):
        return Regime("inconnue", "inconnue", float("nan"), False, "Historique insuffisant pour les indicateurs.")

    if last.ema_fast > last.ema_mid > last.ema_slow and last.close > last.ema_mid:
        trend = "haussière"
    elif last.ema_fast < last.ema_mid < last.ema_slow and last.close < last.ema_mid:
        trend = "baissière"
    else:
        trend = "latérale"

    atr_hist = df["atr"].dropna().iloc[-lookback:]
    rank = float((atr_hist < last.atr).mean() * 100)
    vol = "faible" if rank < 20 else ("forte" if rank > 90 else "normale")

    favorable = vol == "normale"
    if vol == "faible":
        comment = "Volatilité trop faible : les frais pèsent lourd face au mouvement attendu."
    elif vol == "forte":
        comment = "Volatilité extrême : risque de slippage et de stops balayés."
    else:
        comment = "Volatilité exploitable pour le scalping."
    return Regime(trend, vol, rank, favorable, comment)
