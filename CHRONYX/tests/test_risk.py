from datetime import datetime, timedelta, timezone

import pytest

from chronyx.data.symbol_spec import esma_retail_leverage, indicative_spec, margin_required
from chronyx.risk import guards
from chronyx.risk.feasibility import assess
from chronyx.risk.guards import AccountState, RiskGuard
from chronyx.risk.position_sizing import plan_trade

XAU = indicative_spec("XAUUSD")
EUR = indicative_spec("EURUSD")


# ---------------------------------------------------------------- spécifications
def test_pip_and_point_values():
    # EURUSD : 1 pip sur 1 lot = 10 USD = 9.2 € (taux indicatif 0.92)
    assert EUR.pip_value(1.0) == pytest.approx(9.2)
    # XAUUSD : 1 $ de mouvement sur 0.01 lot (1 once) = 1 USD = 0.92 €
    assert XAU.money_for_distance(1.0, 0.01) == pytest.approx(0.92)


def test_volume_is_rounded_down_never_up():
    assert EUR.normalize_volume(0.0199) == 0.01
    assert EUR.normalize_volume(0.009) == 0.0
    assert EUR.normalize_volume(0.03) == 0.03


def test_esma_leverage():
    assert esma_retail_leverage("XAUUSD") == 20
    assert esma_retail_leverage("EURUSD") == 30
    assert esma_retail_leverage("AUDUSD") == 20


def test_margin_gold_min_lot():
    # 0.01 lot = 1 once à 2400 $ => 2400 $ * 0.92 / 20 = 110.4 €
    assert margin_required(XAU, 0.01, 2400, 20) == pytest.approx(110.4)


# ---------------------------------------------------------------- taille de position
def test_plan_accepted_and_risk_within_target():
    p = plan_trade(EUR, "BUY", balance=500, risk_pct=1.0, entry=1.08, sl_distance=0.0010, rr=1.5,
                   spread_points=8, commission_per_lot_rt=7.0, max_margin_pct=100)
    assert p.accepted, p.reasons
    assert p.risk_eur <= 5.0 + 1e-9
    assert p.lots >= EUR.volume_min


def test_lot_calculation_detail():
    # perte par lot = 10 pips * 9.2 + 0.8 pip de spread * 9.2 + 7 € commission = 106.36 €
    p = plan_trade(EUR, "BUY", 500, 1.0, 1.08, 0.0010, 1.5, 8, 7.0, max_margin_pct=100)
    assert p.lots == pytest.approx(0.04)
    assert p.risk_eur == pytest.approx(0.04 * 106.36, rel=1e-6)
    assert p.stop_loss == pytest.approx(1.0790)
    assert p.take_profit == pytest.approx(1.0815)


def test_min_lot_too_risky_is_refused():
    # Or, 300 €, 0.5 % = 1.5 € max ; stop 3 $ sur 0.01 lot = 2.76 € + spread => REFUS
    p = plan_trade(XAU, "BUY", 300, 0.5, 2400, 3.0, 1.5, 25)
    assert not p.accepted
    assert "lot_min" in p.reason_codes
    assert p.min_lot_risk_pct > 0.5


def test_margin_too_high_is_refused():
    p = plan_trade(XAU, "BUY", 100, 2.0, 2400, 0.5, 1.5, 10)
    assert not p.accepted
    assert "marge" in p.reason_codes


def test_spread_too_wide_relative_to_stop_is_refused():
    p = plan_trade(EUR, "SELL", 5000, 1.0, 1.08, 0.0003, 1.5, spread_points=10)
    assert "spread" in p.reason_codes


def test_sell_levels():
    p = plan_trade(EUR, "SELL", 5000, 0.5, 1.08, 0.0010, 2.0, 5, max_margin_pct=100)
    assert p.stop_loss > p.entry > p.take_profit


def test_no_martingale_after_loss():
    before = plan_trade(EUR, "BUY", 500, 1.0, 1.08, 0.0010, 1.5, 8, max_margin_pct=100)
    after_loss = plan_trade(EUR, "BUY", 480, 1.0, 1.08, 0.0010, 1.5, 8, max_margin_pct=100)
    assert after_loss.lots <= before.lots


def test_net_rr_accounts_for_costs():
    p = plan_trade(EUR, "BUY", 5000, 1.0, 1.08, 0.0010, 2.0, 10, 7.0, max_margin_pct=100)
    assert p.rr_net < p.rr_nominal


# ---------------------------------------------------------------- faisabilité
def test_feasibility_gold_small_capital():
    assert assess(XAU, "M5", 100, 2.9, 25, 0, 1.0, price=2400).verdict == "non viable"  # marge
    assert assess(XAU, "M5", 300, 2.9, 25, 0, 1.0, price=2400).verdict == "non viable"  # risque lot min


# ---------------------------------------------------------------- coupe-circuits
RISK = {"perte_max_jour_pct": 2.0, "perte_max_semaine_pct": 5.0, "drawdown_max_pct": 10.0, "trades_max_par_jour": 5,
        "positions_simultanees_max": 1, "pause_apres_perte_min": 30}
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)  # mercredi 11:00 Paris


def state(**kw):
    base = dict(balance=300, equity=300, start_of_day_balance=300, start_of_week_balance=300, peak_equity=300)
    base.update(kw)
    return AccountState(**base)


def test_guard_allows_clean_state():
    assert RiskGuard(RISK).account_checks(state(), NOW) == []


@pytest.mark.parametrize("kw,needle", [
    (dict(equity=293), "Perte du jour"),
    (dict(equity=284, start_of_day_balance=284.5), "semaine"),
    (dict(equity=269, start_of_day_balance=269, start_of_week_balance=269, peak_equity=300), "Drawdown"),
    (dict(trades_today=5), "trades du jour"),
    (dict(open_positions=1), "positions simultanées"),
    (dict(last_loss_time=NOW - timedelta(minutes=10)), "Pause après perte"),
])
def test_guard_blocks(kw, needle):
    reasons = RiskGuard(RISK).account_checks(state(**kw), NOW)
    assert any(needle in r for r in reasons), reasons


def test_kill_switch_blocks_everything():
    guards.activate_kill_switch("test")
    assert any("STOP GLOBAL" in r for r in RiskGuard(RISK).account_checks(state(), NOW))
    guards.release_kill_switch()
    assert RiskGuard(RISK).account_checks(state(), NOW) == []


def test_hard_stop_on_drawdown():
    assert RiskGuard(RISK).hard_stop_reached(state(equity=270, peak_equity=300))


def test_duplicate_and_spread():
    g = RiskGuard(RISK)
    assert g.duplicate_check("XAUUSD", state(open_symbols={"XAUUSD"}))
    assert g.spread_check("XAUUSD", 50, 35)
    assert not g.spread_check("XAUUSD", 20, 35)


def test_schedule():
    g = RiskGuard(RISK, {"plages": [{"debut": "08:00", "fin": "12:00"}], "jours": ["lundi", "mardi", "mercredi"]})
    assert g.schedule_check(NOW) == []                                   # 11:00 Paris mercredi
    assert g.schedule_check(NOW + timedelta(hours=3))                    # 14:00 Paris
    assert g.schedule_check(NOW + timedelta(days=1))                     # jeudi
