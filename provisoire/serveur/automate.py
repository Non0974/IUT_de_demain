"""Échange avec l'automate S7-1200 en Modbus TCP (bloc MB_SERVER côté automate).

Registres (holding registers, adresse 0 = 40001 dans TIA Portal) :
  écrits par le serveur        0 : compteur de vie (+1 à chaque échange)
                               1 : consigne de ventilation (0 arrêt, 1 petite, 2 grande)
                               2 : personnes à simuler sur la maquette (0 à 30, injection de CO2)
                               3 : éclairage demandé (0 éteint, 1 allumé)
                               4 : chauffage demandé (0 hors-gel, 1 réduit, 2 confort)
  lus par le serveur          10 : état (bit 0 auto, bit 1 arrêt d'urgence, bit 2 ventilateur en marche,
                                     bit 3 électrovanne CO2 ouverte, bit 4 communication perdue,
                                     bit 5 éclairage allumé, bit 6 radiateur en marche)
                              11 : vitesse appliquée (0, 1, 2)
                              12 : compteur de vie de l'automate
                              13 : chauffage appliqué (0, 1, 2)
Pas de bibliothèque : le protocole Modbus TCP tient en quelques lignes.
"""

import socket
import struct
import threading
import time

NIVEAUX = ['arret', 'petite', 'grande']
CHAUFFAGES = ['hors_gel', 'reduit', 'confort']


class ClientModbus:
    def __init__(self, ip, port=502, unite=1, delai=2.0):
        self.ip, self.port, self.unite, self.delai = ip, port, unite, delai
        self.sock = None
        self.transaction = 0

    def _connecter(self):
        if self.sock is None:
            self.sock = socket.create_connection((self.ip, self.port), timeout=self.delai)

    def fermer(self):
        if self.sock:
            self.sock.close()
        self.sock = None

    def _requete(self, pdu):
        self._connecter()
        self.transaction = (self.transaction + 1) % 65536
        mbap = struct.pack('>HHHB', self.transaction, 0, len(pdu) + 1, self.unite)
        self.sock.sendall(mbap + pdu)
        entete = self._recevoir(7)
        tid, _, longueur, _ = struct.unpack('>HHHB', entete)
        reponse = self._recevoir(longueur - 1)
        if tid != self.transaction:
            raise IOError('Réponse Modbus inattendue')
        if reponse[0] & 0x80:
            raise IOError(f'Exception Modbus {reponse[1]}')
        return reponse

    def _recevoir(self, n):
        donnees = b''
        while len(donnees) < n:
            morceau = self.sock.recv(n - len(donnees))
            if not morceau:
                raise IOError('Connexion fermée par l\'automate')
            donnees += morceau
        return donnees

    def lire(self, adresse, nombre):
        r = self._requete(struct.pack('>BHH', 3, adresse, nombre))
        return list(struct.unpack(f'>{nombre}H', r[2:2 + 2 * nombre]))

    def ecrire(self, adresse, valeurs):
        pdu = struct.pack('>BHHB', 16, adresse, len(valeurs), 2 * len(valeurs)) + struct.pack(f'>{len(valeurs)}H', *valeurs)
        self._requete(pdu)


def niveau_automatique(personnes, co2, heure, dernier_cours_fin):
    """Ce que la ventilation doit faire (même logique que le jumeau)."""
    if co2 is not None and co2 >= 1200:
        return 'grande'
    if personnes > 0:
        return 'petite' if personnes <= 15 else 'grande'
    if dernier_cours_fin is not None and 7.9 <= heure <= dernier_cours_fin + 2.75:
        return 'petite'          # entre les cours, puis purge après le dernier
    return 'arret'


class PontAutomate:
    """Envoie la consigne à l'automate et lit son état, dans un fil à part."""

    def __init__(self, ip, port, periode=1.0):
        self.client = ClientModbus(ip, port)
        self.periode = periode
        self.consigne = 'petite'
        self.personnes_maquette = 0
        self.eclairage = True
        self.chauffage = 'reduit'
        self.vie = 0
        self.etat = {'connecte': False, 'erreur': 'pas encore contacté'}
        self.verrou = threading.Lock()
        self.arret = False

    def demarrer(self):
        threading.Thread(target=self._boucle, daemon=True, name='automate').start()

    def _boucle(self):
        while not self.arret:
            try:
                with self.verrou:
                    ecrits = [NIVEAUX.index(self.consigne), int(self.personnes_maquette), int(self.eclairage),
                              CHAUFFAGES.index(self.chauffage)]
                self.vie = (self.vie + 1) % 65536
                self.client.ecrire(0, [self.vie, *ecrits])
                mot, vitesse, vie_api, chauffage = self.client.lire(10, 4)
                self.etat = {
                    'connecte': True, 'erreur': None,
                    'auto': bool(mot & 1), 'arret_urgence': bool(mot & 2), 'ventilateur': bool(mot & 4),
                    'electrovanne': bool(mot & 8), 'comm_perdue': bool(mot & 16),
                    'eclairage': bool(mot & 32), 'radiateur': bool(mot & 64),
                    'vitesse': NIVEAUX[vitesse] if vitesse < 3 else '?', 'vie': vie_api,
                    'chauffage': CHAUFFAGES[chauffage] if chauffage < 3 else '?',
                    'consigne': self.consigne,
                }
            except (OSError, IOError, struct.error) as e:
                self.client.fermer()
                self.etat = {'connecte': False, 'erreur': str(e) or e.__class__.__name__, 'consigne': self.consigne}
            time.sleep(self.periode)

    def regler(self, consigne=None, personnes=None, eclairage=None, chauffage=None):
        with self.verrou:
            if consigne in NIVEAUX:
                self.consigne = consigne
            if personnes is not None:
                self.personnes_maquette = max(0, min(30, personnes))
            if eclairage is not None:
                self.eclairage = bool(eclairage)
            if chauffage in CHAUFFAGES:
                self.chauffage = chauffage
