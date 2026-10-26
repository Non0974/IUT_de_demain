# Serveur CampusTwin

Le serveur tourne sur un vieux PC ou un Raspberry Pi de l'IUT. **Python 3.10 ou plus suffit, rien à installer** (sauf pour l'assistant IA, en option). Il :
- reçoit les mesures des cartes ESP32 ;
- calcule l'état de chaque salle : personnes, émargement, Wi-Fi, air, diagnostic ;
- tient le registre des présences (séances, corrections, export) ;
- prévoit le CO₂ de chaque salle pour les 2 prochaines heures et le nombre d'étudiants de chaque cours, ventile en avance la salle de l'automate et propose des changements de salle ;
- pilote l'automate en Modbus TCP ;
- sert l'interface de suivi des classes (avec comptes) et le jumeau 3D ;
- répond aux questions posées en français (assistant IA).

```
python serveur/serveur.py                    vraies cartes et vrai automate (voir config.py)
python serveur/serveur.py --simulation       bâtiment et automate simulés, pour tester
python serveur/serveur.py --simulation --vitesse 300
```

Puis ouvrir http://localhost:8000 : l'interface de suivi des classes. En simulation, les comptes de démonstration sont **directeur** / **demo** et **enseignant** / **demo**.

## Comptes de l'interface de suivi

Avec les vrais capteurs, il faut créer les comptes. Les mots de passe sont demandés au clavier et ne sont gardés que sous forme d'empreinte PBKDF2, dans `serveur/comptes.json` (pas sur GitHub).

```
python serveur/comptes.py ajouter direction --role directeur --nom "Directeur des études"
python serveur/comptes.py ajouter dupont --role enseignant --nom "M. Dupont" --enseignant "DUPONT Jean"
python serveur/comptes.py liste
```

Le nom donné à `--enseignant` doit être celui de l'emploi du temps.

**Noms des enseignants.** Dans le dépôt (public), ils sont remplacés par « Enseignant A, B… ». Pour les vrais noms en local, créer `serveur/enseignants.json` (pas sur GitHub) :

```
{"Enseignant A": "NOM Prénom", "Enseignant B": "NOM Prénom"}
```

Le serveur les remet dans l'emploi du temps et dans l'interface.

| Rôle | Ce qu'il voit | Ce qu'il peut faire |
| --- | --- | --- |
| `directeur`, `scolarite` | Tout l'IUT, le jumeau 3D | Corriger toutes les séances, exporter |
| `enseignant` | Ses séances, ses classes, les étudiants de ses classes (pour ses cours) | Corriger ses séances, exporter ses classes |

- La session dure 10 h.
- Après 5 mauvais mots de passe en une minute, l'adresse est bloquée une minute.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| [serveur.py](serveur.py) | Serveur web, réception des messages, pilotage de la ventilation |
| [salle.py](salle.py) | État d'une salle : comptage de la porte, badges et émargement vérifié, modèle Wi-Fi |
| [estimateur.py](estimateur.py) | Débit d'air réel (deux méthodes), recalage, diagnostic des 5 causes |
| [automate.py](automate.py) | Client Modbus TCP (sans bibliothèque) et règle de ventilation |
| [stockage.py](stockage.py) | Enregistre tous les messages dans `campustwin.db` (SQLite) |
| [registre.py](registre.py) | Registre des présences (`registre.db`) : séances, statut de chaque étudiant, corrections avec auteur et motif, anomalies, export CSV |
| [suivi.py](suivi.py) | Ce que lit l'interface de suivi, avec les règles d'accès |
| [comptes.py](comptes.py) | Comptes, mots de passe et sessions |
| [planning.py](planning.py) | Emploi du temps de chaque jour, avec les changements de salle acceptés |
| [prevision.py](prevision.py) | Jumeau prédictif : personnes attendues et CO₂ de chaque salle pour les 2 prochaines heures, et précision mesurée |
| [commande.py](commande.py) | Ventilation anticipée de la salle de l'automate (commande prédictive) et bilan d'énergie face à la règle simple |
| [capacite.py](capacite.py) | Places des salles : chaque cours de la journée face aux places de sa salle (compté ou prévu) |
| [reaffectation.py](reaffectation.py) | Propositions de changement de salle : air qui va devenir mauvais, ou salle trop petite |
| [assistant.py](assistant.py) | Assistant IA : outils en lecture seule, pseudonymes, appel à l'API Claude |
| [config.py](config.py) | Adresse de l'automate, débits connus, clé des capteurs, sel des cartes, réglages de la ventilation et de l'assistant |

