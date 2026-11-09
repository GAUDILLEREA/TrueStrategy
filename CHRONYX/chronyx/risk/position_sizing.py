"""Calcul de la taille de position et du plan de trade complet.

Principe : on part du risque maximum accepté (en € et en %), on en déduit le
nombre de lots, arrondi VERS LE BAS. Si le lot minimum du broker dépasse ce
risque, le trade est REFUSÉ — jamais « arrondi au minimum ».

La taille de position ne dépend QUE du capital actuel et du % de risque
configuré : aucune augmentation après une perte (pas de martingale).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from ..data.symbol_spec import SymbolSpec, esma_retail_leverage, margin_required

ESMA_STOP_OUT_LEVEL = 0.5   # clôture forcée à 50 % de niveau de marge (règle ESMA clients particuliers)


@dataclass
class TradePlan:
    accepted: bool
    symbol: str
    direction: str
    lots: float = 0.0
    entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_target_eur: float = 0.0       # risque visé
    risk_eur: float = 0.0              # risque réel au SL (mouvement + spread + commission)
    risk_pct: float = 0.0
    min_lot_risk_eur: float = 0.0      # risque si on prenait le lot minimum
    min_lot_risk_pct: float = 0.0
    sl_move_eur: float = 0.0           # perte liée au seul mouvement de prix
    spread_cost_eur: float = 0.0
    commission_eur: float = 0.0
    profit_potential_eur: float = 0.0  # gain net au TP (frais déduits)
    rr_nominal: float = 0.0
    rr_net: float = 0.0                # ratio après frais
    pip_value_eur: float = 0.0         # valeur d'un pip pour la taille calculée
    point_value_eur: float = 0.0
    margin_eur: float = 0.0
    margin_pct_of_balance: float = 0.0
    liquidation_distance: float = 0.0  # mouvement de prix adverse jusqu'au stop-out (si pas de SL)
    reasons: list[str] = field(default_factory=list)   # raisons de refus
    reason_codes: list[str] = field(default_factory=list)  # codes courts : lot_min, spread, stops, marge
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def plan_trade(spec: SymbolSpec, direction: str, balance: float, risk_pct: float, entry: float,
               sl_distance: float, rr: float, spread_points: float, commission_per_lot_rt: float = 0.0,
               leverage: float | None = None, max_spread_pct_of_stop: float = 15.0,
               max_margin_pct: float = 50.0, rates_to_eur: dict | None = None,
               margin_override_per_lot: float | None = None) -> TradePlan:
    """Construit le plan de trade et vérifie toutes les contraintes de risque.

    entry : prix d'entrée estimé (ask pour un achat, bid pour une vente).
    sl_distance : distance du stop en prix. spread_points : spread en points du broker.
    """
    if direction not in ("BUY", "SELL"):
        raise ValueError("direction doit être BUY ou SELL")
    plan = TradePlan(accepted=False, symbol=spec.name, direction=direction, entry=entry, rr_nominal=rr)
    reasons = plan.reasons

    if balance <= 0:
        reasons.append("Capital nul ou négatif.")
        return plan
    if sl_distance <= 0:
        reasons.append("Distance de stop loss invalide.")
        return plan

    sign = 1 if direction == "BUY" else -1
    plan.stop_loss = round(entry - sign * sl_distance, spec.digits)
    plan.take_profit = round(entry + sign * sl_distance * rr, spec.digits)
    plan.risk_target_eur = balance * risk_pct / 100

    spread_price = spread_points * spec.point
    # Coût pour 1 lot : mouvement jusqu'au SL + spread (payé à la sortie sur un graphique bid) + commission
    loss_per_lot = spec.money_for_distance(sl_distance, 1) + spec.money_for_distance(spread_price, 1) \
        + commission_per_lot_rt

    # Lot minimum : risque incompressible imposé par le broker
    plan.min_lot_risk_eur = loss_per_lot * spec.volume_min
    plan.min_lot_risk_pct = plan.min_lot_risk_eur / balance * 100

    lots = spec.normalize_volume(plan.risk_target_eur / loss_per_lot)
    if lots < spec.volume_min:
        reasons.append(
            f"Lot minimum ({spec.volume_min}) => risque de {plan.min_lot_risk_eur:.2f} € "
            f"({plan.min_lot_risk_pct:.2f} % du capital), supérieur à la limite de "
            f"{plan.risk_target_eur:.2f} € ({risk_pct:.2f} %). Trade refusé.")
        plan.reason_codes.append("lot_min")
        lots = spec.volume_min  # uniquement pour afficher les chiffres ; le trade reste refusé
    plan.lots = lots

    plan.sl_move_eur = spec.money_for_distance(sl_distance, lots)
    plan.spread_cost_eur = spec.money_for_distance(spread_price, lots)
    plan.commission_eur = commission_per_lot_rt * lots
    plan.risk_eur = plan.sl_move_eur + plan.spread_cost_eur + plan.commission_eur
    plan.risk_pct = plan.risk_eur / balance * 100
    plan.profit_potential_eur = spec.money_for_distance(sl_distance * rr, lots) - plan.spread_cost_eur \
        - plan.commission_eur
    plan.rr_net = plan.profit_potential_eur / plan.risk_eur if plan.risk_eur else 0.0
    plan.pip_value_eur = spec.pip_value(lots)
    plan.point_value_eur = spec.money_for_distance(spec.point, lots)

    # Spread trop large par rapport au stop : le scalping devient structurellement perdant
    spread_pct = spread_price / sl_distance * 100
    if spread_pct > max_spread_pct_of_stop:
        reasons.append(f"Spread = {spread_pct:.1f} % de la distance du stop (max {max_spread_pct_of_stop:.0f} %).")
        plan.reason_codes.append("spread")
    if plan.rr_net < 1.0:
        plan.notes.append(f"Après frais, le ratio gain/risque n'est que de {plan.rr_net:.2f}.")

    # Distance minimale imposée par le broker
    if spec.stops_level_points and sl_distance < spec.stops_level_points * spec.point:
        reasons.append(f"Stop trop proche : le broker impose au moins {spec.stops_level_points} points.")
        plan.reason_codes.append("stops")

    # Marge
    if leverage is None:
        leverage = esma_retail_leverage(spec.name)
    if margin_override_per_lot is not None:
        plan.margin_eur = margin_override_per_lot * lots
    else:
        plan.margin_eur = margin_required(spec, lots, entry, leverage, rates_to_eur)
    plan.margin_pct_of_balance = plan.margin_eur / balance * 100
    if plan.margin_pct_of_balance > max_margin_pct:
        reasons.append(f"Marge requise {plan.margin_eur:.2f} € = {plan.margin_pct_of_balance:.0f} % du capital "
                       f"(max {max_margin_pct:.0f} %).")
        plan.reason_codes.append("marge")

    # Liquidation : mouvement adverse avant stop-out à 50 % de marge (si le SL ne s'exécutait pas)
    vppu = spec.value_per_price_unit(lots)
    if vppu > 0:
        plan.liquidation_distance = max(0.0, (balance - ESMA_STOP_OUT_LEVEL * plan.margin_eur) / vppu)
        if plan.liquidation_distance < sl_distance * 3:
            plan.notes.append("Attention : la liquidation est proche (< 3x la distance du stop) en cas de gap.")

    plan.accepted = not reasons
    return plan
