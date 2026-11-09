"""Mise à jour du calendrier économique (data/calendrier.csv).

    python -m chronyx.news.importer            # téléchargement automatique
    python -m chronyx.news.importer --fichier export.json

Source automatique : flux JSON hebdomadaire public de Forex Factory
(nfs.faireconomy.media). C'est une source TIERCE, non officielle et sans
garantie. Pour les annonces critiques, recouper avec les calendriers officiels :
  - Fed / FOMC : https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
  - BLS (NFP, CPI) : https://www.bls.gov/schedule/news_release/
  - BEA (PCE, PIB) : https://www.bea.gov/news/schedule
  - BCE : https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.fr.html

En cas d'échec, le fichier existant n'est PAS modifié. S'il devient trop
ancien, le robot bloque le trading (comportement voulu).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

from ..config import load_config

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_IMPACT = {"high": "high", "medium": "medium", "low": "low"}


def parse_ff_json(items: list[dict]) -> pd.DataFrame:
    rows = []
    for it in items:
        impact = _IMPACT.get(str(it.get("impact", "")).strip().lower())
        if impact is None:  # jours fériés, etc.
            continue
        try:
            ts = pd.Timestamp(it["date"]).tz_convert("UTC")
        except Exception:
            continue
        rows.append({"datetime_utc": ts.strftime("%Y-%m-%d %H:%M"), "currency": str(it.get("country", "")).upper(),
                     "impact": impact, "event": str(it.get("title", "")).replace(",", " ")})
    if not rows:
        raise ValueError("Aucun événement exploitable dans les données reçues.")
    return pd.DataFrame(rows).sort_values("datetime_utc")


def fetch(url: str = FEED_URL, timeout: int = 20) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "CHRONYX-calendar/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def update_calendar(target: Path, items: list[dict]) -> int:
    df = parse_ff_json(items)
    tmp = target.with_suffix(".tmp")
    target.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(tmp, index=False)
    tmp.replace(target)  # écriture atomique
    return len(df)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fichier", help="fichier JSON déjà téléchargé")
    args = ap.parse_args(argv)
    cfg = load_config()
    target = cfg.path_for(cfg.get("calendrier", "fichier", default="data/calendrier.csv"))
    try:
        items = json.loads(Path(args.fichier).read_text(encoding="utf-8")) if args.fichier else fetch()
        n = update_calendar(target, items)
    except Exception as e:
        print(f"ÉCHEC de la mise à jour du calendrier : {e}")
        print("Le fichier existant est conservé. Sans calendrier récent, le robot ne tradera pas.")
        return 1
    print(f"Calendrier mis à jour : {n} événements -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
