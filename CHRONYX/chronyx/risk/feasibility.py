"""Faisabilité du scalping selon le capital, l'instrument et les frais.

Pour chaque instrument et timeframe, on estime un stop « typique » (ATR x
multiplicateur), puis on calcule :
  - le risque minimum imposé par le lot minimum ;
  - la part du spread + commission dans le stop (coût structurel).
Le verdict est volontairement prudent.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..data.symbol_spec import SymbolSpec, esma_retail_leverage, margin_required


@dataclass
class Feasibility:
    symbol: str
    timeframe: str
    capital: float
    typical_sl_distance: float
    min_lot_risk_eur: float
    min_lot_risk_pct: float
    cost_pct_of_stop: float
    verdict: str            # "viable" | "limite" | "non viable"
    min_lot_margin_eur: float = 0.0
    recommendations: list[str] = field(default_factory=list)


def assess(spec: SymbolSpec, timeframe: str, capital: float, atr_value: float, spread_points: float,
           commission_per_lot_rt: float, risk_pct_limit: float, sl_atr_mult: float = 1.5,
           price: float | None = None, max_margin_pct: float = 50.0, leverage: float | None = None,
           margin_min_lot_eur: float | None = None) -> Feasibility:
    sl = atr_value * sl_atr_mult
    spread_price = spread_points * spec.point
    loss_min_lot = (spec.money_for_distance(sl, spec.volume_min) + spec.money_for_distance(spread_price, spec.volume_min)
                    + commission_per_lot_rt * spec.volume_min)
    risk_pct = loss_min_lot / capital * 100
    cost_eur_per_lot = spec.money_for_distance(spread_price, 1) + commission_per_lot_rt
    cost_pct = cost_eur_per_lot / spec.money_for_distance(sl, 1) * 100 if sl > 0 else float("inf")

    if margin_min_lot_eur is not None:
        margin = margin_min_lot_eur
    elif price is not None:
        margin = margin_required(spec, spec.volume_min, price, leverage or esma_retail_leverage(spec.name))
    else:
        margin = 0.0

    recs: list[str] = []
    if margin and margin / capital * 100 > max_margin_pct:
        verdict = "non viable"
        recs.append(f"Le lot minimum immobilise {margin:.0f} € de marge ({margin / capital * 100:.0f} % du capital, "
                    f"max {max_margin_pct:.0f} %) : capital insuffisant pour cet instrument.")
        recs.append("Rester en compte démo ou choisir un instrument moins exigeant en marge.")
    elif risk_pct > risk_pct_limit:
        verdict = "non viable"
        recs.append(f"Le lot minimum ({spec.volume_min}) fait risquer {loss_min_lot:.2f} € ({risk_pct:.2f} %) "
                    f"par trade, au-delà de votre limite de {risk_pct_limit} %.")
        recs.append("Utiliser un timeframe plus lent n'aide pas ici (stop plus large => risque plus grand) : "
                    "privilégier un instrument au lot minimum moins coûteux ou augmenter le capital.")
    elif cost_pct > 25:
        verdict = "non viable"
        recs.append(f"Les frais représentent {cost_pct:.0f} % du stop : le scalping est structurellement perdant.")
        recs.append("Passer sur un timeframe moins rapide (M15) ou une stratégie avec des objectifs plus larges.")
    elif cost_pct > 12 or risk_pct > risk_pct_limit * 0.8:
        verdict = "limite"
        recs.append(f"Frais = {cost_pct:.0f} % du stop, risque minimum {risk_pct:.2f} % : marge de manœuvre faible.")
        recs.append("Tester d'abord en compte démo et comparer les spreads réels de plusieurs brokers.")
    else:
        verdict = "viable"
        recs.append("Conditions compatibles avec votre capital. Valider par backtest puis en démo avant tout réel.")
    return Feasibility(spec.name, timeframe, capital, sl, loss_min_lot, risk_pct, cost_pct, verdict,
                       min_lot_margin_eur=margin, recommendations=recs)
