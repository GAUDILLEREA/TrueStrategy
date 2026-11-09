"""Registre des stratégies disponibles et de leur statut de développement."""
from __future__ import annotations

from .trend_scalping import TrendScalping

IMPLEMENTED = {"trend_scalping": TrendScalping}

# Stratégies prévues (phase 9). Statut affiché honnêtement dans le dashboard.
PLANNED = {
    "breakout": "B - Scalping breakout (cassure de range + volatilité)",
    "pullback": "C - Scalping pullback (zone technique + reprise)",
    "price_action": "D - Price Action (structure, zones, chandeliers)",
    "gold_momentum": "E - Gold Momentum (volatilité XAUUSD, dollar, actualités)",
}


def build(name: str, params: dict | None, sl_atr_mult: float, timeframe: str):
    if name not in IMPLEMENTED:
        raise KeyError(f"Stratégie '{name}' non disponible (statut : {PLANNED.get(name, 'inconnue')} - à développer).")
    return IMPLEMENTED[name](params, sl_atr_mult=sl_atr_mult, timeframe=timeframe)