## Messages des capteurs

`POST /api/mesure` avec un objet JSON, ou une liste d'objets. En-tête `X-Cle` si `CLE_CAPTEURS` est rempli.

| type | champs | envoyé par |
| --- | --- | --- |
| `co2` | `salle`, `co2` (ppm), `temp` (°C, optionnel) | nœud salle, toutes les 30 s |
| `passage` | `salle`, `sens` (+1 entrée, −1 sortie), `confiance` | nœud porte |
| `presence` | `salle`, `presence` (vrai/faux) | nœud porte (radar) |
| `badge` | `salle`, `carte` (empreinte, 16 caractères) | nœud salle |
| `wifi` | `bornes` : `{salle: nombre d'appareils}` | export de la DSI, chaque minute |

Heure : `t` (secondes depuis 1970) si la carte a l'heure exacte. Sinon `age_ms`, l'âge du message s'il a attendu dans la file de la carte.

`POST /api/cartes` : table `{empreinte: {"id": "TP1-03", "groupe": "TP1"}}`.
- Elle vient de la scolarité. Les enseignants ont `"groupe": "enseignant"`.
- Elle est gardée dans `serveur/cartes.json`, qui n'est pas mis sur GitHub.

## Ce que lit le site

Toutes ces adresses demandent d'être connecté. Celles du jumeau 3D et des prévisions (`/api/etat`, `/api/flux`, `/api/historique`, `/api/commande`, `/api/simulation/panne`, `/api/previsions`, `/api/proposition`) sont réservées au directeur et à la scolarité.

| Adresse | Contenu |
| --- | --- |
| `POST /api/connexion` | `{"login", "mot_de_passe"}` : ouvre une session (cookie) |
| `GET /api/tableau` | Tableau de bord : séances en cours, chiffres du jour, alertes |
| `GET /api/seances?date=AAAA-MM-JJ` | Séances d'un jour, avec leur émargement (et celles à venir) |
| `GET /api/seance?id=…` | Une séance : statut de chaque étudiant, anomalies, corrections |
| `POST /api/seance/statut` | `{"seance", "etudiant", "statut", "motif"}` : corriger un statut |
| `GET /api/classes?du=…&au=…` | Bilan de chaque classe sur la période |
| `GET /api/classe?id=TP1&du=…&au=…` | Tableau d'une classe : étudiants × séances |
| `GET /api/etudiant?id=TP1-03&du=…&au=…` | Fiche d'un étudiant |
| `GET /api/export?classe=TP1&du=…&au=…` | Feuille de présence CSV, avec les demi-journées pour le CFA |
| `GET /api/etat` | État de toutes les salles et de l'automate |
| `GET /api/flux` | Le même état toutes les secondes (Server-Sent Events) |
| `GET /api/historique?salle=SAR 200` | CO₂ et personnes de la journée, une valeur par minute |
| `POST /api/commande` | `{"auto": false, "niveau": "grande"}` : forcer la ventilation ; `{"strategie": "predictive"}` ou `"reactive"` : jumeau ou règle simple |
| `GET /api/previsions` | Prévision de chaque salle, plan de ventilation, bilan d'énergie, places des salles, propositions de salle |
| `POST /api/proposition` | `{"action": "accepter", "cours", "salle"}` ou `{"action": "ignorer", "cours"}` |
| `GET /api/assistant` | L'assistant est-il prêt, questions suggérées, conversation en cours |
| `POST /api/assistant` | `{"question": "…"}` : réponse de l'assistant ; `{"nouvelle": true}` : nouvelle conversation |
| `POST /api/simulation/panne` | `{"panne": "fenetre"}` : provoquer une panne (mode simulation seulement) |

## Jumeau prédictif

