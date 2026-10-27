# Serveur CampusTwin

Le serveur tourne sur un vieux PC ou un Raspberry Pi de l'IUT. Il faut Python 3.10 ou plus, rien à installer (sauf pour l'assistant IA). Il :
- reçoit les mesures des cartes ESP32 ;
- calcule l'état de chaque salle : personnes, émargement, Wi-Fi, air, diagnostic ;
- tient le registre des présences (séances, corrections, export) ;
- prévoit le CO₂ et le nombre d'étudiants des prochains cours, pilote la ventilation de SAR 200 et propose des changements de salle ;
- gère les tickets des salles ;
- pilote l'automate en Modbus TCP ;
- sert le site de suivi des classes et le jumeau 3D ;
- répond aux questions en français (assistant IA).

```
python serveur/serveur.py                    vraies cartes et vrai automate (voir config.py)
python serveur/serveur.py --simulation       bâtiment et automate simulés
python serveur/serveur.py --simulation --vitesse 300
```

Puis ouvrir http://localhost:8000. En simulation, les comptes de démo sont `directeur`, `enseignant` et `technique`, mot de passe `demo`.

## Comptes

Avec les vrais capteurs, il faut créer les comptes. Le mot de passe est demandé au clavier et on ne garde qu'une empreinte PBKDF2, dans `serveur/comptes.json` (pas sur GitHub).

```
python serveur/comptes.py ajouter direction --role directeur --nom "Directeur des études"
python serveur/comptes.py ajouter dupont --role enseignant --nom "M. Dupont" --enseignant "DUPONT Jean"
python serveur/comptes.py ajouter technique --role technique --nom "Services techniques"
python serveur/comptes.py liste
```

Le nom donné à `--enseignant` doit être celui de l'emploi du temps.

Dans le dépôt (public), les enseignants s'appellent « Enseignant A, B… ». Pour avoir les vrais noms en local, on crée `serveur/enseignants.json` (pas sur GitHub) :

```
{"Enseignant A": "NOM Prénom", "Enseignant B": "NOM Prénom"}
```

| Rôle | Ce qu'il voit | Ce qu'il peut faire |
| --- | --- | --- |
| `directeur`, `scolarite` | Tout l'IUT, le jumeau 3D | Corriger toutes les séances, exporter |
| `enseignant` | Ses séances, ses classes, les étudiants de ses classes (pour ses cours) | Corriger ses séances, exporter ses classes |
| `technique` | Seulement les tickets | Prendre en charge et fermer les tickets |

Tout le monde peut signaler un problème dans une salle. Un enseignant peut commenter un ticket et fermer celui qu'il a ouvert.

La session dure 10 h. Après 5 mauvais mots de passe en une minute, l'adresse est bloquée une minute.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| [serveur.py](serveur.py) | Serveur web, réception des messages, pilotage de la ventilation |
| [salle.py](salle.py) | État d'une salle : comptage de la porte, badges, émargement, modèle Wi-Fi |
| [estimateur.py](estimateur.py) | Débit d'air réel (deux méthodes), recalage, diagnostic des 5 causes |
| [automate.py](automate.py) | Client Modbus TCP (sans bibliothèque) et règle de ventilation |
| [stockage.py](stockage.py) | Enregistre tous les messages dans `campustwin.db` (SQLite) |
| [registre.py](registre.py) | Registre des présences (`registre.db`) : séances, statuts, corrections, anomalies, tickets, export CSV |
| [suivi.py](suivi.py) | Ce que lit le site, avec les règles d'accès |
| [comptes.py](comptes.py) | Comptes, mots de passe et sessions |
| [planning.py](planning.py) | Emploi du temps de chaque jour, avec les changements de salle acceptés |
| [prevision.py](prevision.py) | Prévisions : personnes attendues et CO₂ de chaque salle sur 2 heures |
| [commande.py](commande.py) | Ventilation de SAR 200 (commande prédictive) et énergie comparée à la règle simple |
| [capacite.py](capacite.py) | Places des salles : chaque cours face aux places de sa salle |
| [reaffectation.py](reaffectation.py) | Changements de salle proposés (air mauvais, salle trop petite), échange de salles |
| [temoin.py](temoin.py) | Vérification de l'émargement par le CO₂ |
| [transports.py](transports.py) | Retards dus au RER : appris, prévus et expliqués ; lien avec l'API PRIM |
| [tickets.py](tickets.py) | Tickets des salles : urgence, échéance, moment pour intervenir, places perdues |
| [ambiance.py](ambiance.py) | Chauffage et éclairage selon l'occupation |
| [assistant.py](assistant.py) | Assistant IA : outils en lecture seule, pseudonymes, appel à l'API Claude |
| [config.py](config.py) | Adresse de l'automate, débits, clé des capteurs, réglages |

