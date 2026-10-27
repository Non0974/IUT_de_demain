"""Automate S7-1200 simulé : un serveur Modbus TCP avec la même logique que le programme SCL
(automate/CampusTwin.scl). Sert à tester le serveur sans l'automate.

    python simulateurs/automate.py --port 5020
"""

import socketserver
import struct
import threading
import time

REGISTRES = 32
PERIODE_VANNE = 10.0     # s : l'électrovanne s'ouvre une fraction de cette période
PERIODE_RADIATEUR = 60.0  # s : en réduit, le radiateur de la maquette chauffe 40 % de cette période
PART_REDUIT = 0.4
DELAI_VIE = 5.0          # s sans nouveau compteur de vie du serveur = communication perdue


class AutomateSimule:
    def __init__(self):
        self.hr = [0] * REGISTRES
        self.verrou = threading.Lock()
        self.arret_urgence = False     # bouton coup de poing (entrée %I0.0 sur le vrai automate)
        self.auto = True               # commutateur Manu/Auto (%I0.1)
        self.vie_serveur = None
        self.derniere_vie = 0.0
        self.vie = 0
        self.debut = time.time()

    def cycle(self):
        """Un cycle de l'automate (OB1), appelé toutes les 100 ms."""
        with self.verrou:
            maintenant = time.time()
            if self.hr[0] != self.vie_serveur:
                self.vie_serveur = self.hr[0]
                self.derniere_vie = maintenant
            comm_perdue = maintenant - self.derniere_vie > DELAI_VIE
            consigne = min(self.hr[1], 2)
            personnes = min(self.hr[2], 30)
            if self.arret_urgence:
                vitesse, vanne = 0, False
            elif comm_perdue:
                vitesse, vanne = 1, False            # secours : petite vitesse, pas d'injection
            elif self.auto:
                vitesse = consigne
                vanne = (maintenant - self.debut) % PERIODE_VANNE < PERIODE_VANNE * personnes / 30
            else:
                vitesse, vanne = 1, False            # mode manuel : petite vitesse
            # Éclairage et chauffage : l'automate garde la main sur la sécurité
            if self.arret_urgence:
                eclairage, chauffage = True, 0       # lumière allumée pour évacuer, chauffage coupé
            elif comm_perdue:
                eclairage, chauffage = True, 1       # serveur muet : lumière et chauffage réduit
            elif self.auto:
                eclairage, chauffage = bool(self.hr[3]), min(self.hr[4], 2)
            else:
                eclairage, chauffage = True, 2       # mode manuel : quelqu'un est là
            radiateur = chauffage == 2 or (chauffage == 1 and (maintenant - self.debut) % PERIODE_RADIATEUR < PERIODE_RADIATEUR * PART_REDUIT)
            mot = (self.auto << 0) | (self.arret_urgence << 1) | ((vitesse > 0) << 2) | (vanne << 3) | (comm_perdue << 4) \
                | (eclairage << 5) | (radiateur << 6)
            self.vie = (self.vie + 1) % 65536
            self.hr[10:14] = [mot, vitesse, self.vie, chauffage]

    def boucle(self):
        while True:
            self.cycle()
            time.sleep(0.1)


def creer_serveur(automate, port):
    class Gestionnaire(socketserver.BaseRequestHandler):
        def handle(self):
            while True:
                entete = self._lire(7)
                if not entete:
                    return
                tid, _, longueur, unite = struct.unpack('>HHHB', entete)
                pdu = self._lire(longueur - 1)
                fonction = pdu[0]
                with automate.verrou:
                    if fonction == 3:                                   # lire des registres
                        adr, n = struct.unpack('>HH', pdu[1:5])
                        valeurs = automate.hr[adr:adr + n]
                        reponse = struct.pack('>BB', 3, 2 * n) + struct.pack(f'>{n}H', *valeurs)
                    elif fonction == 16:                                # écrire des registres
                        adr, n, _ = struct.unpack('>HHB', pdu[1:6])
                        automate.hr[adr:adr + n] = struct.unpack(f'>{n}H', pdu[6:6 + 2 * n])
                        reponse = struct.pack('>BHH', 16, adr, n)
                    elif fonction == 6:                                 # écrire un registre
                        adr, v = struct.unpack('>HH', pdu[1:5])
                        automate.hr[adr] = v
                        reponse = pdu[:5]
                    else:
                        reponse = struct.pack('>BB', fonction | 0x80, 1)
                self.request.sendall(struct.pack('>HHHB', tid, 0, len(reponse) + 1, unite) + reponse)

        def _lire(self, n):
            donnees = b''
            while len(donnees) < n:
                morceau = self.request.recv(n - len(donnees))
                if not morceau:
                    return None
                donnees += morceau
            return donnees

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    serveur = socketserver.ThreadingTCPServer(('0.0.0.0', port), Gestionnaire)
    serveur.daemon_threads = True
    return serveur


def demarrer(port=5020):
    automate = AutomateSimule()
    threading.Thread(target=automate.boucle, daemon=True, name='automate-cycle').start()
    serveur = creer_serveur(automate, port)
    threading.Thread(target=serveur.serve_forever, daemon=True, name='automate-modbus').start()
    return automate, serveur


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='Automate S7-1200 simulé (Modbus TCP)')
    p.add_argument('--port', type=int, default=5020)
    a = p.parse_args()
    automate, _ = demarrer(a.port)
    print(f'Automate simulé sur le port {a.port}. Entrée : u = arrêt d\'urgence, m = Manu/Auto, q = quitter.')
    while True:
        cmd = input().strip().lower()
        if cmd == 'u':
            automate.arret_urgence = not automate.arret_urgence
            print('Arrêt d\'urgence', 'ENFONCÉ' if automate.arret_urgence else 'relâché')
        elif cmd == 'm':
            automate.auto = not automate.auto
            print('Mode', 'auto' if automate.auto else 'manuel')
        elif cmd == 'q':
            break
