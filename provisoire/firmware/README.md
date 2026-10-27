# Firmware des cartes ESP32

Trois programmes pour la carte Seeed XIAO ESP32S3. Ils envoient leurs mesures au serveur en HTTP (`POST /api/mesure`, JSON), dans le même format que le simulateur ([simulateurs/batiment.py](../simulateurs/batiment.py)).

| Programme | Rôle | Capteurs |
| --- | --- | --- |
| [noeud_salle](noeud_salle/noeud_salle.ino) | CO₂ de la salle et badge des étudiants | SCD-41, PN532, écran e-paper 2,9" |
| [noeud_porte](noeud_porte/noeud_porte.ino) | Compter les entrées et sorties sans caméra | VL53L5CX, MLX90640, HLK-LD2450 |
| [noeud_badge](noeud_badge/noeud_badge.ino) | Lecteur de badge seul, pour l'essai réel dans la salle de la classe | PN532, 2 LED et buzzer (facultatifs) |
| [ondes_wifi](ondes_wifi/ondes_wifi.ino) | Détecter et compter les personnes avec les ondes Wi-Fi, entre deux cartes | aucun, juste deux XIAO ESP32S3 |

Les trois programmes compilent pour la XIAO ESP32S3 (paquet esp32 3.3.3) :

| Programme | Mémoire programme | RAM |
| --- | --- | --- |
| nœud salle | 33 % | 16 % |
| nœud porte | 33 % | 20 % |
| lecteur de badge | 30 % | 14 % |
| ondes Wi-Fi (récepteur / émetteur) | 29 % / 25 % | 13 % |

Ils ne sont pas encore testés sur le matériel, et les seuils de détection sont à régler le jour de l'installation.

## Installer

