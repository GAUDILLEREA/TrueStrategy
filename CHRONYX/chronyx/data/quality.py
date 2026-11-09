"""Contrôle de la qualité des données de marché.

Règle : si les données sont incomplètes, incohérentes ou trop anciennes,
le robot NE TRADE PAS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from .symbol_spec import TIMEFRAME_MINUTES


@dataclass
class QualityReport:
    ok: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_ohlc(df: pd.DataFrame, timeframe: str, min_bars: int = 250,
               now: datetime | None = None, max_age_bars: float = 3.0,
               check_freshness: bool = True) -> QualityReport:
    issues: list[str] = []
    warnings: list[str] = []
    required = {"time", "open", "high", "low", "close"}
    if df is None or df.empty:
        return QualityReport(False, ["Aucune donnée reçue."])
    missing = required - set(df.columns)
    if missing:
        return QualityReport(False, [f"Colonnes manquantes : {sorted(missing)}"])

    if len(df) < min_bars:
        issues.append(f"Historique insuffisant : {len(df)} bougies (minimum {min_bars}).")
    if df[list(required - {'time'})].isna().any().any():
        issues.append("Valeurs manquantes (NaN) dans les prix.")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        issues.append("Prix nuls ou négatifs détectés.")
    bad = (df["high"] < df[["open", "close"]].max(axis=1)) | (df["low"] > df[["open", "close"]].min(axis=1)) \
        | (df["high"] < df["low"])
    if bad.any():
        issues.append(f"{int(bad.sum())} bougie(s) incohérente(s) (high/low).")
    if df["time"].duplicated().any():
        issues.append("Horodatages en double.")
    if not df["time"].is_monotonic_increasing:
        issues.append("Horodatages non chronologiques.")

    # Trous dans les données (hors week-end) : avertissement seulement
    minutes = TIMEFRAME_MINUTES[timeframe]
    deltas = df["time"].diff().dt.total_seconds().div(60).iloc[1:]
    weekend = df["time"].iloc[1:].dt.dayofweek.isin([0, 6]).to_numpy()
    big = (deltas > minutes * 10).to_numpy() & ~weekend
    if big.any():
        warnings.append(f"{int(big.sum())} trou(s) important(s) dans l'historique.")

    # Fraîcheur : la dernière bougie doit être récente (sinon flux figé / déconnexion)
    if check_freshness:
        now = now or datetime.now(timezone.utc)
        last = df["time"].iloc[-1].to_pydatetime()
        age_min = (now - last).total_seconds() / 60
        if age_min > minutes * max_age_bars and now.weekday() < 5:
            issues.append(f"Données anciennes : dernière bougie il y a {age_min:.0f} min.")

    return QualityReport(ok=not issues, issues=issues, warnings=warnings)
