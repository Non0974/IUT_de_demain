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
| [reaffectation.py](reaffectation.py) | Propositions de changement de salle (air qui va devenir mauvais, salle trop petite) : les salles négocient, échange de salles si aucune n'est libre |
| [temoin.py](temoin.py) | Le CO₂ témoin de l'émargement : combien de personnes ont respiré dans la salle, comparé aux badges |
| [transports.py](transports.py) | RER perturbé : retards appris, prévus et expliqués ; lien avec l'API PRIM d'Île-de-France Mobilités |
| [ambiance.py](ambiance.py) | Chauffage et éclairage selon l'occupation, et énergie face à l'horaire fixe |
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
| `GET /api/cartes/inconnues` | Cartes badgées pas encore attribuées, et à qui on peut les donner |
| `GET /api/cartes/liste` | Cartes enregistrées de la classe et des enseignants |
| `POST /api/cartes/associer` | `{"empreinte", "etudiant": "TP2-04", "nom"}` : donner une carte (elle remplace l'ancienne) |
| `POST /api/cartes/retirer` | `{"empreinte"}` : retirer une carte (perdue) |
| `GET /api/assistant` | L'assistant est-il prêt, questions suggérées, conversation en cours |
| `POST /api/assistant` | `{"question": "…"}` : réponse de l'assistant ; `{"nouvelle": true}` : nouvelle conversation |
| `POST /api/simulation/panne` | `{"panne": "fenetre"}` : provoquer une panne (mode simulation seulement) |

## Jumeau prédictif

- **Prévision.** Pour chaque salle : les cours de l'emploi du temps, le nombre de personnes attendues, et le débit d'air appris par la salle. Le jumeau simule le CO₂ des 2 heures suivantes. Toutes les 10 min, il note sa prévision à 30 et 60 min et la compare à la mesure.
- **Qui viendra.** Le taux de présence est appris sur les 14 derniers jours : celui de chaque groupe, et l'effet de chaque demi-journée de la semaine. Un groupe vu une seule fois garde un taux proche de la moyenne (une séance seule varie trop par hasard). Étudiants attendus = effectif × taux du groupe × effet de la demi-journée.
- **Places des salles.** Chaque cours de la journée face aux places de sa salle : compté pour un cours commencé (capteurs de la porte, sinon badges, car le Wi-Fi se trompe de 2 ou 3 personnes), prévu pour un cours à venir. Salle trop petite (plus d'étudiants que de places), pleine (plus de 90 %), adaptée, ou trop grande (moins de 40 %, alors qu'une salle du même type plus petite existe). Alerte en direct si une salle a plus de monde que de places pendant 5 minutes en plein cours.
- **Ventilation anticipée (SAR 200).** Chaque minute, le jumeau essaie les vitesses possibles pour les 20 minutes suivantes, simule 90 minutes et garde le plan le moins coûteux : énergie (chauffage de l'air neuf + ventilateur) plus une pénalité au-dessus de 800 et 1000 ppm. Il garde la petite vitesse 20 min après chaque cours (plus longtemps si la salle s'est vidée tard, jusqu'au bout de la mesure) et le soir, sinon le diagnostic ne peut plus mesurer la décroissance ni la dérive du capteur.
- **Changement de salle : les salles négocient.** Si l'air d'un cours doit dépasser 1200 ppm, ou s'il y aura plus d'étudiants que de places, la salle interroge chaque salle du même type. Chacune répond avec ses propres données : libre (et l'air qu'elle aurait), trop petite, ventilation inconnue, occupée, ou **échange possible** (son cours tiendrait dans la salle qui a le problème, et l'air resterait correct des deux côtés). On garde la meilleure salle libre, sinon le meilleur échange. Le directeur voit la négociation et accepte ou ignore dans la page Anticipation. Un échange refusé pour l'air est expliqué (« échanger rendrait l'air mauvais »).
- **Limite.** En simulation, la prévision utilise la même physique que le bâtiment simulé : sa précision y est forcément bonne. Le vrai test se fera sur la salle réelle.

## Le CO₂ témoin de l'émargement

5 min après la fin de chaque cours, le jumeau calcule combien de personnes ont respiré dans la salle (bilan de CO₂ : volume de la salle, débit d'air appris) et le compare au nombre de badges, enseignant compris.
- **Plus de badges que de personnes** : cartes badgées pour des absents ? **Plus de personnes que de badges** : oublis, ou personnes extérieures ? Alerte « à vérifier » dans le tableau de bord et sur la fiche de la séance.
- Les 5 premiers cours d'une salle servent à l'apprendre (pas d'alerte). Ensuite, elle se recale sur ses cours sans alerte.
- Pas d'avis si le CO₂ monte trop peu (salle très ventilée) ou si le débit de la salle n'est pas encore mesuré.
- Testé sur de vraies salles ([donnees_reelles](../donnees_reelles/README.md#résultat-3--le-co₂-témoin-de-lémargement)) : repère un groupe de 6 à 8 cartes en trop dans la plupart des salles, pas 1 ou 2.
- En simulation : 6 cartes badgées pour des absents repérées à chaque cours, 4 % de fausses alertes sur une semaine honnête.

## Le RER qui prévient la salle

Quand une ligne qui dessert l'IUT est perturbée (RER D par défaut), le jumeau prévient pour les cours qui commencent dans l'heure et demie : « RER D perturbé depuis 07h30 : environ 7 retards attendus au cours de Vie de l'entreprise (SAR 102, 08h10), au lieu de 1 d'habitude ». Sur la fiche de la séance, les retards sont expliqués.
- Il apprend sur les séances closes la part d'étudiants en retard, ligne perturbée ou non. Aucune donnée personnelle : on ne sait pas qui prend quelle ligne.
- En vrai : messages d'info trafic de l'API PRIM d'Île-de-France Mobilités. Il faut une clé gratuite (prim.iledefrance-mobilites.fr) dans `PRIM_CLE` de `config.py`. **Pas encore testé avec la vraie API** : format et identifiant de la ligne à vérifier avec une clé.
- En simulation : le RER D est perturbé un matin sur quatre, et 40 % des étudiants le prennent. Le jumeau apprend 7 % de retards d'habitude et 42 % pendant une perturbation, et prévoit les retards de chaque cours à 2 ou 3 près.

## Cartes étudiantes

Pour l'essai réel : on badge une carte sur un lecteur, elle apparaît dans la page « Cartes » du site (directeur, scolarité), et on choisit à qui elle est (TP1-01… et un nom, facultatif). Le lecteur répond aussitôt vert (carte connue) ou orange (carte inconnue). Le serveur ne garde qu'une empreinte de la carte ; les noms restent dans `serveur/cartes.json`, sur le PC.

## Chauffage et éclairage selon l'occupation

- **Chauffage :** confort pendant un cours et 45 min avant, ou dès qu'il y a quelqu'un ; réduit le reste de la journée (7 h – 20 h) ; hors-gel la nuit et le week-end.
- **Éclairage :** allumé seulement quand il y a quelqu'un, ou à l'arrivée d'un cours.
- La salle de l'automate (SAR 200) est vraiment pilotée : registres 3 et 4 de l'automate. Pour les autres salles, le jumeau calcule ce que ce pilotage économiserait.
- **Résultat sur un lundi simulé (7 h – 20 h 30)** : SAR 200 consomme 36,6 kWh au lieu de 56,5 avec l'horaire fixe (confort 2,8 h au lieu de 12 h) ; les 23 salles, 790 kWh au lieu de 1115 (−29 %). Puissances estimées (chauffage 50 W/m², éclairage 8 W/m²) : à remplacer par les vraies.

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
python tests/test_ambiance.py      chauffage et éclairage selon l'occupation, énergie face à l'horaire fixe
python tests/test_wifi_dsi.py      import du Wi-Fi de la DSI
python tests/test_celcat.py        import d'un export CELCAT
python tests/test_temoin.py        le CO₂ témoin : fausses alertes sur une semaine honnête, 6 cartes en trop repérées
python tests/test_transports.py    RER D perturbé : retards appris, prévus et expliqués
python tests/test_negociation.py   aucune salle libre : une salle propose un échange
```

Les outils pour brancher les vraies données (CELCAT, Wi-Fi de la DSI) sont dans [outils](../outils/README.md).