1. Arduino IDE 2, puis le paquet de cartes esp32 d'Espressif (déjà installé sur le PC de Louay), carte XIAO_ESP32S3.
2. Bibliothèques (gestionnaire de bibliothèques) :
   - nœud salle : Adafruit PN532 1.3.4, GxEPD2 1.6.9 (seulement si l'écran est branché) ;
   - nœud porte : SparkFun VL53L5CX Arduino Library 1.0.3, Adafruit MLX90640 1.1.2.

   La bibliothèque MLX90640 installe aussi des dizaines de bibliothèques Adafruit pour ses exemples, dont on n'a pas besoin. Pour l'éviter en ligne de commande : `arduino-cli lib install --no-deps`.
3. Dans chaque dossier, copier `config.exemple.h` en `config.h` et le remplir : Wi-Fi, adresse du serveur, salle. `config.h` n'est pas envoyé sur GitHub.
4. Téléverser, puis regarder le moniteur série (115200 bauds).

## Nœud salle

| Élément | Broches XIAO |
| --- | --- |
| SCD-41 et PN532 (I2C, Qwiic) | D4 = SDA, D5 = SCL, 3,3 V |
| PN532 IRQ / RESET | D6 / D7 (PN532 réglé en mode I2C avec ses interrupteurs) |
| Écran e-paper (SPI) | D8 = SCK, D10 = MOSI, D1 = CS, D2 = DC, D3 = RST, D0 = BUSY |

- Le CO₂ est envoyé toutes les 30 s. L'analyse des données réelles a montré qu'il en faut au moins une par minute.
- L'auto-calibration du SCD-41 est coupée. Sinon, le capteur se recale tout seul sur 400 ppm et cache sa dérive (vu dans ROBOD). C'est le serveur qui vérifie la dérive chaque soir.
- Carte étudiante : on lit le numéro (UID) de la carte et on n'envoie que son empreinte : SHA-256 du sel + numéro, 16 caractères. Le numéro lui-même ne quitte jamais la carte. Le sel doit être le même dans `config.h` et dans `serveur/config.py`.
- Si le Wi-Fi tombe, les messages attendent dans une file (60 messages) et partent avec leur âge. Le serveur recalcule l'heure.

## Lecteur de badge seul

Pour l'essai réel, pas de matériel en plus : on charge ce programme sur la XIAO et le PN532 du nœud salle (écran débranché), on met la salle du cours dans `config.h`, et on pose le lecteur à l'entrée de la salle de la classe. Les LED et le buzzer viennent du stock de l'IUT ; sans eux, le lecteur marche aussi, mais sans signal pour l'étudiant.

| Élément | Broches XIAO |
| --- | --- |
| PN532 (I2C) | D4 = SDA, D5 = SCL, D6 = IRQ, D7 = RESET, 3,3 V (interrupteurs du PN532 en mode I2C) |
| LED verte, LED rouge | D1, D2, chacune avec une résistance de 220 Ω |
| Buzzer actif 3,3 V | D3 |

- Le badge part tout de suite au serveur, qui répond si la carte est connue.
- Vert + 1 bip : badge enregistré. Orange + 2 bips : carte inconnue, à enregistrer dans la page « Cartes » du site. Rouge qui clignote : serveur injoignable, le badge est gardé (40 au plus) et renvoyé toutes les 10 s.
- Comme le nœud salle, il n'envoie qu'une empreinte de la carte, jamais son numéro.

## Ondes Wi-Fi

C'est notre idée la plus nouvelle : compter les personnes sans capteur, juste avec les ondes Wi-Fi. Deux cartes XIAO ESP32S3 se parlent. L'émetteur envoie 50 petits paquets par seconde (ESP-NOW). Le récepteur lit pour chaque paquet le CSI, c'est-à-dire comment le signal arrive sur chacune des 52 sous-porteuses du canal. Quand quelqu'un bouge entre les deux cartes, les ondes rebondissent autrement et le CSI change. Le principe vient de projets comme ESPectre et RuView, et de travaux de recherche (Carnegie Mellon a retrouvé la posture des gens avec le Wi-Fi).

Le même programme sert aux deux cartes, on choisit le rôle avec `ROLE_EMETTEUR` dans `config.h`. On pose les deux cartes à deux coins opposés de la salle. Elles se connectent au même réseau (partage de connexion d'un téléphone ou petite box), ce qui les met sur le même canal. Le Wi-Fi de l'université n'est pas utilisé pour la mesure. Le récepteur envoie toutes les 10 s le mouvement mesuré et l'amplitude moyenne de chaque sous-porteuse (`type: "ondes"`).

Ce qu'on veut tester : dans SAR 200, le serveur garde chaque mesure avec le nombre de personnes compté à la porte (`serveur/ondes.csv`), puis `python outils/ondes_wifi.py serveur/ondes.csv` dit si les ondes voient la présence et à combien près elles comptent. D'après ces projets, la présence devrait marcher. Compter sera plus dur, il faudra sans doute plus de deux cartes.

## Nœud porte

| Élément | Broches XIAO | Où le placer |
| --- | --- | --- |
| VL53L5CX (I2C 0) | D4 = SDA, D5 = SCL | Au plafond, au-dessus de la porte, regarde le sol |
| MLX90640 (I2C 1) | D8 = SDA, D9 = SCL | À côté du ToF, regarde le sol |
| HLK-LD2450 (UART) | D7 = RX (← TX du radar), D6 = TX, 5 V | Sur le mur côté salle, près de la porte |

Comment ça marche :
1. Le ToF et la caméra thermique voient la zone de la porte coupée en deux : côté couloir et côté salle. Une personne qui passe allume d'abord un côté puis l'autre, ce qui donne le sens. Le nombre de silhouettes donne le nombre de personnes, par exemple deux de front.
2. Le radar donne son avis sur le sens, d'après la vitesse des cibles près de la porte, et dit s'il reste quelqu'un dans la salle.
3. Fusion : vote à la majorité dans une fenêtre de 1,5 s. Si les capteurs ne sont pas d'accord, on ne compte rien.
4. Au démarrage (personne sous la porte pendant 10 s), le ToF apprend la distance du sol et la caméra apprend la température du fond.
5. Présence : si le radar ne voit plus personne pendant 2 min, le serveur remet le compteur à zéro. Ça rattrape les sorties ratées.

Réglages dans `config.h` :
- `SEUIL_TOF_MM`, `SEUIL_THERMIQUE_C` : sensibilité des capteurs ;
- `TOF_SALLE_EN_BAS`, `THERMIQUE_SALLE_EN_BAS` : quel côté de l'image est la salle ;
- `RADAR_SIGNE` : sens de la vitesse du radar.

Pour les vérifier : passer 20 fois (10 entrées, 10 sorties) et comparer avec le moniteur série.
