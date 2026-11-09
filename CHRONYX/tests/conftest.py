import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chronyx.risk import guards  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_kill_switch(tmp_path, monkeypatch):
    """Chaque test utilise son propre fichier STOP_GLOBAL (jamais celui de l'utilisateur)."""
    monkeypatch.setattr(guards, "KILL_SWITCH_FILE", tmp_path / "STOP_GLOBAL")
    monkeypatch.setattr(guards, "PAUSE_FILE", tmp_path / "PAUSE")
    yield


def make_bars(rows, start="2026-11-02 08:00", freq="5min", spread=0):
    """rows : liste de (open, high, low, close)."""
    t = pd.date_range(start, periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df.insert(0, "time", t)
    df["tick_volume"] = 100
    df["spread"] = spread
    return df
