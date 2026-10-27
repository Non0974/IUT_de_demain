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
| [ondes.py](ondes.py) | Ondes Wi-Fi (CSI) entre deux cartes : niveau de la salle vide, présence, fichier d'apprentissage |
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
| `ondes` | `salle`, `paquets`, `mouvement`, `turbulence`, `rssi`, `amplitudes` (52) | deux cartes ESP32-S3 (ondes Wi-Fi), toutes les 10 s |

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

Pour chaque salle, le serveur prend les cours de l'emploi du temps, le nombre de personnes attendues et le débit d'air mesuré dans la salle, puis il simule le CO₂ des deux heures suivantes. Toutes les 10 minutes, il compare sa prévision à 30 et 60 minutes avec la mesure, pour savoir à quel point il se trompe.

Le nombre d'étudiants attendus vient du taux de présence appris sur les 14 derniers jours, pour chaque groupe et pour chaque demi-journée de la semaine. Un groupe vu une seule fois reste proche de la moyenne, parce qu'une seule séance varie trop.

Pour les places, un cours commencé est compté (capteurs de la porte, sinon badges, car le Wi-Fi se trompe de 2 ou 3 personnes) et un cours à venir est prévu. La salle est trop petite s'il y a plus d'étudiants que de places, pleine au-dessus de 90 %, et trop grande sous 40 % quand une salle plus petite du même type existe. Une alerte part si une salle a plus de monde que de places pendant 5 minutes en plein cours.

La ventilation de SAR 200 est décidée chaque minute : on essaie les vitesses possibles pour les 20 minutes suivantes, on simule 90 minutes et on garde le plan le moins coûteux (énergie de l'air neuf et du ventilateur, plus une pénalité au-dessus de 800 et 1000 ppm). La petite vitesse est gardée 20 minutes après chaque cours (plus si la salle se vide tard) et le soir, sinon le diagnostic ne peut plus mesurer la décroissance du CO₂.

Si l'air d'un cours va dépasser 1200 ppm, ou s'il y a plus d'étudiants que de places, le serveur regarde chaque salle du même type : libre ou non, assez grande ou non, et l'air qu'elle aurait avec ce cours. Si aucune salle n'est libre, une salle occupée peut proposer un échange, à condition que son cours tienne dans l'autre salle et que l'air reste correct des deux côtés. Le directeur accepte ou ignore dans la page Anticipation.

En simulation, la prévision utilise le même modèle que le bâtiment simulé, donc elle y est forcément bonne. Le vrai test se fera dans la salle réelle.

## Vérification de l'émargement par le CO₂

5 minutes après la fin d'un cours, le serveur calcule avec le CO₂ combien de personnes ont été dans la salle (avec le volume de la salle et son débit d'air) et compare au nombre de badges, enseignant compris. S'il y a beaucoup plus de badges que de personnes, des cartes ont peut-être été badgées pour des absents. S'il y a plus de personnes que de badges, ce sont des oublis ou des personnes extérieures. Dans les deux cas, une alerte « à vérifier » apparaît.

Les 5 premiers cours d'une salle servent à la recaler, sans alerte. Le serveur ne donne pas d'avis si le CO₂ monte trop peu (salle très ventilée) ou si le débit de la salle n'est pas encore mesuré. Sur de vraies salles ([donnees_reelles](../donnees_reelles/README.md)), 6 à 8 cartes en trop sont repérées dans la plupart des salles, mais pas 1 ou 2. En simulation, 6 cartes en trop sont repérées à chaque cours, avec 4 % de fausses alertes sur une semaine normale.

## Retards dus au RER

Quand une ligne qui dessert l'IUT est perturbée (RER D par défaut), le serveur prévient pour les cours qui commencent dans l'heure et demie, par exemple : « RER D perturbé depuis 07h30. Environ 7 retards attendus en Vie de l'entreprise à 08h10, contre 1 d'habitude. » Sur la fiche de la séance, les retards sont expliqués.

La part d'étudiants en retard, ligne perturbée ou non, est apprise sur les séances passées. On ne sait pas qui prend quelle ligne. En vrai, l'info trafic vient de l'API PRIM d'Île-de-France Mobilités : il faut une clé gratuite (prim.iledefrance-mobilites.fr) dans `PRIM_CLE` de `config.py`. Ce n'est pas encore testé avec la vraie API. En simulation, le RER D est perturbé un matin sur quatre et 40 % des étudiants le prennent. Le serveur apprend 7 % de retards en temps normal et 42 % pendant une perturbation.

## Tickets

Dans la page Tickets, on choisit la salle et le problème : table, chaise, feutres, brosse, vidéoprojecteur, câble HDMI, poste informatique, chauffage, éclairage, prise, propreté ou autre. Le ticket va au service concerné (logistique, informatique, maintenance, entretien). Un problème signalé deux fois ne fait qu'un ticket.

