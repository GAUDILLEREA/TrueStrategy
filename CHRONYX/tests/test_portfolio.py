from collections import namedtuple
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from chronyx.account import portfolio as pf
from chronyx.data import mt5_client
from chronyx.data.storage import Storage
from chronyx.data.symbol_spec import indicative_spec
from chronyx.execution import executor
from chronyx.risk import guards
from chronyx.risk.guards import AccountState, RiskGuard

from test_mt5_fake import FakeMT5

Pos = namedtuple("Pos", "ticket time type magic volume price_open sl tp price_current swap profit symbol")
Deal = namedtuple("Deal", "ticket time type entry magic position_id volume price commission swap profit fee symbol comment")
T0 = 1_762_700_000  # heure SERVEUR (UTC+2 dans le faux MT5)


class PortfolioMT5(FakeMT5):
    POSITION_TYPE_BUY = 0

    def positions_get(self, ticket=None):
        ps = [Pos(11, T0, 0, executor.MAGIC, 0.02, 1.0800, 1.0790, 1.0815, 1.0805, 0.0, 0.92, "EURUSD"),
              Pos(12, T0, 1, 0, 0.01, 1.2700, 0.0, 0.0, 1.2710, -0.1, -0.92, "GBPUSD")]
        return [p for p in ps if ticket is None or p.ticket == ticket]

    def history_deals_get(self, start, end):
        return [
            Deal(1, T0 - 7200, 2, 0, 0, 0, 0, 0, 0, 0, 500.0, 0, "", "Dépôt"),
            # position 100 : achat EURUSD gagnant
            Deal(2, T0, 0, 0, executor.MAGIC, 100, 0.02, 1.0800, -0.7, 0, 0.0, 0, "EURUSD", ""),
            Deal(3, T0 + 600, 1, 1, executor.MAGIC, 100, 0.02, 1.0815, -0.7, 0, 2.76, 0, "EURUSD", "tp"),
            # position 101 : vente XAUUSD perdante, manuelle
            Deal(4, T0 + 900, 1, 0, 0, 101, 0.01, 4000.0, 0, 0, 0.0, 0, "XAUUSD", ""),
            Deal(5, T0 + 1500, 0, 1, 0, 101, 0.01, 4003.0, 0, -0.1, -2.76, 0, "XAUUSD", "sl"),
            # position 102 encore ouverte (pas de sortie) : ignorée
            Deal(6, T0 + 2000, 0, 0, executor.MAGIC, 102, 0.01, 1.08, 0, 0, 0, 0, "EURUSD", ""),
            Deal(7, T0 + 3000, 2, 0, 0, 0, 0, 0, 0, 0, -100.0, 0, "", "Retrait"),
        ]


@pytest.fixture
def client(monkeypatch):
    f = PortfolioMT5(demo=True)
    monkeypatch.setattr(mt5_client, "mt5", f)
    c = mt5_client.MT5Client()
    c.connect()
    return c


SPECS = {"EURUSD": indicative_spec("EURUSD"), "GBPUSD": indicative_spec("GBPUSD")}


def test_open_positions(client):
    df = pf.open_positions(client, SPECS, executor.MAGIC, datetime.now(timezone.utc))
    assert list(df["symbole"]) == ["EURUSD", "GBPUSD"]
    eur = df.iloc[0]
    assert eur.sens == "ACHAT" and eur.robot
    assert eur.risque_sl_eur == pytest.approx(0.0010 * 0.02 * 100_000 * 0.92)     # 10 pips sur 0.02 lot
    assert eur.gain_tp_eur == pytest.approx(0.0015 * 0.02 * 100_000 * 0.92)
    assert eur.ouverture == pd.Timestamp(T0 - 7200, unit="s", tz="UTC")          # heure serveur -> UTC
    gbp = df.iloc[1]
    assert pd.isna(gbp.sl) and not gbp.robot                                       # sans SL, manuelle


