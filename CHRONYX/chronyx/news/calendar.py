"""Calendrier économique et filtre d'annonces.

Règle de sécurité (« fail-closed ») : si le calendrier est absent, vide,
trop ancien ou illisible, le robot BLOQUE le trading. Aucune actualité n'est
inventée.

Source v1 : fichier CSV local (data/calendrier.csv), à mettre à jour depuis
une source fiable (voir docs/GUIDE_UTILISATEUR.md). Colonnes :
    datetime_utc,currency,impact,event
    2026-11-14 13:30,USD,high,CPI (inflation US)
Le champ `impact` vaut low | medium | high.
Un connecteur automatique vers un fournisseur de données sera ajouté en phase 8.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Devises qui influencent chaque instrument. L'or réagit fortement au dollar US.
SYMBOL_CURRENCIES = {
    "XAUUSD": {"USD"}, "EURUSD": {"EUR", "USD"}, "GBPUSD": {"GBP", "USD"}, "USDJPY": {"USD", "JPY"},
    "AUDUSD": {"AUD", "USD"}, "USDCAD": {"USD", "CAD"}, "USDCHF": {"USD", "CHF"},
    "EURJPY": {"EUR", "JPY"}, "GBPJPY": {"GBP", "JPY"},
}

MAJOR_KEYWORDS = ("NFP", "Non-Farm", "CPI", "PCE", "FOMC", "Fed", "BCE", "ECB", "Taux", "Rate", "GDP", "PIB",
                  "Chômage", "Unemployment", "Powell", "Lagarde", "Inflation")


@dataclass
class CalendarStatus:
    usable: bool
    message: str
    events: pd.DataFrame


def load_calendar(path: str | Path, max_age_hours: float = 24, now: datetime | None = None) -> CalendarStatus:
    now = now or datetime.now(timezone.utc)
    p = Path(path)
    empty = pd.DataFrame(columns=["datetime_utc", "currency", "impact", "event"])
    if not p.exists():
        return CalendarStatus(False, f"Calendrier introuvable ({p.name}) : trading bloqué par sécurité.", empty)
    try:
        df = pd.read_csv(p)
        df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], utc=True)
        df["impact"] = df["impact"].str.lower().str.strip()
        df["currency"] = df["currency"].str.upper().str.strip()
    except Exception as e:  # fichier corrompu
        return CalendarStatus(False, f"Calendrier illisible ({e}) : trading bloqué.", empty)
    if df.empty:
        return CalendarStatus(False, "Calendrier vide : trading bloqué (données incertaines).", empty)
    age_h = (now.timestamp() - p.stat().st_mtime) / 3600
    if age_h > max_age_hours:
        return CalendarStatus(False, f"Calendrier mis à jour il y a {age_h:.0f} h (max {max_age_hours:.0f} h) : "
                                     f"trading bloqué.", df)
    if df["datetime_utc"].max() < now:
        return CalendarStatus(False, "Le calendrier ne contient aucun événement futur : trading bloqué.", df)
    return CalendarStatus(True, f"Calendrier OK ({len(df)} événements).", df.sort_values("datetime_utc"))


def news_block(status: CalendarStatus, symbol: str, now: datetime, minutes_before: int = 15,
               minutes_after: int = 15, blocking_impacts: tuple[str, ...] = ("high",)) -> list[str]:
    if not status.usable:
        return [status.message]
    cur = SYMBOL_CURRENCIES.get(symbol, set())
    ev = status.events
    ev = ev[ev["currency"].isin(cur) & ev["impact"].isin(blocking_impacts)]
    lo, hi = now - timedelta(minutes=minutes_after), now + timedelta(minutes=minutes_before)
    hits = ev[(ev["datetime_utc"] >= lo) & (ev["datetime_utc"] <= hi)]
    return [f"Annonce majeure {r.currency} « {r.event} » à {r.datetime_utc:%H:%M} UTC "
            f"(fenêtre -{minutes_before}/+{minutes_after} min)." for r in hits.itertuples()]


def next_event(status: CalendarStatus, symbol: str, now: datetime) -> dict | None:
    if status.events.empty:
        return None
    cur = SYMBOL_CURRENCIES.get(symbol, set())
    ev = status.events[(status.events["currency"].isin(cur)) & (status.events["datetime_utc"] >= now)]
    if ev.empty:
        return None
    r = ev.iloc[0]
    return {"heure_utc": r.datetime_utc, "devise": r.currency, "impact": r.impact, "evenement": r.event}


def news_mask(times: pd.Series, events: pd.DataFrame, symbol: str, minutes_before: int, minutes_after: int,
              blocking_impacts: tuple[str, ...] = ("high",)) -> pd.Series:
    """Version vectorisée pour le backtest : True = trading bloqué à cette bougie."""
    mask = pd.Series(False, index=times.index)
    if events is None or events.empty:
        return mask
    cur = SYMBOL_CURRENCIES.get(symbol, set())
    ev = events[events["currency"].isin(cur) & events["impact"].isin(blocking_impacts)]
    for t in ev["datetime_utc"]:
        mask |= (times >= t - timedelta(minutes=minutes_before)) & (times <= t + timedelta(minutes=minutes_after))
    return mask
