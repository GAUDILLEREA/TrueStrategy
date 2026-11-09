"""Envoi des ordres vers MetaTrader 5.

Sécurités :
 - chaque ordre part AVEC son stop loss et son take profit côté serveur du
   broker : la position reste protégée même si le PC ou le robot s'arrête ;
 - identifiant unique par signal (anti-doublon, stocké en SQLite) ;
 - vérification préalable via order_check ;
 - passage par order_gate (modes / verrou du réel) avant tout envoi automatique.
"""
from __future__ import annotations

import logging

from ..data import mt5_client
from ..data.storage import Storage
from ..risk.position_sizing import TradePlan
from .modes import GateDecision

log = logging.getLogger(__name__)

MAGIC = 770077
MAX_DEVIATION_POINTS = 20


class OrderRefused(RuntimeError):
    pass


def client_order_id(symbol: str, strategy: str, bar_time) -> str:
    return f"{symbol}|{strategy}|{bar_time}"


def send_market_order(plan: TradePlan, client: mt5_client.MT5Client, storage: Storage, client_id: str,
                      gate: GateDecision, manual_validation: bool = False) -> dict:
    """Envoie un ordre au marché. `manual_validation=True` = mode assistance, l'utilisateur a cliqué."""
    if not plan.accepted:
        raise OrderRefused("Plan refusé par la gestion du risque : " + " | ".join(plan.reasons))
    mt5 = mt5_client.mt5
    if mt5 is None or not client.connected:
        raise OrderRefused("MetaTrader 5 non connecté.")
    account_type = "demo" if client.is_demo() else "reel"
    # Sur un compte RÉEL, le verrou du réel s'applique TOUJOURS, même avec validation manuelle.
    if account_type == "reel" and not gate.allowed:
        raise OrderRefused("Compte réel : " + " | ".join(gate.reasons))
    if not gate.allowed and not manual_validation:
        raise OrderRefused(" | ".join(gate.reasons))
    if not storage.register_order(client_id, symbol=plan.symbol, direction=plan.direction, lots=plan.lots,
                                  entry=plan.entry, sl=plan.stop_loss, tp=plan.take_profit, status="en_cours",
                                  account_type=account_type):
        raise OrderRefused(f"Ordre déjà envoyé pour ce signal ({client_id}) : doublon bloqué.")

    symbol = client.broker_symbol(plan.symbol)
    tick = mt5.symbol_info_tick(symbol)
    is_buy = plan.direction == "BUY"
    request = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(plan.lots),
        "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
        "price": tick.ask if is_buy else tick.bid,
        "sl": float(plan.stop_loss), "tp": float(plan.take_profit),
        "deviation": MAX_DEVIATION_POINTS, "magic": MAGIC, "comment": "CHRONYX",
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": _filling_mode(symbol),
    }
    check = mt5.order_check(request)
    if check is None or check.retcode != 0:
        storage.update_order(client_id, status="refuse_check", comment=str(getattr(check, "comment", check)))
        raise OrderRefused(f"Vérification MT5 refusée : {getattr(check, 'comment', mt5.last_error())}")
    res = mt5.order_send(request)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        storage.update_order(client_id, status="echec", comment=str(getattr(res, "comment", mt5.last_error())))
        raise OrderRefused(f"Ordre rejeté par le broker : {getattr(res, 'comment', mt5.last_error())}")
    storage.update_order(client_id, status="execute", broker_ticket=str(res.order))
    storage.log_event("INFO", "ordre", f"{plan.direction} {plan.lots} {plan.symbol} exécuté ({account_type})",
                      {"ticket": res.order, "price": res.price})
    log.info("Ordre exécuté : %s %s %s @ %s (compte %s)", plan.direction, plan.lots, plan.symbol, res.price, account_type)
    return res._asdict()


def _filling_mode(symbol: str):
    mt5 = mt5_client.mt5
    info = mt5.symbol_info(symbol)
    modes = info.filling_mode if info else 0
    if modes & 1:
        return mt5.ORDER_FILLING_FOK
    if modes & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def close_all_positions(client: mt5_client.MT5Client, storage: Storage, only_chronyx: bool = True) -> int:
    """STOP GLOBAL : ferme les positions ouvertes par CHRONYX (ou toutes)."""
    mt5 = mt5_client.mt5
    if mt5 is None or not client.connected:
        return 0
    closed = 0
    for p in mt5.positions_get() or []:
        if only_chronyx and p.magic != MAGIC:
            continue
        tick = mt5.symbol_info_tick(p.symbol)
        is_buy = p.type == mt5.POSITION_TYPE_BUY
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume, "position": p.ticket,
               "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
               "price": tick.bid if is_buy else tick.ask, "deviation": MAX_DEVIATION_POINTS, "magic": MAGIC,
               "comment": "CHRONYX STOP", "type_time": mt5.ORDER_TIME_GTC, "type_filling": _filling_mode(p.symbol)}
        res = mt5.order_send(req)
        if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
            closed += 1
        else:
            storage.log_event("ERROR", "stop_global", f"Échec de fermeture de la position {p.ticket}",
                              {"retour": getattr(res, "comment", None)})
    storage.log_event("WARNING", "stop_global", f"{closed} position(s) fermée(s) par STOP GLOBAL")
    return closed
