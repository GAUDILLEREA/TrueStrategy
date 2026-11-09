"""Comparaison des brokers.

Le module ne choisit JAMAIS un broker à votre place. Il :
 1. affiche les informations réglementaires (avec leur statut de vérification) ;
 2. exclut d'office les brokers incompatibles (pas de MT5, robots interdits) ;
 3. peut MESURER les spreads réels sur un compte démo MT5 de chaque broker,
    ce qui est plus fiable que les spreads « à partir de » publicitaires ;
 4. calcule le coût total d'un trade minimum (spread + commission) en €.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

BROKERS_FILE = Path(__file__).with_name("brokers.yaml")


def load_brokers(path: Path = BROKERS_FILE) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def eligibility(b: dict) -> tuple[str, list[str]]:
    """Renvoie (statut, raisons). Statut : 'incompatible' | 'alerte AMF' | 'prudence' | 'à vérifier' | 'éligible'."""
    reasons = []
    if b.get("metatrader5") is False:
        reasons.append("Pas de MetaTrader 5")
    if b.get("robots_ea_autorises") is False:
        reasons.append("Robots/EA non autorisés")
    if reasons:
        return "incompatible", reasons
    if b.get("liste_noire_amf"):
        return "alerte AMF", ["Signalé sur la liste noire de l'AMF : démo uniquement"]
    if not b.get("entite_ue"):
        return "prudence", ["Pas d'entité régulée dans l'UE identifiée"]
    if b.get("statut") != "verifie":
        return "à vérifier", ["Informations à confirmer sur les sources officielles"]
    return "éligible", []


def comparison_table(data: dict | None = None) -> pd.DataFrame:
    data = data or load_brokers()
    rows = []
    for b in data["brokers"]:
        status, why = eligibility(b)
        rows.append({
            "Broker": b["nom"], "Entité UE": b.get("entite_ue") or "—", "Régulateur": b.get("regulateur"),
            "Licence": b.get("licence") or "—", "MT5": _yn(b.get("metatrader5")),
            "Robots": _yn(b.get("robots_ea_autorises")), "Scalping": _yn(b.get("scalping_autorise")),
            "Fonds de garantie": b.get("fonds_garantie") or "—",
            "Dépôt min (€)": _na(b.get("depot_minimum_eur")),
            "Spread XAUUSD (pts)": _na(b.get("spread_xauusd_points")),
            "Spread EURUSD (pts)": _na(b.get("spread_eurusd_points")),
            "Commission A/R (€/lot)": _na(b.get("commission_lot_aller_retour_eur")),
            "Lot min": b.get("lot_minimum"), "Statut": status, "Remarques": "; ".join(why + [b.get("alerte", "")]).strip("; "),
        })
    return pd.DataFrame(rows)


def _yn(v) -> str:
    return {True: "Oui", False: "Non"}.get(v, "À vérifier")


def _na(v) -> str:
    return "À relever" if v is None else str(v)


@dataclass
class SpreadMeasure:
    symbol: str
    samples: int
    median_points: float
    max_points: float


def measure_spreads(client, symbols: list[str], samples: int = 30, interval_s: float = 1.0) -> list[SpreadMeasure]:
    """Mesure le spread réel sur le compte MT5 connecté (démo conseillé)."""
    out = []
    specs = {s: client.symbol_spec(s) for s in symbols}
    values: dict[str, list[float]] = {s: [] for s in symbols}
    for _ in range(samples):
        for s in symbols:
            try:
                values[s].append(client.spread_points(s, specs[s]))
            except Exception:
                pass
        time.sleep(interval_s)
    for s, v in values.items():
        if v:
            out.append(SpreadMeasure(s, len(v), statistics.median(v), max(v)))
    return out


def trade_cost_eur(spec, spread_points: float, commission_per_lot_rt: float, lots: float | None = None) -> float:
    lots = lots or spec.volume_min
    return spec.money_for_distance(spread_points * spec.point, lots) + commission_per_lot_rt * lots


def broker_alert(name: str, data: dict | None = None) -> str | None:
    """Alerte réglementaire du broker configuré (None si aucune)."""
    data = data or load_brokers()
    for b in data["brokers"]:
        if b["nom"].lower() == str(name).lower() and (b.get("liste_noire_amf") or not b.get("entite_ue")):
            return b.get("alerte") or "Pas d'entité régulée dans l'UE identifiée."
    return None