- **Prévision.** Pour chaque salle : les cours de l'emploi du temps, le nombre de personnes attendues, et le débit d'air appris par la salle. Le jumeau simule le CO₂ des 2 heures suivantes. Toutes les 10 min, il note sa prévision à 30 et 60 min et la compare à la mesure.
- **Qui viendra.** Le taux de présence est appris sur les 14 derniers jours : celui de chaque groupe, et l'effet de chaque demi-journée de la semaine. Un groupe vu une seule fois garde un taux proche de la moyenne (une séance seule varie trop par hasard). Étudiants attendus = effectif × taux du groupe × effet de la demi-journée.
- **Places des salles.** Chaque cours de la journée face aux places de sa salle : compté pour un cours commencé (capteurs de la porte, sinon badges, car le Wi-Fi se trompe de 2 ou 3 personnes), prévu pour un cours à venir. Salle trop petite (plus d'étudiants que de places), pleine (plus de 90 %), adaptée, ou trop grande (moins de 40 %, alors qu'une salle du même type plus petite existe). Alerte en direct si une salle a plus de monde que de places pendant 5 minutes en plein cours.
- **Ventilation anticipée (SAR 200).** Chaque minute, le jumeau essaie les vitesses possibles pour les 20 minutes suivantes, simule 90 minutes et garde le plan le moins coûteux : énergie (chauffage de l'air neuf + ventilateur) plus une pénalité au-dessus de 800 et 1000 ppm. Il garde la petite vitesse 20 min après chaque cours et le soir, sinon le diagnostic ne peut plus mesurer la décroissance ni la dérive du capteur.
- **Changement de salle.** Si l'air d'un cours doit dépasser 1200 ppm, ou s'il y aura plus d'étudiants que de places, le jumeau cherche une salle libre du même type, assez grande, dont il connaît la ventilation, où le pic reste sous 1200 ppm. Sans salle libre assez grande, le problème est signalé quand même. Le directeur accepte ou ignore dans la page Anticipation. Un cours déplacé change dans le planning du jour.
- **Limite.** En simulation, la prévision utilise la même physique que le bâtiment simulé : sa précision y est forcément bonne. Le vrai test se fera sur la salle réelle.

## Assistant IA (en option)

On pose une question en français dans la page « Assistant IA » : « Qui est absent en SAR 109 ? », « Quelle salle aura l'air mauvais dans l'heure ? ». Le serveur envoie la question à Claude (Anthropic), qui lit les données avec 10 outils, puis répond.

Pour l'activer :
```
pip install anthropic
set ANTHROPIC_API_KEY=sk-ant-...        (clé à créer sur console.anthropic.com, puis relancer le serveur)
```
Sans ça, la page dit que l'assistant est hors ligne et tout le reste marche.

- **L'IA ne voit aucun nom.** Avant l'envoi, chaque étudiant devient ETU-001, ETU-002… (un jeu par conversation) et chaque enseignant « Enseignant A, B… ». Un nom tapé dans la question est remplacé aussi. Les motifs d'absence (parfois médicaux) et les auteurs des corrections ne partent pas. Le serveur remet les vrais noms dans la réponse affichée.
- **Mêmes droits que la personne connectée.** Un enseignant n'a que ses séances et ses classes, et pas les outils du bâtiment ni des prévisions.
- **Lecture seule.** Corriger une présence ou déplacer un cours reste un clic humain.
- **Coût.** Quelques centimes par question. 30 questions par heure et par compte au plus, 15 questions par conversation (`config.py`).
- **Réglages** (`config.py`) : modèle `claude-opus-5-5`, effort `medium` (`low` répond plus vite). Si le modèle refuse une question par erreur, l'API la relance sur le modèle de secours conseillé par Anthropic (`fallbacks: "default"`).

## Ce que les données réelles ont changé dans le diagnostic

Voir [donnees_reelles](../donnees_reelles/README.md).
- **Recalage de chaque salle sur ses 3 premiers départs :** rapport normal entre les deux méthodes, et débit de référence quand on ne connaît pas la ventilation.
- **Comptage faux décidé sur la médiane de plusieurs départs**, pas sur un seul.
- **Niveau du soir mesuré seulement si le CO₂ est stable.** Dans ROBOD, le CO₂ d'une salle fermée peut monter la nuit.
- **Décroissance coupée** quand le CO₂ rejoint le bruit du capteur.
- **5ᵉ cause :** capteur de CO₂ mal placé.

## Tests

```
python tests/test_scenarios.py     une semaine simulée, chaque panne et chaque fraude doit être trouvée
python tests/test_automate.py      échange Modbus et sécurité de l'automate simulé
python tests/test_suivi.py         comptes, droits, registre des présences, corrections, export
python tests/test_prevision.py     prévisions, ventilation anticipée, présence apprise, places des salles, changement de salle
python tests/test_assistant.py     assistant IA avec un faux client : aucun nom envoyé, droits, refus, page web
```
