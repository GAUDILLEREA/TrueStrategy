"""Stratégie A : Scalping de tendance (EMA 20/50/200 + RSI + ATR + confirmation HTF).

Règles d'achat (inverses pour la vente) :
 1. Empilement haussier des EMA : EMA20 > EMA50 > EMA200, maintenu sur 5 bougies
    (évite de décider sur une bougie isolée).
 2. Confirmation timeframe supérieur (H1 par défaut, bougie CLÔTURÉE) :
    clôture HTF > EMA50 HTF et EMA20 HTF > EMA50 HTF.
 3. Pullback : le prix est revenu toucher l'EMA20 dans les 3 dernières bougies.
 4. Reprise : la bougie clôture au-dessus de l'EMA20 et est haussière.
 5. RSI entre 45 et 70 (momentum présent mais pas de surachat).
 Stop loss = ATR x multiplicateur ; Take profit = stop x Risk/Reward.

Aucune rentabilité n'est supposée : la stratégie doit être validée par backtest
sur données réelles du broker puis en démo.
"""
from __future__ import annotations

import pandas as pd

from ..analysis.indicators import add_indicators, ema
from .base import Signal, Strategy, merge_higher_timeframe

DEFAULTS = dict(ema_rapide=20, ema_moyenne=50, ema_lente=200, rsi_periode=14, rsi_achat_min=45,
                rsi_achat_max=70, rsi_vente_min=30, rsi_vente_max=55, atr_periode=14,
                timeframe_confirmation="H1")


class TrendScalping(Strategy):
    name = "trend_scalping"
    label = "A - Scalping de tendance"
    description = "EMA 20/50/200, RSI, ATR et confirmation sur timeframe supérieur."

    def __init__(self, params: dict | None = None, sl_atr_mult: float = 1.5, timeframe: str = "M5") -> None:
        p = {**DEFAULTS, **{k: v for k, v in (params or {}).items() if k != "actif"}}
        self.p = p
        self.sl_atr_mult = sl_atr_mult
        self.timeframe = timeframe

    def prepare(self, df: pd.DataFrame, htf: pd.DataFrame | None = None) -> pd.DataFrame:
        p = self.p
        d = add_indicators(df, p["ema_rapide"], p["ema_moyenne"], p["ema_lente"], p["rsi_periode"], p["atr_periode"])

        if htf is not None and len(htf) > p["ema_moyenne"]:
            h = htf.copy()
            h["ema_f"] = ema(h["close"], p["ema_rapide"])
            h["ema_m"] = ema(h["close"], p["ema_moyenne"])
            d = merge_higher_timeframe(d, h, self.timeframe, p["timeframe_confirmation"], ["close", "ema_f", "ema_m"])
            d["htf_up"] = (d["htf_close"] > d["htf_ema_m"]) & (d["htf_ema_f"] > d["htf_ema_m"])
            d["htf_down"] = (d["htf_close"] < d["htf_ema_m"]) & (d["htf_ema_f"] < d["htf_ema_m"])
        else:
            d["htf_up"] = False
            d["htf_down"] = False

        stack_up = (d["ema_fast"] > d["ema_mid"]) & (d["ema_mid"] > d["ema_slow"])
        stack_dn = (d["ema_fast"] < d["ema_mid"]) & (d["ema_mid"] < d["ema_slow"])
        d["c_stack_up"] = stack_up.rolling(5).sum() == 5
        d["c_stack_dn"] = stack_dn.rolling(5).sum() == 5
        d["c_pullback_up"] = (d["low"] <= d["ema_fast"]).rolling(3).max().astype(bool)
        d["c_pullback_dn"] = (d["high"] >= d["ema_fast"]).rolling(3).max().astype(bool)
        d["c_resume_up"] = (d["close"] > d["ema_fast"]) & (d["close"] > d["open"])
        d["c_resume_dn"] = (d["close"] < d["ema_fast"]) & (d["close"] < d["open"])
        d["c_rsi_up"] = d["rsi"].between(p["rsi_achat_min"], p["rsi_achat_max"])
        d["c_rsi_dn"] = d["rsi"].between(p["rsi_vente_min"], p["rsi_vente_max"])

        up_cols = ["c_stack_up", "htf_up", "c_pullback_up", "c_resume_up", "c_rsi_up"]
        dn_cols = ["c_stack_dn", "htf_down", "c_pullback_dn", "c_resume_dn", "c_rsi_dn"]
        d["long_signal"] = d[up_cols].fillna(False).all(axis=1) & d["atr"].notna()
        d["short_signal"] = d[dn_cols].fillna(False).all(axis=1) & d["atr"].notna()
        d["sl_distance"] = d["atr"] * self.sl_atr_mult
        return d

    _LABELS_UP = {
        "c_stack_up": "EMA20 > EMA50 > EMA200 depuis 5 bougies",
        "htf_up": "Tendance haussière confirmée sur le timeframe supérieur (bougie clôturée)",
        "c_pullback_up": "Retour sur l'EMA20 dans les 3 dernières bougies",
        "c_resume_up": "Bougie de reprise haussière au-dessus de l'EMA20",
        "c_rsi_up": "RSI dans la zone d'achat (45-70)",
    }
    _LABELS_DN = {
        "c_stack_dn": "EMA20 < EMA50 < EMA200 depuis 5 bougies",
        "htf_down": "Tendance baissière confirmée sur le timeframe supérieur (bougie clôturée)",
        "c_pullback_dn": "Retour sur l'EMA20 dans les 3 dernières bougies",
        "c_resume_dn": "Bougie de reprise baissière sous l'EMA20",
        "c_rsi_dn": "RSI dans la zone de vente (30-55)",
    }

    def explain_last(self, prepared: pd.DataFrame, symbol: str, rr: float) -> Signal:
        last = prepared.iloc[-1]
        if pd.isna(last.get("ema_slow")) or pd.isna(last.get("atr")):
            return Signal(symbol, self.label, None, missing=["Historique insuffisant pour calculer l'EMA200 / l'ATR."])

        up = {k: bool(last[k]) if pd.notna(last[k]) else False for k in self._LABELS_UP}
        dn = {k: bool(last[k]) if pd.notna(last[k]) else False for k in self._LABELS_DN}
        up_score, dn_score = sum(up.values()) / 5, sum(dn.values()) / 5
        trend = "haussière" if last.c_stack_up else ("baissière" if last.c_stack_dn else "latérale / indécise")

        if bool(last.long_signal):
            direction, conds, labels, score = "BUY", up, self._LABELS_UP, up_score
        elif bool(last.short_signal):
            direction, conds, labels, score = "SELL", dn, self._LABELS_DN, dn_score
        else:
            direction = None
            conds, labels, score = (up, self._LABELS_UP, up_score) if up_score >= dn_score else (dn, self._LABELS_DN, dn_score)

        sig = Signal(symbol=symbol, strategy=self.label, direction=direction, entry=float(last.close),
                     trend=trend, score=score,
                     confirmations=[labels[k] for k, v in conds.items() if v],
                     missing=[labels[k] for k, v in conds.items() if not v])
        if direction:
            sig.sl_distance = float(last.sl_distance)
            sig.tp_distance = float(last.sl_distance) * rr
            side = "sous" if direction == "BUY" else "au-dessus de"
            sig.invalidation = (f"Clôture {side} l'EMA50 ({last.ema_mid:.5g}) ou perte de la confirmation "
                                f"du timeframe supérieur avant l'entrée.")
        return sig
