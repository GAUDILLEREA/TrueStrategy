"""Journalisation complète : console + fichier rotatif (logs/chronyx.log)."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import ROOT

_CONFIGURED = False


def setup_logging(level: int = logging.INFO, log_dir: str | Path = "logs") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    d = Path(log_dir)
    if not d.is_absolute():
        d = ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    fh = RotatingFileHandler(d / "chronyx.log", maxBytes=5_000_000, backupCount=10, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)
    _CONFIGURED = True
