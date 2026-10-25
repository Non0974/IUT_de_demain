# Automate S7-1200 — maquette de ventilation

L'automate pilote la maquette, une boîte de 60 L qui reproduit la salle SAR 200 :
- le ventilateur (2 vitesses) joue la ventilation ;
- l'électrovanne de CO₂ joue les occupants : plus il y a de personnes dans la vraie salle, plus elle s'ouvre longtemps.

Le serveur CampusTwin lui envoie la consigne en Modbus TCP. L'automate garde la main sur la sécurité : arrêt d'urgence, mode manuel, perte de communication.

Le programme est dans [CampusTwin.scl](CampusTwin.scl). La même logique est écrite en Python dans [simulateurs/automate.py](../simulateurs/automate.py), ce qui permet de tester le serveur sans l'automate.

**À vérifier dans TIA Portal :** le fichier SCL n'a pas pu être compilé ici, faute de TIA Portal sur le PC.

## Matériel

CPU 1212C AC/DC/RLY (6ES7212-1BE40-0XB0) : 8 entrées 24 V, 6 sorties relais.

| Variable | Adresse | Branchement |
| --- | --- | --- |
| `AU` | %I0.0 | Arrêt d'urgence, contact à **ouverture** (TRUE = tout va bien) |
| `Auto` | %I0.1 | Commutateur Manu/Auto (TRUE = Auto) |
| `Couvercle` | %I0.2 | Micro-interrupteur du couvercle (TRUE = fermé) |
| `Petite` | %Q0.0 | Relais petite vitesse du ventilateur |
| `Grande` | %Q0.1 | Relais grande vitesse du ventilateur |
| `Vanne` | %Q0.2 | Électrovanne CO₂ 24 V, normalement fermée |
| `VoyantAuto` | %Q0.3 | Voyant vert |
| `VoyantDefaut` | %Q0.4 | Voyant rouge (fixe : arrêt d'urgence ; clignote : serveur muet) |

Alimentation 24 V : Mean Well HDR-30-24.

**Sécurité CO₂ :**
- l'électrovanne est aussi coupée en câblage par le contact d'arrêt d'urgence (en série avec son alimentation), pas seulement par le programme ;
- bouteille de 500 g maximum ;
- détendeur réglé au plus bas.

## Ce que fait le programme

| Situation | Ventilateur | Électrovanne |
| --- | --- | --- |
| Arrêt d'urgence enfoncé | arrêt | fermée |
| Plus de nouvelles du serveur depuis 5 s | petite vitesse (secours) | fermée |
| Mode manuel | petite vitesse | fermée |
| Mode auto | consigne du serveur (0, 1 ou 2) | ouverte (personnes / 30) × 10 s, toutes les 10 s, couvercle fermé |

Pour changer de vitesse, le moteur est coupé 0,5 s : les deux relais ne sont jamais fermés ensemble.

## Registres Modbus

L'automate est **serveur** Modbus TCP (bloc MB_SERVER, port 502) ; le PC CampusTwin est client.

| Registre (indice / TIA) | Sens | Contenu |
| --- | --- | --- |
| 0 / 40001 | PC → automate | Compteur de vie du serveur (change à chaque échange, 1 fois par seconde) |
| 1 / 40002 | PC → automate | Consigne : 0 arrêt, 1 petite, 2 grande |
| 2 / 40003 | PC → automate | Personnes à simuler sur la maquette (0 à 30) |
| 10 / 40011 | automate → PC | État : bit 0 auto, bit 1 arrêt d'urgence, bit 2 ventilateur en marche, bit 3 électrovanne ouverte, bit 4 communication perdue |
| 11 / 40012 | automate → PC | Vitesse appliquée (0, 1, 2) |
| 12 / 40013 | automate → PC | Compteur de vie de l'automate |

## Mise en service dans TIA Portal

1. Créer le projet avec la CPU 1212C, et donner une adresse IP fixe à l'interface PROFINET (par exemple `192.168.0.10`, la même que `AUTOMATE_IP` dans [serveur/config.py](../serveur/config.py)).
2. Créer la table de variables avec les 8 variables ci-dessus.
3. Dans *Sources externes*, ajouter `CampusTwin.scl`, puis clic droit > *Générer les blocs à partir de la source*.
4. Vérifier `Connexion.InterfaceId` dans `DB_Echange` : c'est l'identifiant matériel de l'interface PROFINET (64 en général, visible dans les propriétés de l'interface).
5. Si TIA ne trouve pas `MB_SERVER` à la génération : glisser une fois l'instruction *Communication > Autres > MODBUS TCP > MB_SERVER* dans un bloc, puis régénérer.
6. Charger dans l'automate et tester avec le serveur :

   ```
   python serveur/serveur.py
   ```

   Le site affiche l'état de l'automate. Le compteur de vie de l'automate doit augmenter.

## Tester sans l'automate

```
python simulateurs/automate.py --port 5020
```

Puis mettre `AUTOMATE_IP = '127.0.0.1'` et `AUTOMATE_PORT = 5020` dans `serveur/config.py`.

Le serveur lancé avec `--simulation` démarre cet automate simulé tout seul. Dans la console de l'automate simulé : `u` appuie ou relâche l'arrêt d'urgence, `m` bascule Manu/Auto.
