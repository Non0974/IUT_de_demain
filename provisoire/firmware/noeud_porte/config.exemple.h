// Copier ce fichier en config.h et le remplir (config.h n'est pas mis sur GitHub).

#pragma once

#define WIFI_NOM          "routeur-campustwin"
#define WIFI_MOT_DE_PASSE "a-changer"
#define SERVEUR_URL       "http://192.168.0.2:8000"
#define CLE_CAPTEURS      ""
#define NTP_SERVEUR       "pool.ntp.org"
#define SALLE             "SAR 200"

// Réglages de la détection (à ajuster le jour de l'installation, voir README)
#define SEUIL_TOF_MM       600    // une personne : au moins 60 cm plus haut que le sol vu à vide
#define SEUIL_THERMIQUE_C  2.5    // une personne : au moins 2,5 °C au-dessus du fond
#define TOF_SALLE_EN_BAS   1      // 1 si les lignes 4 à 7 du ToF sont côté salle, 0 sinon
#define THERMIQUE_SALLE_EN_BAS 1  // 1 si les lignes 12 à 23 de la caméra thermique sont côté salle
#define RADAR_SIGNE        1      // 1 si une vitesse positive du radar veut dire "entre dans la salle", -1 sinon
#define FENETRE_FUSION_MS  1500   // les avis des capteurs sur un même passage arrivent dans cet intervalle