## Messages des capteurs

`POST /api/mesure` avec un objet JSON ou une liste d'objets. En-tête `X-Cle` si `CLE_CAPTEURS` est rempli.

| type | champs | envoyé par |
| --- | --- | --- |
| `co2` | `salle`, `co2` (ppm), `temp` (°C, optionnel) | nœud salle, toutes les 30 s |
| `passage` | `salle`, `sens` (+1 entrée, −1 sortie), `confiance` | nœud porte |
| `presence` | `salle`, `presence` (vrai/faux) | nœud porte (radar) |
| `badge` | `salle`, `carte` (empreinte, 16 caractères) | nœud salle |
| `wifi` | `bornes` : `{salle: nombre d'appareils}` | export de la DSI, chaque minute |

Heure : `t` (secondes depuis 1970) si la carte a l'heure exacte, sinon `age_ms` (âge du message s'il a attendu dans la file de la carte).

`POST /api/cartes` : table `{empreinte: {"id": "TP1-03", "groupe": "TP1"}}`, donnée par la scolarité. Les enseignants ont `"groupe": "enseignant"`. Elle est gardée dans `serveur/cartes.json` (pas sur GitHub).

## Adresses du site

Toutes demandent d'être connecté. `/api/etat`, `/api/flux`, `/api/historique`, `/api/commande`, `/api/simulation/panne`, `/api/previsions`, `/api/proposition` et les adresses `/api/cartes/...` sont réservées au directeur et à la scolarité. Le compte `technique` n'a que `/api/tickets`.

