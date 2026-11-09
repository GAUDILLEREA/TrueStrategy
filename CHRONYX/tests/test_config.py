import copy

import pytest

from chronyx.config import DEFAULT_CONFIG_PATH, load_config, validate


def base():
    return copy.deepcopy(load_config().raw)


def test_default_config_loads_and_is_safe():
    cfg = load_config(DEFAULT_CONFIG_PATH)
    assert cfg.mode in ("analyse", "assistance", "demo_auto")
    assert cfg.risk["risque_par_trade_pct"] <= 1.0          # pas plus de 1 % par défaut
    assert cfg.get("reel", "active") is False               # réel désactivé par défaut
    assert "XAUUSD" in cfg.active_symbols


def test_risk_is_clamped_to_absolute_limit():
    raw = base()
    raw["risque"]["risque_par_trade_pct"] = 10
    raw["limites_absolues"]["risque_par_trade_pct_max"] = 50  # tentative de lever la limite
    cfg, warnings = validate(raw)
    assert cfg["risque"]["risque_par_trade_pct"] == 2.0
    assert warnings


def test_real_mode_without_activation_falls_back_to_analysis():
    raw = base()
    raw["general"]["mode"] = "reel"
    raw["reel"]["active"] = False
    cfg, warnings = validate(raw)
    assert cfg["general"]["mode"] == "analyse"


def test_martingale_and_grid_cannot_be_enabled():
    raw = base()
    raw["limites_absolues"]["martingale_autorisee"] = True
    raw["limites_absolues"]["grid_autorisee"] = True
    cfg, _ = validate(raw)
    assert cfg["limites_absolues"]["martingale_autorisee"] is False
    assert cfg["limites_absolues"]["grid_autorisee"] is False


def test_invalid_mode_rejected():
    raw = base()
    raw["general"]["mode"] = "yolo"
    with pytest.raises(ValueError):
        validate(raw)
