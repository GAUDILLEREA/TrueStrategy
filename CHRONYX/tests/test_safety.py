import json
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from chronyx.brokers.comparison import comparison_table, eligibility, load_brokers
from chronyx.config import load_config
from chronyx.data.storage import Storage
from chronyx.engine.pipeline import analyze, default_account_state
from chronyx.engine.sources import SimulatedSource
from chronyx.execution.modes import (CONFIRMATION_PHRASE, Mode, order_gate, risk_fingerprint,
                                     write_real_confirmation)
from chronyx.news.calendar import load_calendar, news_block, news_mask
from chronyx.news.importer import parse_ff_json

NOW = datetime(2026, 11, 4, 13, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- calendrier
def write_cal(path, rows):
    pd.DataFrame(rows, columns=["datetime_utc", "currency", "impact", "event"]).to_csv(path, index=False)


def test_missing_calendar_blocks_trading(tmp_path):
    st = load_calendar(tmp_path / "absent.csv", now=NOW)
    assert not st.usable
    assert news_block(st, "XAUUSD", NOW)


def test_stale_calendar_blocks_trading(tmp_path):
    p = tmp_path / "cal.csv"
    write_cal(p, [("2026-11-10 13:30", "USD", "high", "CPI")])
    old = time.time() - 3 * 86400
    os.utime(p, (old, old))
    assert not load_calendar(p, max_age_hours=24).usable


def test_news_window(tmp_path):
    p = tmp_path / "cal.csv"
    write_cal(p, [("2026-11-04 13:10", "USD", "high", "CPI"), ("2026-11-04 13:05", "JPY", "low", "Divers"),
                  ("2026-11-20 13:30", "EUR", "high", "BCE")])
    st = load_calendar(p, now=NOW)
    assert st.usable
    assert news_block(st, "XAUUSD", NOW)              # CPI dans 10 min -> bloqué
    assert not news_block(st, "XAUUSD", NOW, minutes_before=5)
    assert not news_block(st, "EURJPY", NOW)          # JPY impact faible, EUR loin
    mask = news_mask(pd.Series(pd.date_range("2026-11-04 12:50", periods=6, freq="10min", tz="UTC")), st.events,
                     "EURUSD", 15, 15)
    assert mask.tolist() == [False, True, True, True, False, False]


def test_importer_parses_feed():
    items = [{"title": "CPI m/m", "country": "USD", "date": "2026-11-12T08:30:00-05:00", "impact": "High"},
             {"title": "Bank Holiday", "country": "JPY", "date": "2026-11-12T00:00:00-05:00", "impact": "Holiday"}]
    df = parse_ff_json(items)
    assert len(df) == 1 and df.iloc[0].datetime_utc == "2026-11-12 13:30" and df.iloc[0].impact == "high"


# ---------------------------------------------------------------- modes et verrou du réel
def test_analysis_and_assistance_never_send_orders():
    assert not order_gate(Mode.ANALYSE, True, True).allowed
    assert not order_gate(Mode.ASSISTANCE, True, True).allowed


def test_demo_mode_refuses_real_account():
    assert order_gate(Mode.DEMO_AUTO, True, False).allowed
    assert not order_gate(Mode.DEMO_AUTO, False, False).allowed
    assert not order_gate(Mode.DEMO_AUTO, None, False).allowed


def test_real_mode_requires_all_confirmations(tmp_path):
    f = tmp_path / "conf.json"
    fp = risk_fingerprint(123, {"risque_par_trade_pct": 0.5}, ["trend_scalping"])
    assert not order_gate(Mode.REEL, False, True, fp, f).allowed                  # pas de confirmation
    assert not write_real_confirmation("oui", fp, f)                              # mauvaise phrase
    assert write_real_confirmation(CONFIRMATION_PHRASE, fp, f)
    assert not order_gate(Mode.REEL, False, False, fp, f).allowed                 # config désactivée
    assert order_gate(Mode.REEL, False, True, fp, f).allowed
    other = risk_fingerprint(123, {"risque_par_trade_pct": 2.0}, ["trend_scalping"])
    assert not order_gate(Mode.REEL, False, True, other, f).allowed               # paramètres changés
    assert not order_gate(Mode.REEL, False, True, fp, f, now=datetime.now(timezone.utc) + timedelta(days=2)).allowed
    assert not order_gate(Mode.REEL, True, True, fp, f).allowed                   # compte démo


# ---------------------------------------------------------------- journal / anti-doublon
def test_duplicate_order_blocked(tmp_path):
    s = Storage(tmp_path / "db.sqlite")
    assert s.register_order("XAUUSD|A|t1", symbol="XAUUSD", direction="BUY", lots=0.01)
    assert not s.register_order("XAUUSD|A|t1", symbol="XAUUSD", direction="BUY", lots=0.01)
    s.log_event("INFO", "test", "ok", {"a": 1})
    assert len(s.read("events")) == 1


# ---------------------------------------------------------------- brokers
def test_broker_eligibility():
    data = load_brokers()
    status = {b["nom"]: eligibility(b)[0] for b in data["brokers"]}
    assert status["XTB"] == "incompatible"          # pas de MT5
    assert status["Vantage"] == "prudence"          # pas d'entité UE identifiée
    assert all(s != "éligible" for s in status.values())  # rien n'est marqué vérifié sans vérification
    assert len(comparison_table(data)) == len(data["brokers"])


# ---------------------------------------------------------------- pipeline complet
def test_pipeline_without_calendar_never_trades(tmp_path):
    cfg = load_config()
    src = SimulatedSource(cfg)
    cal = load_calendar(tmp_path / "absent.csv", now=NOW)
    for sym in cfg.active_symbols:
        a = analyze(cfg, src, sym, cal, default_account_state(src.account()), NOW)
        assert not a.tradable
        assert any("Calendrier" in r for r in a.no_trade_reasons())
        assert a.decision == "PAS DE TRADE"


# ---------------------------------------------------------------- moteur autonome
def test_engine_cycle_simulation_and_kill_switch(tmp_path):
    from chronyx.engine.bot import AccountTracker, run_cycle
    from chronyx.risk import guards
    cfg = load_config()
    src = SimulatedSource(cfg)
    st = Storage(tmp_path / "db.sqlite")
    tracker = AccountTracker(tmp_path / "etat.json")
    res = run_cycle(cfg, src, st, tracker, NOW)
    assert len(res) == len(cfg.active_symbols)
    assert len(st.read("signals")) == len(cfg.active_symbols)        # chaque décision est journalisée
    guards.activate_kill_switch("test")
    assert run_cycle(cfg, src, st, tracker, NOW) == []


def test_engine_drawdown_triggers_global_stop(tmp_path):
    from chronyx.engine.bot import AccountTracker, run_cycle
    from chronyx.risk import guards
    cfg = load_config()
    src = SimulatedSource(cfg)
    tracker = AccountTracker(tmp_path / "etat.json")
    tracker.data = {"peak": 1000.0}                                   # equity 300 vs pic 1000 => drawdown 70 %
    run_cycle(cfg, src, Storage(tmp_path / "db.sqlite"), tracker, NOW)
    assert guards.kill_switch_active()
