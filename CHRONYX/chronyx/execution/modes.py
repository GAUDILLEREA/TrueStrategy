"""Modes de fonctionnement et verrou du trading réel.

MODE 1 analyse     : signaux uniquement, aucun ordre.
MODE 2 assistance  : proposition entrée/SL/TP, l'utilisateur valide chaque ordre.
MODE 3 demo_auto   : ordres automatiques UNIQUEMENT si le compte MT5 est un compte démo.
MODE 4 reel        : désactivé par défaut. Nécessite les TROIS conditions :
                     - reel.active: true dans config.yaml,
                     - une confirmation manuelle saisie dans le dashboard (phrase exacte),
                     - une confirmation valable pour CE compte et CES paramètres de risque.
Le robot ne passe JAMAIS seul d'un mode à un autre.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from ..config import ROOT

CONFIRMATION_FILE = ROOT / "data" / "confirmation_reel.json"
CONFIRMATION_PHRASE = "J'ACCEPTE LE RISQUE DE PERTE EN REEL"
CONFIRMATION_VALIDITY = timedelta(hours=24)


class Mode(str, Enum):
    ANALYSE = "analyse"
    ASSISTANCE = "assistance"
    DEMO_AUTO = "demo_auto"
    REEL = "reel"

    @property
    def label(self) -> str:
        return {"analyse": "MODE 1 - ANALYSE", "assistance": "MODE 2 - ASSISTANCE",
                "demo_auto": "MODE 3 - DÉMO AUTOMATIQUE", "reel": "MODE 4 - RÉEL"}[self.value]

    @property
    def sends_orders_automatically(self) -> bool:
        return self in (Mode.DEMO_AUTO, Mode.REEL)


def risk_fingerprint(account_login: str | int, risk_cfg: dict, strategies: list[str]) -> str:
    """Empreinte des paramètres critiques : toute modification invalide la confirmation."""
    payload = json.dumps({"login": str(account_login), "risk": risk_cfg, "strategies": sorted(strategies)},
                         sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def write_real_confirmation(phrase: str, fingerprint: str, path: Path = CONFIRMATION_FILE) -> bool:
    if phrase.strip() != CONFIRMATION_PHRASE:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "fingerprint": fingerprint}),
                    encoding="utf-8")
    return True


def revoke_real_confirmation(path: Path = CONFIRMATION_FILE) -> None:
    if path.exists():
        path.unlink()


@dataclass
class GateDecision:
    allowed: bool
    reasons: list[str]


def order_gate(mode: Mode, account_is_demo: bool | None, real_enabled_in_config: bool,
               fingerprint: str | None = None, path: Path = CONFIRMATION_FILE,
               now: datetime | None = None) -> GateDecision:
    """Décide si un ordre AUTOMATIQUE peut être envoyé."""
    now = now or datetime.now(timezone.utc)
    if mode in (Mode.ANALYSE, Mode.ASSISTANCE):
        return GateDecision(False, [f"{mode.label} : aucun ordre automatique."])
    if account_is_demo is None:
        return GateDecision(False, ["Type de compte inconnu (MT5 non connecté) : aucun ordre."])
    if mode == Mode.DEMO_AUTO:
        if not account_is_demo:
            return GateDecision(False, ["Mode démo, mais le compte connecté est un compte RÉEL : ordre bloqué."])
        return GateDecision(True, [])
    # Mode réel
    reasons = []
    if account_is_demo:
        reasons.append("Mode réel sélectionné mais le compte est un compte démo.")
    if not real_enabled_in_config:
        reasons.append("Trading réel désactivé dans config.yaml (reel.active: false).")
    if not path.exists():
        reasons.append("Aucune confirmation manuelle du trading réel.")
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["ts"])
        if now - ts > CONFIRMATION_VALIDITY:
            reasons.append("Confirmation du trading réel expirée (validité 24 h).")
        if fingerprint is None or data.get("fingerprint") != fingerprint:
            reasons.append("Le compte ou les paramètres de risque ont changé depuis la confirmation.")
    return GateDecision(not reasons, reasons)