| Adresse | Contenu |
| --- | --- |
| `POST /api/connexion` | `{"login", "mot_de_passe"}` : ouvre une session (cookie) |
| `GET /api/tableau` | Tableau de bord : séances en cours, chiffres du jour, alertes |
| `GET /api/seances?date=AAAA-MM-JJ` | Séances d'un jour avec leur émargement |
| `GET /api/seance?id=…` | Une séance : statut de chaque étudiant, anomalies, corrections |
| `POST /api/seance/statut` | `{"seance", "etudiant", "statut", "motif"}` : corriger un statut |
| `GET /api/classes?du=…&au=…` | Bilan de chaque classe sur la période |
| `GET /api/classe?id=TP1&du=…&au=…` | Une classe : étudiants × séances |
| `GET /api/etudiant?id=TP1-03&du=…&au=…` | Fiche d'un étudiant |
| `GET /api/export?classe=TP1&du=…&au=…` | Feuille de présence CSV, avec les demi-journées pour le CFA |
| `GET /api/etat` | État de toutes les salles et de l'automate |
| `GET /api/flux` | Le même état chaque seconde (Server-Sent Events) |
| `GET /api/historique?salle=SAR 200` | CO₂ et personnes de la journée, une valeur par minute |
| `POST /api/commande` | `{"auto": false, "niveau": "grande"}` : forcer la ventilation ; `{"strategie": "predictive"}` ou `"reactive"` |
| `GET /api/previsions` | Prévisions, plan de ventilation, énergie, places des salles, propositions de salle |
| `POST /api/proposition` | `{"action": "accepter", "cours", "salle"}` ou `{"action": "ignorer", "cours"}` |
| `GET /api/tickets` | Tickets avec urgence et échéance, liste des salles et des problèmes possibles |
| `POST /api/tickets` | `{"salle", "objet", "quantite", "detail"}` : signaler un problème |
| `POST /api/tickets/changer` | `{"id", "statut", "texte"}` : prendre en charge, fermer, commenter |
| `GET /api/cartes/inconnues` | Cartes badgées pas encore attribuées |
| `GET /api/cartes/liste` | Cartes enregistrées |
| `POST /api/cartes/associer` | `{"empreinte", "etudiant": "TP2-04", "nom"}` : donner une carte (remplace l'ancienne) |
| `POST /api/cartes/retirer` | `{"empreinte"}` : retirer une carte |
| `GET /api/assistant` | État de l'assistant, questions proposées, conversation en cours |
| `POST /api/assistant` | `{"question": "…"}` ou `{"nouvelle": true}` |
| `POST /api/simulation/panne` | `{"panne": "fenetre"}` : provoquer une panne (simulation seulement) |

## Prévisions

- Pour chaque salle, on prend les cours de l'emploi du temps, le nombre de personnes attendues et le débit d'air mesuré dans la salle, et on simule le CO₂ des 2 heures suivantes. Toutes les 10 min, la prévision à 30 et 60 min est comparée à la mesure.
- Le taux de présence est appris sur les 14 derniers jours, pour chaque groupe et pour chaque demi-journée de la semaine. Un groupe vu une seule fois reste proche de la moyenne. Étudiants attendus = effectif × taux du groupe × effet de la demi-journée.
- Places : pour un cours commencé, on compte les étudiants (porte, sinon badges, car le Wi-Fi se trompe de 2 ou 3 personnes) ; pour un cours à venir, on prend la prévision. La salle est trop petite (plus d'étudiants que de places), pleine (plus de 90 %), adaptée, ou trop grande (moins de 40 % alors qu'une salle plus petite du même type existe). Une alerte part si une salle a plus de monde que de places pendant 5 minutes en plein cours.
- Ventilation de SAR 200 : chaque minute, on essaie les vitesses possibles pour les 20 minutes suivantes, on simule 90 minutes et on garde le plan le moins coûteux (énergie de l'air neuf et du ventilateur, plus une pénalité au-dessus de 800 et 1000 ppm). La petite vitesse est gardée 20 min après chaque cours (plus si la salle se vide tard) et le soir, sinon le diagnostic ne peut plus mesurer la décroissance du CO₂.
- Changement de salle : si l'air d'un cours va dépasser 1200 ppm, ou s'il y a plus d'étudiants que de places, on interroge chaque salle du même type. Chacune répond : libre (avec l'air qu'elle aurait), trop petite, ventilation inconnue, occupée, ou échange possible (son cours tient dans l'autre salle et l'air reste correct des deux côtés). On garde la meilleure salle libre, sinon le meilleur échange. Le directeur accepte ou ignore dans la page Anticipation.
- Limite : en simulation, la prévision utilise le même modèle que le bâtiment simulé, donc elle y est forcément bonne. Le vrai test se fera dans la salle réelle.

## Vérification de l'émargement par le CO₂

5 min après la fin d'un cours, on calcule avec le CO₂ combien de personnes ont été dans la salle (volume de la salle, débit d'air mesuré) et on compare au nombre de badges, enseignant compris.
- Plus de badges que de personnes : des cartes ont peut-être été badgées pour des absents. Plus de personnes que de badges : oublis, ou personnes extérieures. Dans les deux cas, une alerte « à vérifier » apparaît.
- Les 5 premiers cours d'une salle servent à la recaler, sans alerte.
- Pas d'avis si le CO₂ monte trop peu (salle très ventilée) ou si le débit de la salle n'est pas encore mesuré.
- Sur de vraies salles ([donnees_reelles](../donnees_reelles/README.md)) : 6 à 8 cartes en trop sont repérées dans la plupart des salles, pas 1 ou 2.
- En simulation : 6 cartes en trop repérées à chaque cours, 4 % de fausses alertes sur une semaine normale.

## Retards dus au RER

Quand une ligne qui dessert l'IUT est perturbée (RER D par défaut), le serveur prévient pour les cours qui commencent dans l'heure et demie, par exemple : « RER D perturbé depuis 07h30 : environ 7 retards attendus au cours de Vie de l'entreprise (SAR 102, 08h10), au lieu de 1 d'habitude ». Sur la fiche de la séance, les retards sont expliqués.
- La part d'étudiants en retard, ligne perturbée ou non, est apprise sur les séances passées. On ne sait pas qui prend quelle ligne.
- En vrai, on lit l'info trafic de l'API PRIM d'Île-de-France Mobilités. Il faut une clé gratuite (prim.iledefrance-mobilites.fr) dans `PRIM_CLE` de `config.py`. Pas encore testé avec la vraie API.
- En simulation : RER D perturbé un matin sur quatre, 40 % des étudiants le prennent. Le serveur apprend 7 % de retards en temps normal et 42 % pendant une perturbation, et prévoit les retards de chaque cours à 2 ou 3 près.

## Tickets

Page Tickets du site. On choisit la salle et le problème : table, chaise, feutres, brosse, vidéoprojecteur, câble HDMI, poste informatique, chauffage, éclairage, prise, propreté, autre. Le ticket va au service concerné (logistique, informatique, maintenance, entretien).
- Urgence : on regarde le prochain cours dans la salle et le nombre d'étudiants attendus. C'est urgent s'il n'y a plus assez de places pour un cours de la journée, ou s'il manque de quoi faire cours (feutres, vidéoprojecteur…) pour un cours dans moins de 2 h. Sinon c'est « avant le prochain cours » (aujourd'hui ou demain) ou « pas pressé ».
- Le ticket indique quand la salle est libre, pour intervenir sans déranger un cours.
- Une table manquante enlève 2 places (table de TD pour 2, à vérifier), une chaise ou un poste 1. Tant que le ticket est ouvert, la capacité et les propositions de salle comptent avec les places qui restent. Exemple testé : 2 tables manquantes en SAR 122 (15 places au lieu de 19), le cours de 9h30 attend 16 étudiants, le ticket passe en urgent et la salle est signalée trop petite.
- Un problème signalé deux fois ne fait qu'un ticket.
- Le serveur ouvre lui-même un ticket quand le diagnostic trouve une panne : ventilation, capteur mal placé, comptage faux, ou capteur qui dérive (seulement dans SAR 200, la seule salle où l'air est purgé le soir avant la mesure). Il ne le rouvre pas avant 12 h après sa fermeture.
- Les tickets urgents apparaissent dans les alertes du directeur, et la fiche d'une séance affiche ceux de sa salle.

## Cartes étudiantes

Pour l'essai réel : on badge une carte sur un lecteur, elle apparaît dans la page Cartes (directeur, scolarité), et on choisit à qui elle est (TP1-01…, nom facultatif). Le lecteur s'allume en vert (carte connue) ou en orange (carte inconnue). Le serveur ne garde qu'une empreinte de la carte, les noms restent dans `serveur/cartes.json` sur le PC.

## Chauffage et éclairage

- Chauffage : confort pendant un cours et 45 min avant, ou dès qu'il y a quelqu'un ; réduit le reste de la journée (7 h – 20 h) ; hors-gel la nuit et le week-end.
- Éclairage : allumé seulement quand il y a quelqu'un, ou à l'arrivée d'un cours.
- SAR 200 est vraiment pilotée (registres 3 et 4 de l'automate). Pour les autres salles, on calcule ce que ça économiserait.
- Sur un lundi simulé (7 h – 20 h 30) : SAR 200 consomme 36,6 kWh au lieu de 56,5 avec l'horaire fixe ; les 23 salles, 790 kWh au lieu de 1115 (−29 %). Les puissances sont estimées (chauffage 50 W/m², éclairage 8 W/m²), à remplacer par les vraies.

## Assistant IA (en option)

Dans la page Assistant IA, on pose une question en français (« Qui est absent en SAR 109 ? »). Le serveur l'envoie à Claude (Anthropic), qui lit les données avec 11 outils, puis répond.

Pour l'activer :
```
pip install anthropic
set ANTHROPIC_API_KEY=sk-ant-...        (clé à créer sur console.anthropic.com, puis relancer le serveur)
```
Sans ça, la page indique que l'assistant est hors ligne et le reste marche.

- L'IA ne reçoit aucun nom : chaque étudiant devient ETU-001, ETU-002… et chaque enseignant « Enseignant A, B… ». Un nom tapé dans la question est remplacé aussi. Les motifs d'absence et les auteurs des corrections ne sont pas envoyés. Le serveur remet les vrais noms à l'affichage.
- Elle a les droits de la personne connectée : un enseignant n'a que ses séances et ses classes.
- Elle ne modifie rien.
- Coût : quelques centimes par question. 30 questions par heure et par compte, 15 par conversation (`config.py`).
- Réglages (`config.py`) : modèle `claude-opus-5-5`, effort `medium`. Si le modèle refuse une question par erreur, l'API la relance sur le modèle de secours (`fallbacks: "default"`).

## Ce qu'on a changé après les tests sur données réelles

Voir [donnees_reelles](../donnees_reelles/README.md).
- Chaque salle se recale sur ses 3 premiers départs (rapport normal entre les deux méthodes, débit de référence si la ventilation est inconnue).
- Le comptage faux est décidé sur la médiane de plusieurs départs, pas sur un seul.
- Le niveau du soir n'est mesuré que si le CO₂ est stable : dans ROBOD, le CO₂ d'une salle fermée peut monter la nuit.
- La décroissance est coupée quand le CO₂ rejoint le bruit du capteur.
- On a ajouté une 5ᵉ cause : capteur de CO₂ mal placé.

## Tests

```
python tests/test_scenarios.py     une semaine simulée, chaque panne et chaque fraude doit être trouvée
python tests/test_automate.py      échange Modbus et sécurité de l'automate simulé
python tests/test_suivi.py         comptes, droits, registre des présences, corrections, export
python tests/test_prevision.py     prévisions, ventilation, présence apprise, places, changement de salle
python tests/test_assistant.py     assistant IA avec un faux client : aucun nom envoyé, droits, refus
python tests/test_ambiance.py      chauffage et éclairage, énergie comparée à l'horaire fixe
python tests/test_wifi_dsi.py      import du Wi-Fi de la DSI
python tests/test_celcat.py        import d'un export CELCAT
python tests/test_temoin.py        vérification par le CO₂ : fausses alertes, 6 cartes en trop repérées
python tests/test_transports.py    RER D perturbé : retards appris, prévus et expliqués
python tests/test_negociation.py   aucune salle libre : une salle propose un échange
python tests/test_tickets.py       tickets : urgence, places perdues, droits, panne détectée
```

Les outils pour brancher les vraies données (CELCAT, Wi-Fi de la DSI) sont dans [outils](../outils/README.md).