Le serveur regarde le prochain cours dans la salle et le nombre d'étudiants attendus. Le ticket est urgent s'il n'y a plus assez de places pour un cours de la journée, ou s'il manque de quoi faire cours (feutres, vidéoprojecteur…) pour un cours dans moins de 2 heures. Sinon il est à faire avant le prochain cours, ou pas pressé. Le ticket indique aussi quand la salle est libre, pour intervenir sans déranger un cours.

Une table manquante enlève 2 places (on a supposé des tables de TD pour 2), une chaise ou un poste 1. Tant que le ticket est ouvert, la capacité et les propositions de salle comptent avec les places qui restent. Dans le test, 2 tables manquent en SAR 122 : la salle passe de 19 à 15 places, le cours de 9h30 attend 16 étudiants, donc le ticket est urgent et la salle est signalée trop petite.

Le serveur ouvre aussi un ticket quand le diagnostic trouve une panne : ventilation, capteur mal placé, comptage faux, ou capteur qui dérive. La dérive n'est prise en compte que dans SAR 200, la seule salle où l'air est purgé le soir avant la mesure. Un ticket fermé n'est pas rouvert avant 12 heures. Les tickets urgents apparaissent dans les alertes du directeur.

## Ondes Wi-Fi

Deux cartes ESP32-S3 mesurent comment les ondes Wi-Fi changent quand quelqu'un bouge dans la salle ([firmware/ondes_wifi](../firmware/README.md#ondes-wifi)). Le serveur apprend le niveau de la salle vide (quand la porte compte 0 personne), puis dit si quelqu'un bouge : mouvement au-dessus de la moyenne de la salle vide plus 4 écarts-types. La fiche d'une séance l'affiche. Si l'émetteur n'est pas reçu, le serveur ne donne pas d'avis.

Avec les vrais capteurs, chaque mesure est gardée avec le nombre de personnes compté à la porte dans `serveur/ondes.csv`. `python outils/ondes_wifi.py serveur/ondes.csv` apprend sur la première moitié et teste sur la deuxième : présence juste ou non, et erreur du comptage comparée à « répondre toujours la moyenne ». En simulation, la relation entre ondes et personnes est inventée, donc le test ne prouve que la chaîne des données. Le vrai résultat viendra de l'essai dans la salle.

## Cartes étudiantes

Pour l'essai réel, on badge une carte sur un lecteur, elle apparaît dans la page Cartes (directeur, scolarité) et on choisit à qui elle est (TP1-01…, nom facultatif). Le lecteur s'allume en vert si la carte est connue, en orange sinon. Le serveur ne garde qu'une empreinte de la carte, et les noms restent dans `serveur/cartes.json` sur le PC.

## Chauffage et éclairage

Le chauffage est en confort pendant un cours et 45 minutes avant, ou dès qu'il y a quelqu'un. Il est réduit le reste de la journée (7 h à 20 h) et en hors-gel la nuit et le week-end. La lumière ne s'allume que quand il y a quelqu'un. SAR 200 est vraiment pilotée (registres 3 et 4 de l'automate). Pour les autres salles, on calcule seulement ce que ça économiserait.

Sur un lundi simulé, SAR 200 consomme 36,6 kWh au lieu de 56,5 avec l'horaire fixe, et les 23 salles 790 kWh au lieu de 1115 (−29 %). Les puissances sont estimées (chauffage 50 W/m², éclairage 8 W/m²) et seront à remplacer par les vraies.

## Assistant IA (en option)

Dans la page Assistant IA, on pose une question en français, par exemple « Qui est absent en SAR 109 ? ». Le serveur l'envoie à Claude (Anthropic), qui lit les données avec 11 outils puis répond. Pour l'activer :

```
pip install anthropic
set ANTHROPIC_API_KEY=sk-ant-...        (clé à créer sur console.anthropic.com, puis relancer le serveur)
```

Sans ça, la page indique que l'assistant est hors ligne et le reste marche.

L'IA ne reçoit aucun nom : chaque étudiant devient ETU-001, ETU-002… et chaque enseignant « Enseignant A, B… », y compris dans la question. Les motifs d'absence et les auteurs des corrections ne sont pas envoyés, et le serveur remet les vrais noms à l'affichage. L'IA a les droits de la personne connectée et ne modifie rien. Une question coûte quelques centimes, avec une limite de 30 questions par heure et par compte. Le modèle (`claude-opus-5-5`) et l'effort se règlent dans `config.py`.

## Ce qu'on a changé après les tests sur données réelles

Voir [donnees_reelles](../donnees_reelles/README.md).
Chaque salle se recale maintenant sur ses 3 premiers départs. Le comptage faux est décidé sur plusieurs départs et pas sur un seul. Le niveau du soir n'est mesuré que si le CO₂ est stable, parce que dans ROBOD le CO₂ d'une salle fermée peut monter la nuit. La décroissance est coupée quand le CO₂ rejoint le bruit du capteur. Et on a ajouté une 5ᵉ cause, le capteur de CO₂ mal placé.

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
python tests/test_ondes.py         ondes Wi-Fi : salle vide apprise, présence, fichier d'apprentissage
```

Les outils pour brancher les vraies données (CELCAT, Wi-Fi de la DSI) sont dans [outils](../outils/README.md).
