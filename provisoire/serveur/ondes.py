"""Compter avec les ondes Wi-Fi (CSI) : deux cartes ESP32-S3 se parlent, le récepteur mesure comment le
signal change quand quelqu'un bouge entre elles (firmware/ondes_wifi).

Toutes les 10 s, le récepteur envoie un « mouvement » (variation du signal sur 10 s). Le serveur :
  - apprend le niveau de la salle vide (comptage de la porte à 0, ou pas de cours et personne au Wi-Fi) ;
  - dit s'il y a quelqu'un qui bouge : mouvement au-dessus de moyenne + 4 écarts-types de la salle vide ;
  - garde chaque mesure avec le nombre de personnes comptées à la porte (serveur/ondes.csv), pour
    apprendre ensuite à compter avec les ondes (outils/ondes_wifi.py).
On ne sait pas encore si les ondes comptent bien dans une vraie salle de cours : c'est ce qu'on veut tester.
"""

from collections import deque
from datetime import datetime
from statistics import mean, pstdev

VIDE_MIN = 12              # mesures de salle vide (2 min) avant de donner un avis
VIDE_GARDE = 90            # on garde les 90 dernières mesures de salle vide (15 min)
ECARTS = 4                 # seuil = moyenne + 4 écarts-types de la salle vide
PAQUETS_MIN = 100          # en dessous (sur 10 s), l'émetteur est éteint ou trop loin
VALIDITE = 60              # s : une mesure plus vieille n'est plus affichée
NB_AMPLITUDES = 52


class Ondes:
    def __init__(self):
        self.derniere = None
        self.vide = deque(maxlen=VIDE_GARDE)

    def seuil(self):
        if len(self.vide) < VIDE_MIN:
            return None
        m = mean(self.vide)
        return m + ECARTS * max(pstdev(self.vide), 0.05 * m, 1e-3)

    def mesurer(self, t, message, salle_vide):
        """message : {'paquets', 'mouvement', 'turbulence', 'rssi', 'amplitudes'} ; salle_vide : vrai si
        on sait que la salle est vide (sert à apprendre le niveau de la salle vide)."""
        paquets = int(message.get('paquets', 0))
        mouvement = float(message.get('mouvement', 0))
        recu = paquets >= PAQUETS_MIN
        if recu and salle_vide:
            self.vide.append(mouvement)
        seuil = self.seuil()
        self.derniere = {
            't': t, 'paquets': paquets, 'mouvement': mouvement,
            'turbulence': float(message.get('turbulence', 0)), 'rssi': float(message.get('rssi', 0)),
            'seuil': seuil, 'presence': (mouvement > seuil) if recu and seuil is not None else None,
            'etat': 'emetteur' if not recu else 'apprentissage' if seuil is None else 'ok',
        }
        return self.derniere

    def etat(self, t):
        d = self.derniere
        if not d or t - d['t'] > VALIDITE:
            return None
        return {k: d[k] for k in ('mouvement', 'seuil', 'presence', 'paquets', 'etat')}


ENTETE = ['heure', 'salle', 'paquets', 'mouvement', 'turbulence', 'rssi', 'personnes_porte', 'personnes_wifi',
          'cours_en_cours'] + [f'a{k}' for k in range(NB_AMPLITUDES)]


def ligne_csv(t, salle, message, personnes_porte, personnes_wifi, cours_en_cours):
    """Une ligne du fichier d'apprentissage : la mesure des ondes et le vrai nombre de personnes."""
    amplitudes = list(message.get('amplitudes') or [])[:NB_AMPLITUDES]
    amplitudes += [''] * (NB_AMPLITUDES - len(amplitudes))
    return [datetime.fromtimestamp(t).isoformat(timespec='seconds'), salle, message.get('paquets', 0),
            message.get('mouvement', 0), message.get('turbulence', 0), message.get('rssi', 0),
            '' if personnes_porte is None else personnes_porte,
            '' if personnes_wifi is None else personnes_wifi, int(cours_en_cours)] + amplitudes