def test_closed_trades_and_summary(client):
    t = pf.closed_trades(client, datetime(2020, 1, 1), datetime(2030, 1, 1), executor.MAGIC)
    assert list(t["position"]) == [100, 101]
    win, loss = t.iloc[0], t.iloc[1]
    assert win.sens == "ACHAT" and win.pnl_eur == pytest.approx(2.76 - 1.4) and win.robot
    assert loss.sens == "VENTE" and loss.pnl_eur == pytest.approx(-2.86) and not loss.robot
    s = pf.summarize(t)
    assert s.trades == 2 and s.gagnants == 1 and s.perdants == 1
    assert s.pnl_net == pytest.approx(1.36 - 2.86)
    assert s.frais == pytest.approx(-1.5)
    inst = pf.by_instrument(t)
    assert set(inst["symbole"]) == {"EURUSD", "XAUUSD"}
    assert pf.daily_pnl(t)["trades"].sum() == 2


def test_cash_movements(client):
    mv = pf.cash_movements(client, datetime(2020, 1, 1), datetime(2030, 1, 1))
    assert list(mv["type"]) == ["Dépôt", "Retrait"]
    assert mv["montant_eur"].sum() == pytest.approx(400.0)


def test_close_single_position(client, tmp_path):
    executor.close_position(client, Storage(tmp_path / "db.sqlite"), 11)
    req = mt5_client.mt5.sent[-1]
    assert req["position"] == 11 and req["type"] == 1                              # achat fermé par une vente
    with pytest.raises(executor.OrderRefused):
        executor.close_position(client, Storage(tmp_path / "db.sqlite"), 999)


RISK = {"risque_par_trade_pct": 0.5, "positions_simultanees_max": 1, "perte_max_jour_pct": 2.0,
        "perte_max_semaine_pct": 5.0, "drawdown_max_pct": 10.0, "trades_max_par_jour": 5, "pause_apres_perte_min": 0}


def test_risk_gauges(client):
    pos = pf.open_positions(client, SPECS, executor.MAGIC)
    st = AccountState(balance=300, equity=295, start_of_day_balance=300, start_of_week_balance=300, peak_equity=310,
                      trades_today=2, open_positions=1)
    g = {x.nom: x for x in pf.risk_gauges(st, RISK, pos)}
    assert g["Perte du jour"].utilise == pytest.approx(5 / 300 * 100)
    assert g["Perte du jour"].niveau == "attention"                               # 1.67 % sur 2 %
    assert g["Drawdown depuis le plus haut"].utilise == pytest.approx(15 / 310 * 100)
    assert "SANS stop loss" in g["Risque ouvert (si tous les SL sont touchés)"].detail
    assert g["Positions ouvertes"].niveau == "danger"


def test_withdrawal_impact():
    ok = pf.withdrawal_impact(500, 500, 0, 100, 1.0, {"XAUUSD": 4.5})
    assert ok.possible and ok.capital_apres == 400 and ok.risque_trade_apres == pytest.approx(4.0)
    assert any("XAUUSD" in m for m in ok.messages)                                 # or refusé après retrait
    blocked = pf.withdrawal_impact(500, 480, 300, 200, 1.0)
    assert not blocked.possible                                                   # marge libre insuffisante
    assert not pf.withdrawal_impact(500, 500, 0, 0, 1.0).possible


def test_pause_blocks_new_trades_but_is_not_global_stop():
    st = AccountState(balance=300, equity=300, start_of_day_balance=300, start_of_week_balance=300, peak_equity=300)
    now = datetime(2026, 11, 4, 10, tzinfo=timezone.utc)
    guards.activate_pause("test")
    assert guards.pause_active() and not guards.kill_switch_active()
    assert any("PAUSE" in r for r in RiskGuard(RISK).account_checks(st, now))
    guards.release_pause()
    assert RiskGuard(RISK).account_checks(st, now) == []


def test_example_history_format():
    bt = pd.DataFrame({"symbol": ["EURUSD"], "direction": ["BUY"], "lots": [0.01],
                       "entry_time": [pd.Timestamp("2026-11-02 08:00", tz="UTC")],
                       "exit_time": [pd.Timestamp("2026-11-02 09:00", tz="UTC")], "entry": [1.08], "exit": [1.081],
                       "gross": [0.92], "commission": [0.07], "swap": [0.0], "pnl": [0.85]})
    ex = pf.example_from_backtest(bt)
    assert list(ex.columns) == pf.TRADE_COLUMNS and ex.iloc[0].sens == "ACHAT"
