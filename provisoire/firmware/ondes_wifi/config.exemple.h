// Copier ce fichier en config.h et le remplir (config.h n'est pas mis sur GitHub).
// Le même programme sert aux deux cartes : seul ROLE_EMETTEUR change.

#pragma once

#define ROLE_EMETTEUR   0                 // 1 : la carte qui envoie les paquets, 0 : la carte qui mesure

// Les deux cartes se connectent au même réseau (partage de connexion d'un téléphone, petite box) :
// elles sont alors sur le même canal Wi-Fi. Le récepteur s'en sert aussi pour envoyer ses mesures.
// Sans réseau (WIFI_NOM vide), les deux cartes se mettent sur CANAL, mais rien n'est envoyé au serveur.
#define WIFI_NOM        "routeur-campustwin"
#define WIFI_MOT_DE_PASSE "a-changer"
#define CANAL           6

#define SERVEUR_URL     "http://192.168.0.2:8000"   // adresse du PC qui fait tourner serveur.py
#define CLE_CAPTEURS    ""                          // même valeur que CLE_CAPTEURS dans serveur/config.py
#define NTP_SERVEUR     "pool.ntp.org"

#define SALLE           "SAR 200"

// Adresse donnée à l'émetteur, pour que le récepteur ne garde que ses paquets.
// Même valeur sur les deux cartes. Une adresse différente par salle.
#define EMETTEUR_MAC    { 0x1a, 0x00, 0x00, 0x00, 0x02, 0x00 }

#define PAQUETS_PAR_SECONDE 50                      // émetteur
#define PERIODE_ENVOI_MS    10000                   // récepteur : une mesure toutes les 10 s
