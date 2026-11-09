# ⚡ CHRONYX AI TRADING BOT

Robot de scalping **XAUUSD (or) et Forex** pour **MetaTrader 5**, conçu pour un **petit capital (100 à 500 €)**,
avec une priorité absolue donnée à la **sécurité**, à la **gestion du risque** et à la **transparence**.

> ⚠️ **Avertissement.** CHRONYX ne promet aucun profit. Le trading de CFD avec effet de levier fait perdre de
> l'argent à la majorité des particuliers. Aucune stratégie n'est considérée comme rentable avant d'avoir été
> validée sur données réelles puis en compte démo. Ce logiciel n'est pas un conseil en investissement.

---

## 1. Ce que fait la version 0.1 (testée)

| Fonction | État |
|---|---|
| Connexion MetaTrader 5 (session du terminal, aucun mot de passe stocké) | Écrite, **à tester sur votre PC Windows** |
| Données de marché + contrôle qualité (trous, incohérences, données figées) | ✅ testé |
| Indicateurs EMA 20/50/200, RSI, ATR, MACD, supports/résistances (sans look-ahead) | ✅ testé |
| Stratégie A - Scalping de tendance multi-timeframes, signaux expliqués | ✅ testé |
| Calcul de lot, valeur du pip, spread, commission, marge, liquidation, R/R net | ✅ testé |
| **Refus automatique** si le lot minimum dépasse votre risque maximum | ✅ testé |
| Faisabilité du scalping selon votre capital | ✅ testé |
| Coupe-circuits : perte jour/semaine, drawdown, trades max, pause après perte, spread, anti-doublon, horaires | ✅ testé |
| STOP GLOBAL (dashboard, fichier, `stop_global.bat`) | ✅ testé |
| Filtre calendrier économique (bloque si calendrier absent/ancien) | ✅ testé |
| Backtest (spread bid/ask, commission, slippage, swap, gaps, SL prioritaire) + statistiques + robustesse | ✅ testé |
| 4 modes (Analyse / Assistance / Démo auto / Réel verrouillé) | ✅ verrou testé ; envoi d'ordres **à tester en démo** |
| Comparateur de brokers (données réglementaires à vérifier, mesure des spreads réels en démo) | ✅ testé |
| Dashboard sombre en français (8 onglets) | ✅ testé dans un navigateur |
| Stratégies B à E, module IA, recherche de stratégies | ⏳ phases suivantes |

Voir [docs/ETAT_DU_PROJET.md](docs/ETAT_DU_PROJET.md) pour le détail phase par phase.

---

## 2. Installation sous Windows 10 / 11 (pas à pas)

### Étape 1 — Installer Python
1. Aller sur <https://www.python.org/downloads/windows/>.
2. Télécharger **Python 3.12 (64-bit)** — « Windows installer (64-bit) ».
3. Lancer l'installateur et **cocher « Add python.exe to PATH »**, puis « Install Now ».

