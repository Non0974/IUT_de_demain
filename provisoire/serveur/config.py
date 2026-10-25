"""Réglages du serveur. À adapter le jour de l'installation à l'IUT."""

PORT_WEB = 8000

# Clé que les cartes ESP32 envoient dans l'en-tête X-Cle (vide = pas de contrôle, pour les essais)
CLE_CAPTEURS = ''

# Sel du hachage des numéros de carte étudiante. Le serveur ne garde jamais le numéro lui-même.
# À changer et à garder secret (même valeur dans le firmware du nœud salle).
SEL_CARTES = 'campustwin-demo'

# Automate S7-1200 (MB_SERVER, Modbus TCP)
AUTOMATE_IP = '192.168.0.10'
AUTOMATE_PORT = 502
AUTOMATE_PERIODE = 1.0          # s entre deux échanges

# Salle qui pilote l'automate (la maquette reproduit sa ventilation)
SALLE_AUTOMATE = 'SAR 200'

# Débits connus de la ventilation (m3/h, fuites comprises) selon la commande de l'automate.
# Pour les autres salles, le débit de référence est appris pendant le recalage.
DEBITS = {
    'SAR 200': {'arret': 25, 'petite': 375, 'grande': 725},
}

# Recalage : None = à apprendre sur les premiers départs. On peut forcer une valeur connue.
BIAIS_CONNU = {}

G_PERSONNE = 0.018              # m3/h de CO2 par personne assise
C_EXT = 420                     # ppm

# Fichiers de la base de données : messages des capteurs, et registre des présences
BASE = 'campustwin.db'
BASE_REGISTRE = 'registre.db'
