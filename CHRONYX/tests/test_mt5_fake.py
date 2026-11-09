"""Tests du client MT5 et de l'exécuteur avec un FAUX module MetaTrader5.

Ils vérifient la logique de CHRONYX (verrous, anti-doublon, SL/TP envoyés,
conversion des spécifications). Ils ne remplacent pas un essai réel en démo.
"""
import time
from collections import namedtuple
from types import SimpleNamespace

import numpy as np
import pytest

from chronyx.data import mt5_client
from chronyx.data.storage import Storage
from chronyx.execution import executor
from chronyx.execution.modes import Mode, order_gate
from chronyx.risk.position_sizing import plan_trade

Acc = namedtuple("Acc", "login server trade_mode currency balance equity leverage")
SymInfo = namedtuple("SymInfo", "digits point trade_contract_size volume_min volume_step volume_max trade_tick_size "
                                "trade_tick_value currency_base currency_profit trade_stops_level filling_mode")
Tick = namedtuple("Tick", "time bid ask")
Res = namedtuple("Res", "retcode order price comment")


class FakeMT5(SimpleNamespace):
    ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_REAL = 0, 2
    TRADE_ACTION_DEAL, ORDER_TYPE_BUY, ORDER_TYPE_SELL = 1, 0, 1
    ORDER_TIME_GTC, ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 0, 1, 2
    TRADE_RETCODE_DONE = 10009
    TIMEFRAME_M5 = 5

    def __init__(self, demo=True):
        super().__init__(sent=[], demo=demo)

    def initialize(self, **kw): return True
    def shutdown(self): pass
    def last_error(self): return (0, "ok")
    def account_info(self): return Acc(1, "Broker-Demo", 0 if self.demo else 2, "EUR", 500.0, 500.0, 30)
    def terminal_info(self): return SimpleNamespace(connected=True, trade_allowed=True)
    def symbol_select(self, s, v): return True
    def symbol_info(self, s): return SymInfo(5, 1e-5, 100000, 0.01, 0.01, 50, 1e-5, 0.92, "EUR", "USD", 10, 1)
    def symbol_info_tick(self, s): return Tick(int(time.time()) + 2 * 3600, 1.08000, 1.08008)  # serveur UTC+2
    def order_check(self, r): return SimpleNamespace(retcode=0, comment="ok")
    def order_send(self, r):
        self.sent.append(r)
        return Res(self.TRADE_RETCODE_DONE, 42, r["price"], "done")

    def copy_rates_from_pos(self, s, tf, start, n):
        dt = np.dtype([("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"),
                       ("tick_volume", "i8"), ("spread", "i4"), ("real_volume", "i8")])
        arr = np.zeros(n, dtype=dt)
        arr["time"] = 1_700_000_000 + np.arange(n) * 300
        arr["open"] = arr["close"] = 1.08
        arr["high"], arr["low"] = 1.0802, 1.0798
        return arr


@pytest.fixture
def fake(monkeypatch):
    def _make(demo=True):
        f = FakeMT5(demo)
        monkeypatch.setattr(mt5_client, "mt5", f)
        c = mt5_client.MT5Client()
        c.connect()
        return f, c
    return _make


def test_spec_and_rates_from_mt5(fake):
    _, c = fake()
    spec = c.symbol_spec("EURUSD")
    assert spec.source == "mt5" and spec.stops_level_points == 10
    assert spec.pip_value(1.0) == pytest.approx(9.2)
    df = c.rates("EURUSD", "M5", 10)
    assert len(df) == 10 and str(df["time"].dt.tz) == "UTC"
    assert c.spread_points("EURUSD", spec) == pytest.approx(8.0)


def _plan(c):
    return plan_trade(c.symbol_spec("EURUSD"), "BUY", 500, 1.0, 1.08008, 0.0010, 1.5, 8, max_margin_pct=100)


def test_demo_order_sent_with_sl_tp_and_no_duplicate(fake, tmp_path):
    f, c = fake(demo=True)
    st = Storage(tmp_path / "db.sqlite")
    gate = order_gate(Mode.DEMO_AUTO, c.is_demo(), False)
    executor.send_market_order(_plan(c), c, st, "EURUSD|A|t1", gate)
    req = f.sent[0]
    assert req["sl"] < req["price"] < req["tp"] and req["magic"] == executor.MAGIC
    with pytest.raises(executor.OrderRefused, match="doublon"):
        executor.send_market_order(_plan(c), c, st, "EURUSD|A|t1", gate)
    assert len(f.sent) == 1


def test_real_account_blocked_even_with_manual_validation(fake, tmp_path):
    f, c = fake(demo=False)
    st = Storage(tmp_path / "db.sqlite")
    gate = order_gate(Mode.REEL, c.is_demo(), False)          # pas activé, pas confirmé
    with pytest.raises(executor.OrderRefused, match="Compte réel"):
        executor.send_market_order(_plan(c), c, st, "EURUSD|A|t2", gate, manual_validation=True)
    assert f.sent == []


def test_demo_mode_on_real_account_blocked(fake, tmp_path):
    f, c = fake(demo=False)
    gate = order_gate(Mode.DEMO_AUTO, c.is_demo(), False)
    with pytest.raises(executor.OrderRefused):
        executor.send_market_order(_plan(c), c, Storage(tmp_path / "db.sqlite"), "x", gate)
    assert f.sent == []


def test_refused_plan_never_sent(fake, tmp_path):
    f, c = fake()
    bad = plan_trade(c.symbol_spec("EURUSD"), "BUY", 20, 0.25, 1.08, 0.0010, 1.5, 8)
    assert not bad.accepted
    with pytest.raises(executor.OrderRefused, match="gestion du risque"):
        executor.send_market_order(bad, c, Storage(tmp_path / "db.sqlite"), "y", order_gate(Mode.DEMO_AUTO, True, False))
    assert f.sent == []


def test_server_time_converted_to_utc(fake):
    _, c = fake()
    assert c.server_utc_offset_seconds() == 2 * 3600
    df = c.rates("EURUSD", "M5", 3)
    assert df["time"].iloc[0].timestamp() == 1_700_000_000 - 2 * 3600
    assert abs(c.tick("EURUSD")["time"].timestamp() - time.time()) < 5


def test_symbol_suffix_autodetected(monkeypatch):
    f = FakeMT5()
    names = {"XAUUSD+", "XAUUSD+.x", "EURUSD"}
    base_info = FakeMT5.symbol_info
    f.symbol_info = lambda s: base_info(f, s) if s in names else None
    f.symbols_get = lambda pattern: [SimpleNamespace(name=n, trade_mode=4) for n in sorted(names)
                                     if n.startswith(pattern.rstrip("*"))]
    monkeypatch.setattr(mt5_client, "mt5", f)
    c = mt5_client.MT5Client()
    c.connect()
    assert c.broker_symbol("XAUUSD") == "XAUUSD+"      # variante la plus courte
    assert c.broker_symbol("EURUSD") == "EURUSD"       # nom standard existant
    assert c.symbol_spec("XAUUSD").name == "XAUUSD"    # le robot garde le nom standard
