# Serveur CampusTwin

Le serveur tourne sur un vieux PC ou un Raspberry Pi de l'IUT. **Python 3.10 ou plus suffit, rien à installer.** Il :
- reçoit les mesures des cartes ESP32 ;
- calcule l'état de chaque salle : personnes, émargement, Wi-Fi, air, diagnostic ;
- tient le registre des présences (séances, corrections, export) ;
- pilote l'automate en Modbus TCP ;
- sert l'interface de suivi des classes (avec comptes) et le jumeau 3D.

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
| [config.py](config.py) | Adresse de l'automate, débits connus, clé des capteurs, sel des cartes |

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

Toutes ces adresses demandent d'être connecté. Celles du jumeau 3D (`/api/etat`, `/api/flux`, `/api/historique`, `/api/commande`, `/api/simulation/panne`) sont réservées au directeur et à la scolarité.

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
| `POST /api/commande` | `{"auto": false, "niveau": "grande"}` : forcer la ventilation |
| `POST /api/simulation/panne` | `{"panne": "fenetre"}` : provoquer une panne (mode simulation seulement) |

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
```
