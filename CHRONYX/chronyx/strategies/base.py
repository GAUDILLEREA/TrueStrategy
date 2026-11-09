"""Socle commun des stratégies : format de signal explicable."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd

from ..data.symbol_spec import TIMEFRAME_MINUTES


@dataclass
class Signal:
    symbol: str
    strategy: str
    direction: str | None                   # "BUY", "SELL" ou None (pas de trade)
    entry: float | None = None              # prix de référence (clôture de la dernière bougie)
    sl_distance: float | None = None        # distance du stop, en prix
    tp_distance: float | None = None
    trend: str = "inconnue"
    confirmations: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)   # conditions non remplies
    invalidation: str = ""
    score: float = 0.0                      # part des conditions remplies (0-1), PAS une probabilité de gain

    @property
    def stop_loss(self) -> float | None:
        if self.direction is None or self.entry is None or self.sl_distance is None:
            return None
        return self.entry - self.sl_distance if self.direction == "BUY" else self.entry + self.sl_distance

    @property
    def take_profit(self) -> float | None:
        if self.direction is None or self.entry is None or self.tp_distance is None:
            return None
        return self.entry + self.tp_distance if self.direction == "BUY" else self.entry - self.tp_distance


class Strategy(ABC):
    name: str = "base"
    label: str = "Stratégie"
    description: str = ""

    @abstractmethod
    def prepare(self, df: pd.DataFrame, htf: pd.DataFrame | None = None) -> pd.DataFrame:
        """Ajoute indicateurs et colonnes 'long_signal' / 'short_signal' (booléens) + 'sl_distance'."""

    @abstractmethod
    def explain_last(self, prepared: pd.DataFrame, symbol: str, rr: float) -> Signal:
        """Signal explicable sur la DERNIÈRE bougie clôturée."""


def merge_higher_timeframe(ltf: pd.DataFrame, htf: pd.DataFrame, ltf_tf: str, htf_tf: str,
                           columns: list[str], prefix: str = "htf_") -> pd.DataFrame:
    """Joint les valeurs du timeframe supérieur SANS look-ahead.

    Une bougie HTF n'est utilisable qu'une fois CLÔTURÉE. On aligne donc l'heure
    de clôture de chaque bougie LTF sur l'heure de clôture de la dernière bougie
    HTF terminée.
    """
    l = ltf.copy()
    h = htf[["time"] + columns].copy()
    l["_close_time"] = l["time"] + pd.Timedelta(minutes=TIMEFRAME_MINUTES[ltf_tf])
    h["_close_time"] = h["time"] + pd.Timedelta(minutes=TIMEFRAME_MINUTES[htf_tf])
    h = h.drop(columns=["time"]).rename(columns={c: prefix + c for c in columns})
    merged = pd.merge_asof(l.sort_values("_close_time"), h.sort_values("_close_time"),
                           on="_close_time", direction="backward")
    return merged.drop(columns=["_close_time"])
