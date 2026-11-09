"""Moteur autonome CHRONYX (fonctionne SANS le dashboard).

    python -m chronyx.engine.bot              # se connecte à MT5
    python -m chronyx.engine.bot --simulation # données fictives, aucun ordre
    python -m chronyx.engine.bot --once       # un seul cycle (test)

Protections appliquées à chaque cycle :
 - STOP GLOBAL (fichier data/STOP_GLOBAL) : ferme les positions CHRONYX et bloque tout ;
 - drawdown max : active automatiquement le STOP GLOBAL ;
 - perte de connexion MT5 : aucun nouvel ordre, tentative de reconnexion ;
 - erreurs critiques répétées : arrêt du robot ;
 - les positions ont toujours un SL/TP côté broker (protégées même si le PC s'éteint).
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone

from ..config import ROOT, load_config
from ..data.storage import Storage
from ..execution.executor import MAGIC, OrderRefused, client_order_id, close_all_positions, send_market_order
from ..execution.modes import Mode, order_gate, risk_fingerprint
from ..logging_setup import setup_logging
from ..news.calendar import load_calendar
from ..risk.guards import AccountState, RiskGuard, activate_kill_switch, kill_switch_active
from .pipeline import analyze
from .sources import MT5Source, make_source

log = logging.getLogger("chronyx.bot")
STATE_FILE = ROOT / "data" / "etat_compte.json"
MAX_CONSECUTIVE_ERRORS = 5


class AccountTracker:
    """Mémorise le solde de début de jour/semaine et le plus haut d'equity (persisté sur disque)."""

    def __init__(self, path=STATE_FILE) -> None:
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def update(self, balance: float, equity: float, now: datetime) -> AccountState:
        day, week = now.date().isoformat(), f"{now.isocalendar().year}-{now.isocalendar().week}"
        d = self.data
        if d.get("day") != day:
            d.update(day=day, start_day=balance, trades_today=0)
        if d.get("week") != week:
            d.update(week=week, start_week=balance)
        d["peak"] = max(float(d.get("peak", equity)), equity)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(d, default=str), encoding="utf-8")
        last_loss = datetime.fromisoformat(d["last_loss"]) if d.get("last_loss") else None
        return AccountState(balance=balance, equity=equity, start_of_day_balance=d["start_day"],
                            start_of_week_balance=d["start_week"], peak_equity=d["peak"],
                            trades_today=int(d.get("trades_today", 0)), last_loss_time=last_loss)

    def record_trade(self) -> None:
        self.data["trades_today"] = int(self.data.get("trades_today", 0)) + 1
        self.path.write_text(json.dumps(self.data, default=str), encoding="utf-8")

    def record_loss(self, when: datetime) -> None:
        self.data["last_loss"] = when.isoformat()
        self.path.write_text(json.dumps(self.data, default=str), encoding="utf-8")


def _refresh_positions(source, state: AccountState) -> None:
    if isinstance(source, MT5Source):
        pos = [p for p in source.client.positions() if p.get("magic") == MAGIC]
        state.open_positions = len(pos)
        reverse = {v: k for k, v in source.client._symbol_map.items()}
        suffix = source.client.suffix
        state.open_symbols = {reverse.get(p["symbol"], p["symbol"][: len(p["symbol"]) - len(suffix)] if suffix
                                         else p["symbol"]) for p in pos}


def _check_recent_losses(source, tracker: AccountTracker, now: datetime) -> None:
    """Détecte la dernière perte (historique MT5 du jour) pour la pause après perte."""
    if not isinstance(source, MT5Source):
        return
    from ..data import mt5_client
    mt5 = mt5_client.mt5
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(start, now) or []
    losses = [d for d in deals if d.magic == MAGIC and d.entry == mt5.DEAL_ENTRY_OUT and d.profit < 0]
    if losses:
        tracker.record_loss(datetime.fromtimestamp(max(d.time for d in losses), tz=timezone.utc))


