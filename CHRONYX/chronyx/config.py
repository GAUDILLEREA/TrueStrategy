"""Chargement et validation de la configuration.

Les limites absolues (risque max, perte max, interdiction martingale/grid)
sont appliquées ici : toute valeur dépassant une limite est ramenée à la
limite et un avertissement est enregistré.
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

try:  # variables non secrètes (.env) : chemin du terminal, login, serveur
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"

VALID_MODES = ("analyse", "assistance", "demo_auto", "reel")

# Plafonds codés en dur : même un config.yaml modifié ne peut pas les dépasser.
HARD_MAX_RISK_PCT = 2.0
HARD_MAX_DAILY_LOSS_PCT = 5.0
HARD_MAX_DRAWDOWN_PCT = 20.0


@dataclass
class Config:
    raw: dict[str, Any]
    path: Path
    warnings: list[str] = field(default_factory=list)

    # ---- accès pratiques ----
    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    @property
    def mode(self) -> str:
        return self.raw["general"]["mode"]

    @property
    def risk(self) -> dict[str, Any]:
        return self.raw["risque"]

    @property
    def active_symbols(self) -> list[str]:
        return [s for s, v in self.raw.get("instruments", {}).items() if v and v.get("actif")]

    def spread_max_points(self, symbol: str) -> float:
        table = self.risk.get("spread_max_points", {}) or {}
        return float(table.get(symbol, table.get("defaut", 20)))

    def path_for(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else ROOT / p

    def save(self, path: Path | None = None) -> None:
        target = path or self.path
        with open(target, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.raw, f, allow_unicode=True, sort_keys=False)


def _clamp(cfg: dict, section: str, key: str, maximum: float, warnings: list[str]) -> None:
    val = cfg.get(section, {}).get(key)
    if val is None:
        return
    if float(val) > maximum:
        warnings.append(f"{section}.{key}={val} dépasse la limite absolue {maximum} : ramené à {maximum}.")
        cfg[section][key] = maximum
    if float(val) <= 0:
        raise ValueError(f"{section}.{key} doit être strictement positif (valeur : {val}).")


def validate(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    cfg = copy.deepcopy(raw)
    warnings: list[str] = []

    for section in ("general", "capital", "risque", "limites_absolues"):
        if section not in cfg:
            raise ValueError(f"Section obligatoire manquante dans config.yaml : '{section}'")

    mode = cfg["general"].get("mode", "analyse")
    if mode not in VALID_MODES:
        raise ValueError(f"Mode inconnu '{mode}'. Modes valides : {', '.join(VALID_MODES)}")

    # Le mode réel n'est jamais accepté via le fichier seul : il faut reel.active ET
    # une confirmation manuelle depuis le dashboard (voir execution/modes.py).
    if mode == "reel" and not cfg.get("reel", {}).get("active", False):
        warnings.append("Mode 'reel' demandé sans activation manuelle : retour forcé au mode 'analyse'.")
        cfg["general"]["mode"] = "analyse"

    lim = cfg["limites_absolues"]
    max_risk = min(float(lim.get("risque_par_trade_pct_max", HARD_MAX_RISK_PCT)), HARD_MAX_RISK_PCT)
    max_daily = min(float(lim.get("perte_max_jour_pct_max", HARD_MAX_DAILY_LOSS_PCT)), HARD_MAX_DAILY_LOSS_PCT)
    max_dd = min(float(lim.get("drawdown_max_pct_max", HARD_MAX_DRAWDOWN_PCT)), HARD_MAX_DRAWDOWN_PCT)

    _clamp(cfg, "risque", "risque_par_trade_pct", max_risk, warnings)
    _clamp(cfg, "risque", "perte_max_jour_pct", max_daily, warnings)
    _clamp(cfg, "risque", "drawdown_max_pct", max_dd, warnings)

    if lim.get("martingale_autorisee") or lim.get("grid_autorisee"):
        warnings.append("Martingale / grid interdits : options forcées à false.")
        lim["martingale_autorisee"] = False
        lim["grid_autorisee"] = False

    if float(cfg["risque"].get("risk_reward", 0)) <= 0:
        raise ValueError("risque.risk_reward doit être > 0")
    if float(cfg["capital"].get("capital_initial", 0)) <= 0:
        raise ValueError("capital.capital_initial doit être > 0")

    for w in warnings:
        log.warning(w)
    return cfg, warnings


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(p, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cfg, warnings = validate(raw)
    return Config(raw=cfg, path=p, warnings=warnings)
