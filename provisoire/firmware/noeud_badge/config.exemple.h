// Copier ce fichier en config.h et le remplir (config.h n'est pas mis sur GitHub).

#pragma once

#define WIFI_NOM        "routeur-campustwin"
#define WIFI_MOT_DE_PASSE "a-changer"

#define SERVEUR_URL     "http://192.168.0.2:8000"   // adresse du PC qui fait tourner serveur.py
#define CLE_CAPTEURS    ""                          // même valeur que CLE_CAPTEURS dans serveur/config.py
#define SEL_CARTES      "campustwin-demo"           // même valeur que SEL_CARTES dans serveur/config.py
#define NTP_SERVEUR     "pool.ntp.org"              // ou l adresse du PC serveur s il n y a pas internet

#define SALLE           "SAR 102"

// Voyants et buzzer (une résistance de 220 ohms en série avec chaque LED)
#define LED_VERTE       D1
#define LED_ROUGE       D2
#define BUZZER          D3                          // buzzer actif 3,3 V