def run_cycle(cfg, source, storage: Storage, tracker: AccountTracker, now: datetime | None = None) -> list:
    now = now or datetime.now(timezone.utc)
    mode = Mode(cfg.mode)
    acc = source.account()
    _check_recent_losses(source, tracker, now)
    state = tracker.update(float(acc["balance"]), float(acc["equity"]), now)
    _refresh_positions(source, state)
    guard = RiskGuard(cfg.risk, cfg.get("horaires"))

    # Coupe-circuit drawdown : arrêt global automatique
    if guard.hard_stop_reached(state) and not kill_switch_active():
        activate_kill_switch("Drawdown maximal atteint")
        storage.log_event("CRITICAL", "securite", "Drawdown maximal atteint : STOP GLOBAL activé.")
    if kill_switch_active():
        if isinstance(source, MT5Source):
            close_all_positions(source.client, storage)
        log.warning("STOP GLOBAL actif : aucune action de trading.")
        return []

    cal_cfg = cfg.get("calendrier", default={}) or {}
    calendar = load_calendar(cfg.path_for(cal_cfg.get("fichier", "data/calendrier.csv")),
                             float(cal_cfg.get("age_max_heures", 24)), now)
    results = []
    for symbol in cfg.active_symbols:
        a = analyze(cfg, source, symbol, calendar, state, now)
        results.append(a)
        sig = a.signal
        storage.log_signal(symbol, sig.strategy, sig.direction or "AUCUN", sig.entry, sig.stop_loss, sig.take_profit,
                           a.tradable, a.no_trade_reasons(), mode.value)
        if not a.tradable:
            log.info("%s : PAS DE TRADE - %s", symbol, " | ".join(a.no_trade_reasons()[:3]))
            continue
        log.info("%s : signal %s (%s), lots=%.2f, risque=%.2f €", symbol, sig.direction, sig.strategy,
                 a.plan.lots, a.plan.risk_eur)
        if not mode.sends_orders_automatically:
            continue  # analyse / assistance : l'utilisateur décide dans le dashboard
        fp = risk_fingerprint(acc.get("login"), cfg.risk, [n for n, s in (cfg.get("strategies") or {}).items()
                                                            if s.get("actif")])
        gate = order_gate(mode, source.is_demo(), bool(cfg.get("reel", "active", default=False)), fp)
        if not gate.allowed:
            storage.log_event("WARNING", "verrou", f"Ordre {symbol} bloqué", {"raisons": gate.reasons})
            log.warning("Ordre bloqué : %s", " | ".join(gate.reasons))
            continue
        try:
            send_market_order(a.plan, source.client, storage, client_order_id(symbol, sig.strategy, a.bar_time), gate)
            tracker.record_trade()
            state.open_positions += 1
            state.open_symbols.add(symbol)
        except OrderRefused as e:
            log.warning("Ordre refusé : %s", e)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Moteur CHRONYX")
    ap.add_argument("--simulation", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=30, help="secondes entre deux cycles")
    args = ap.parse_args(argv)

    setup_logging()
    cfg = load_config()
    for w in cfg.warnings:
        log.warning(w)
    storage = Storage(cfg.path_for(cfg.get("journal", "base_sqlite", default="data/chronyx.db")))
    source, msg = make_source(cfg, prefer_mt5=not args.simulation)
    if msg:
        log.warning(msg)
    if not source.live and Mode(cfg.mode).sends_orders_automatically:
        log.error("Mode %s impossible sans MetaTrader 5 : arrêt.", cfg.mode)
        return 2
    storage.log_event("INFO", "demarrage", f"CHRONYX démarré - {source.name} - mode {cfg.mode}")
    tracker = AccountTracker()
    errors = 0
    while True:
        try:
            if isinstance(source, MT5Source) and not source.client.is_alive():
                log.error("Connexion MT5 perdue : aucun nouvel ordre. Tentative de reconnexion...")
                storage.log_event("ERROR", "connexion", "Perte de connexion MT5")
                source.client.shutdown()
                source.client.connect()
            run_cycle(cfg, source, storage, tracker)
            errors = 0
        except KeyboardInterrupt:
            log.info("Arrêt demandé par l'utilisateur.")
            return 0
        except Exception as e:
            errors += 1
            log.exception("Erreur pendant le cycle (%d/%d) : %s", errors, MAX_CONSECUTIVE_ERRORS, e)
            storage.log_event("ERROR", "cycle", str(e))
            if errors >= MAX_CONSECUTIVE_ERRORS:
                activate_kill_switch(f"Erreurs critiques répétées : {e}")
                storage.log_event("CRITICAL", "securite", "Erreurs répétées : robot arrêté, STOP GLOBAL activé.")
                return 1
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
