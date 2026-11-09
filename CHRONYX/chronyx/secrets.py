"""Stockage sécurisé des identifiants MetaTrader 5.

Les mots de passe ne sont JAMAIS écrits dans un fichier. Ils sont stockés
dans le Gestionnaire d'identifiants Windows via la bibliothèque `keyring`.
Ils ne sont transmis à aucun service externe ni à aucune IA.

Utilisation (dans une invite de commandes) :
    python -m chronyx.secrets enregistrer 12345678
    python -m chronyx.secrets supprimer 12345678
"""
from __future__ import annotations

import getpass
import sys

SERVICE = "CHRONYX-MT5"


def _keyring():
    try:
        import keyring  # type: ignore
        return keyring
    except ImportError:
        return None


def get_mt5_password(login: str) -> str | None:
    kr = _keyring()
    if kr is None:
        return None
    return kr.get_password(SERVICE, str(login))


def main(argv: list[str]) -> int:
    kr = _keyring()
    if kr is None:
        print("Le module 'keyring' n'est pas installé : pip install keyring")
        return 1
    if len(argv) != 2 or argv[0] not in ("enregistrer", "supprimer"):
        print(__doc__)
        return 1
    action, login = argv
    if action == "enregistrer":
        pwd = getpass.getpass(f"Mot de passe MT5 du compte {login} (saisie masquée) : ")
        kr.set_password(SERVICE, login, pwd)
        print("Mot de passe enregistré dans le Gestionnaire d'identifiants Windows.")
    else:
        kr.delete_password(SERVICE, login)
        print("Mot de passe supprimé.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
