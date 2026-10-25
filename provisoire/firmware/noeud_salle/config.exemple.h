// Copier ce fichier en config.h et le remplir (config.h n'est pas mis sur GitHub).

#pragma once

#define WIFI_NOM        "routeur-campustwin"
#define WIFI_MOT_DE_PASSE "a-changer"

#define SERVEUR_URL     "http://192.168.0.2:8000"   // adresse du PC qui fait tourner serveur.py
#define CLE_CAPTEURS    ""                          // même valeur que CLE_CAPTEURS dans serveur/config.py
#define SEL_CARTES      "campustwin-demo"           // même valeur que SEL_CARTES dans serveur/config.py
#define NTP_SERVEUR     "pool.ntp.org"              // ou l adresse du PC serveur s il n y a pas internet

#define SALLE           "SAR 200"
#define PERIODE_CO2_S   30          // une mesure toutes les 30 s (au moins une par minute, voir donnees_reelles)
#define AVEC_ECRAN      1           // 1 si l'écran e-paper est branché
