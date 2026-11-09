"""Diagnostic de l'environnement Windows pour CHRONYX.

    python verifier_environnement.py

Vérifie : système, Python (version + 64 bits), dépendances, MetaTrader 5
(paquet, terminal, connexion, type de compte), configuration, calendrier.
Ne modifie rien et n'envoie aucun ordre.
"""
from __future__ import annotations

import importlib
import platform
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OK, KO, WARN = "[ OK ]", "[ERREUR]", "[ATTENTION]"
results: list[tuple[str, str, str]] = []


def report(status: str, item: str, detail: str = "") -> None:
    results.append((status, item, detail))
    print(f"{status:12} {item}" + (f" : {detail}" if detail else ""))


def check_system() -> None:
    sysname = platform.system()
    if sysname == "Windows":
        rel, ver = platform.release(), platform.version()
        build = int(ver.split(".")[-1]) if ver.split(".")[-1].isdigit() else 0
        name = "Windows 11" if build >= 22000 else f"Windows {rel}"
        report(OK if rel in ("10", "11") else WARN, "Système", f"{name} (build {ver})")
    else:
        report(WARN, "Système", f"{sysname} : MetaTrader 5 (API Python) nécessite Windows. Mode simulation seulement.")


def check_python() -> None:
    v = sys.version_info
    bits = struct.calcsize("P") * 8
    status = OK if (3, 10) <= (v.major, v.minor) <= (3, 13) else KO
    report(status, "Python", f"{platform.python_version()} ({bits} bits) - {sys.executable}")
    if bits != 64:
        report(KO, "Python 64 bits", "MetaTrader5 exige Python 64 bits.")


def check_packages() -> None:
    for mod, pip in [("pandas", "pandas"), ("numpy", "numpy"), ("yaml", "PyYAML"), ("streamlit", "streamlit"),
                     ("plotly", "plotly"), ("sklearn", "scikit-learn"), ("pytest", "pytest"),
                     ("dotenv", "python-dotenv"), ("keyring", "keyring")]:
        try:
            m = importlib.import_module(mod)
            report(OK, f"Paquet {pip}", getattr(m, "__version__", ""))
        except ImportError:
            report(KO, f"Paquet {pip}", "manquant -> lancer installer.bat")


def find_terminals() -> list[Path]:
    found = []
    for base in (Path("C:/Program Files"), Path("C:/Program Files (x86)")):
        if base.exists():
            found += list(base.glob("*/terminal64.exe"))
    return found


def check_mt5() -> None:
    try:
        import MetaTrader5 as mt5  # type: ignore
        report(OK, "Paquet MetaTrader5", getattr(mt5, "__version__", ""))
    except ImportError:
        report(KO if platform.system() == "Windows" else WARN, "Paquet MetaTrader5",
               "non installé (Windows uniquement)")
        return
    terms = find_terminals()
    report(OK if terms else WARN, "Terminal MetaTrader 5",
           ", ".join(str(t) for t in terms) if terms else "introuvable dans Program Files (installer MT5)")
    if not mt5.initialize():
        report(WARN, "Connexion MT5", f"impossible ({mt5.last_error()}). Ouvrez MT5 et connectez un compte démo.")
        return
    try:
        acc = mt5.account_info()
        term = mt5.terminal_info()
        if acc is None:
            report(WARN, "Compte MT5", "terminal ouvert mais aucun compte connecté")
            return
        demo = acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
        report(OK, "Compte MT5", f"{acc.server} - {'DÉMO' if demo else 'RÉEL'} - devise {acc.currency} - levier 1:{acc.leverage}")
        if not demo:
            report(WARN, "Type de compte", "Compte RÉEL connecté. Utilisez un compte DÉMO pour les phases de test.")
        report(OK if term.trade_allowed else WARN, "Trading algorithmique",
               "autorisé" if term.trade_allowed else "désactivé dans MT5 (bouton 'Trading Algo')")
        for sym in ("XAUUSD", "EURUSD"):
            si = mt5.symbol_info(sym)
            if si is None:
                report(WARN, f"Symbole {sym}", "introuvable (suffixe broker ? voir config.yaml)")
            else:
                report(OK, f"Symbole {sym}", f"lot min {si.volume_min}, contrat {si.trade_contract_size}, "
                                             f"spread {si.spread} pts")
    finally:
        mt5.shutdown()


def check_config() -> None:
    try:
        from chronyx.config import load_config
        cfg = load_config()
        report(OK, "config.yaml", f"mode {cfg.mode}, risque {cfg.risk['risque_par_trade_pct']} %, "
                                  f"instruments {', '.join(cfg.active_symbols)}")
        for w in cfg.warnings:
            report(WARN, "config.yaml", w)
        from chronyx.news.calendar import load_calendar
        st = load_calendar(cfg.path_for(cfg.get("calendrier", "fichier", default="data/calendrier.csv")),
                           float(cfg.get("calendrier", "age_max_heures", default=24)))
        report(OK if st.usable else WARN, "Calendrier économique", st.message + ("" if st.usable else
               " -> lancer maj_calendrier.bat"))
    except Exception as e:
        report(KO, "config.yaml", str(e))


def main() -> int:
    print("=" * 70 + "\n  CHRONYX - Vérification de l'environnement\n" + "=" * 70)
    check_system()
    check_python()
    check_packages()
    check_mt5()
    check_config()
    errors = sum(1 for s, _, _ in results if s == KO)
    warns = sum(1 for s, _, _ in results if s == WARN)
    print("=" * 70)
    print(f"Résultat : {errors} erreur(s), {warns} avertissement(s).")
    if errors:
        print("Corrigez les erreurs (voir README.md, section Dépannage).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