### Étape 2 — Installer MetaTrader 5 et ouvrir un compte DÉMO
1. Télécharger MetaTrader 5 depuis <https://www.metatrader5.com/fr/download> (ou depuis le site d'un broker).
2. Ouvrir MT5 → *Fichier* → *Ouvrir un compte* → choisir un serveur **démo** (les comptes démo sont gratuits, sans dépôt).
3. Dans MT5, activer le bouton **« Trading Algo »** (barre d'outils) — nécessaire pour le mode démo automatique.
4. Vérifier que **XAUUSD** et **EURUSD** apparaissent dans l'*Observation du marché* (clic droit → *Symboles* sinon).

> Vous n'avez pas besoin de choisir un broker maintenant. Le comparateur intégré vous aidera, et vous pouvez
> ouvrir des comptes démo chez plusieurs brokers pour mesurer leurs spreads réels.

### Étape 3 — Installer CHRONYX
1. Copier le dossier `CHRONYX` où vous voulez (ex. `C:\CHRONYX`). Éviter OneDrive.
2. Double-cliquer sur **`installer.bat`**. Il crée un environnement isolé (`.venv`), installe les dépendances,
   télécharge le calendrier économique puis lance le diagnostic.

### Étape 4 — Lancer
1. Ouvrir MetaTrader 5 et se connecter au compte démo.
2. Double-cliquer sur **`start_bot.bat`** : le moteur démarre dans une fenêtre et le **dashboard s'ouvre dans le navigateur**
   (<http://localhost:8501>).

Sans MetaTrader 5, CHRONYX démarre en **mode SIMULATION** (données fictives, clairement signalées) pour vérifier l'installation.

---

## 3. Fichiers utiles

| Fichier | Rôle |
|---|---|
| `start_bot.bat` | Lance le moteur + le dashboard |
| `installer.bat` | Installation (une fois) |
| `verifier_environnement.bat` | Diagnostic : Windows, Python, dépendances, MT5, compte, config, calendrier |
| `maj_calendrier.bat` | Met à jour le calendrier économique |
| `stop_global.bat` | Arrêt d'urgence sans dashboard |
| `lancer_tests.bat` | Lance les tests automatiques |
| `demarrage_auto_windows.bat` | (Facultatif) démarrage à l'ouverture de session — `/supprimer` pour annuler |
| `config.yaml` | Tous les paramètres (aussi modifiables dans le dashboard) |
| `.env.example` | Modèle de variables (sans mot de passe) |
| `docs/GUIDE_UTILISATEUR.md` | Guide d'utilisation complet |

---

## 4. Sécurité — ce qui est garanti par le code

- **Mode par défaut : ANALYSE** (aucun ordre). Le mode **RÉEL** exige : `reel.active: true` dans `config.yaml`
  **+** compte réel connecté **+** phrase de confirmation tapée dans le dashboard, valable 24 h et liée au compte et
  aux paramètres de risque (toute modification l'annule). Le robot ne passe **jamais** seul du démo au réel.
- **Mode DÉMO AUTO** : refuse d'envoyer un ordre si le compte connecté n'est pas un compte démo.
- **Risque plafonné** : 2 % par trade maximum (codé en dur), 1 % recommandé au plus, 0,5 % par défaut.
- **Martingale, grid, récupération des pertes : impossibles.** La taille de position dépend uniquement du capital
  actuel et du % de risque.
- Chaque ordre part **avec SL et TP côté broker** : la position reste protégée même si le PC s'éteint.
- **Fail-closed** : données douteuses, calendrier absent/ancien, connexion perdue → pas de trade.
- **Identifiants** : jamais stockés en clair. Méthode recommandée : le robot utilise la session déjà ouverte dans MT5.
  Option : mot de passe dans le Gestionnaire d'identifiants Windows (`python -m chronyx.secrets enregistrer LOGIN`).
  Aucun identifiant n'est transmis à une IA ou à un service externe.
- Journal complet : `logs/chronyx.log` + base SQLite `data/chronyx.db` (signaux, ordres, événements).

---

## 5. Ce que les premiers calculs révèlent pour votre capital

Calculs du module de faisabilité (spécifications indicatives : 0,01 lot minimum, levier ESMA 1:20 sur l'or) :

- **100 €** : un seul micro-lot d'or (0,01) immobilise environ **110 € de marge** à 2 400 $/once, et davantage si le
  cours est plus élevé → **l'or n'est pas tradable**.
- **300 €** : un stop M5 typique sur l'or fait risquer **≈ 1,4 %** du capital au lot minimum → refusé avec un risque de 0,5 % ou 1 %.
- **500 €** : jugé **limite** à 1 % de risque.
- Sur EURUSD/GBPUSD en M5, plusieurs combinaisons sont **viables** sur le plan du risque — à confirmer avec les spreads
  réels de votre broker.

Le robot affichera ces chiffres **avec les vraies spécifications de votre broker** dès que MT5 sera connecté
(onglet *Capital & faisabilité*).

---

## 6. Dépannage

| Problème | Solution |
|---|---|
| « Python est introuvable » | Réinstaller Python en cochant *Add python.exe to PATH* |
| « Le module MetaTrader5 n'est pas installé » | Vérifier Python **64 bits**, relancer `installer.bat` |
| « Échec de connexion à MetaTrader 5 » | Ouvrir MT5 et se connecter à un compte avant de lancer CHRONYX |
| Symbole introuvable | Le broker utilise un suffixe (ex. `XAUUSD.r`) : renseigner `broker.suffixe_symboles` dans `config.yaml` |
| « Calendrier introuvable / ancien » | Lancer `maj_calendrier.bat` (connexion Internet requise) |
| Le dashboard ne s'ouvre pas | Ouvrir manuellement <http://localhost:8501> |

## 7. Tests

```
lancer_tests.bat           (ou : .venv\Scripts\python -m pytest -v)
```
