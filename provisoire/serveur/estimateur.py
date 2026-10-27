"""Débit d'air réel d'une salle et diagnostic des causes d'un air mauvais.

Deux méthodes indépendantes (bilan de masse du CO2, V dC/dt = N G - Q (C - Cext)) :
  - salle occupée : bilan intégré sur 10 min, avec le comptage N ;
  - salle qui se vide : décroissance exponentielle du CO2, sans le comptage.
La nuit (ventilation en marche, salle vide), le CO2 doit revenir à l'air extérieur : sinon le capteur dérive.

Ce que les données réelles (salle danoise OU44, ROBOD) ont changé par rapport au jumeau :
  - une phase de recalage par salle : on apprend le rapport normal entre les deux méthodes (1,55 dans
    la salle danoise) et, si on ne connaît pas le débit de la ventilation, le débit de référence ;
  - on décide sur plusieurs départs (médiane), pas sur un seul ;
  - une 5e cause : le capteur de CO2 ne réagit pas aux personnes (mal placé).
Les temps sont en heures (t = secondes depuis 1970 / 3600).
"""

from collections import deque
from math import log
from statistics import median

FENETRE_OCC = 10 / 60          # h, fenêtre du bilan en occupation
BORNES = 1 / 60                # h, moyenne aux deux bouts de la fenêtre
ATTENTE_DECROISSANCE = 3 / 60  # h après le départ (les derniers sortent, l'air se mélange)
DUREE_MIN_DECROISSANCE = 6 / 60
DUREE_MAX_DECROISSANCE = 1.0    # h : au-delà, le CO2 est revenu dans le bruit du capteur
NUIT = (19.5, 20.5)            # heure de la mesure du niveau de base
SEUIL_DERIVE = 80              # ppm
VALIDITE = 14                  # h, durée pendant laquelle une estimation reste utilisable
T_NORMALE = 20                 # °C
EXCES_MIN_OCC = 250            # ppm : en dessous, le CO2 monte trop peu pour mesurer le débit
DEPARTS_CALIBRATION = 3        # départs utilisés pour le recalage
RATIO_MIN, RATIO_MAX = 0.7, 1.3
RETOUR_NORMAL = 0.5            # h de mesures normales avant d'oublier une anomalie
JOURNEE = (7.0, 19.5)          # h : débits appris seulement pendant la journée de cours


def regression_pente(xs, ys):
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den > 0 else 0.0


class EstimateurSalle:
    def __init__(self, volume, debits=None, g=0.018, c_ext=420, biais=None, q_ref=None):
        self.volume = volume            # m3
        self.debits = debits or {}      # débit attendu (m3/h) pour chaque niveau de ventilation, s'il est connu
        self.g = g                      # m3/h de CO2 par personne
        self.c_ext = c_ext              # ppm
        self.echantillons = deque()     # dict(t, h, C, Cbrut, N, niveau, T)
        self.correction = 0.0           # ppm retirés après une dérive détectée la nuit
        self.occ = None                 # dernière estimation en occupation
        self.dec = None                 # dernière estimation par décroissance
        self.base = None                # dernière mesure de nuit
        self.vide = None                # début de la période vide en cours
        self.nuit = {'points': [], 'jour': None}
        self.nuit_refusee = None        # dernière soirée où le CO2 n'était pas encore stable
        self.anomalie_occ = None
        self.normal_depuis = None
        self.mal_place_depuis = None
        # Recalage : rapport normal occ/dec et débit de référence
        self.biais = biais
        self.q_ref = q_ref
        self.rapports_bruts = []
        self.decroissances = []
        self.comparaisons = deque(maxlen=3)   # rapports occ/dec (recalés) des derniers départs
        # Débits mesurés récemment (un point toutes les 10 min au plus), pour le jumeau prédictif
        self.debits_occupee = deque(maxlen=30)    # (niveau, Q) salle occupée
        self.debits_vide = deque(maxlen=30)       # (niveau, Q) salle qui se vide

    # ---------- entrées ----------

    def attendu(self, niveau):
        if niveau in self.debits:
            return self.debits[niveau]
        return self.q_ref

    def en_calibration(self):
        return self.biais is None

    def ajouter(self, t, heure, C, N, niveau=None, T=None):
        e = {'t': t, 'h': heure, 'Cbrut': C, 'C': C - self.correction, 'N': N, 'niveau': niveau, 'T': T}
        self.echantillons.append(e)
        while self.echantillons and self.echantillons[0]['t'] < t - 3:
            self.echantillons.popleft()
        self._occupation(t)
        self._decroissance(e)
        self._nuit(e)
        self._capteur_place(t)

    # ---------- méthode 1 : salle occupée ----------

    def _occupation(self, t):
        fen = [e for e in self.echantillons if e['t'] > t - FENETRE_OCC]
        if len(fen) < 5 or fen[-1]['t'] - fen[0]['t'] < 0.8 * FENETRE_OCC:
            return
        niveau = fen[0]['niveau']
        if not all(e['N'] >= 8 and e['niveau'] == niveau for e in fen):
            return
        if sum(e['C'] for e in fen) / len(fen) - self.c_ext < EXCES_MIN_OCC:
            return
        debut = [e['C'] for e in fen if e['t'] <= fen[0]['t'] + BORNES]
        fin = [e['C'] for e in fen if e['t'] >= fen[-1]['t'] - BORNES]
        production = exces = 0.0
        for a, b in zip(fen, fen[1:]):
            dt = b['t'] - a['t']
            production += (a['N'] + b['N']) / 2 * self.g / self.volume * 1e6 * dt
            exces += ((a['C'] + b['C']) / 2 - self.c_ext) * dt
        q_brut = self.volume * (production - (sum(fin) / len(fin) - sum(debut) / len(debut))) / exces
        q = q_brut / (self.biais or 1.0)
        self.occ = {'Q': q, 'Q_brut': q_brut, 'Qatt': self.attendu(niveau), 't': t, 'niveau': niveau}
        self._retenir(self.debits_occupee, t, niveau, q)
        if self.occ['Qatt']:
            r = q / self.occ['Qatt']
            if r < RATIO_MIN or r > RATIO_MAX:
                self.normal_depuis = None
                if self.anomalie_occ is None:
                    self.anomalie_occ = t
            else:
                if self.normal_depuis is None:
                    self.normal_depuis = t
                if t - self.normal_depuis > RETOUR_NORMAL:
                    self.anomalie_occ = None

    # ---------- méthode 2 : salle qui se vide ----------

    def _decroissance(self, e):
        if e['N'] > 0 or e['niveau'] == 'arret':
            self.vide = None
            return
        if self.vide is None or e['niveau'] != self.vide['niveau']:
            occ_avant = self.occ if self.occ and e['t'] - self.occ['t'] < 0.5 else None
            self.vide = {'t': e['t'], 'niveau': e['niveau'], 'C0': e['C'], 'occ_avant': occ_avant, 'compare': False}
            return
        if self.vide['C0'] - self.c_ext < 150:
            return
        # On s'arrête quand l'excès de CO2 tombe dans le bruit du capteur : la fin de courbe aplatirait la pente
        seuil = max(80, 0.15 * (self.vide['C0'] - self.c_ext))
        fen = [x for x in self.echantillons
               if self.vide['t'] + ATTENTE_DECROISSANCE <= x['t'] <= self.vide['t'] + DUREE_MAX_DECROISSANCE]
        fin = next((i for i, x in enumerate(fen) if x['C'] - self.c_ext < seuil), len(fen))
        fen = fen[:fin]
        if len(fen) < 5 or fen[-1]['t'] - fen[0]['t'] < DUREE_MIN_DECROISSANCE:
            return
        pente = regression_pente([x['t'] for x in fen], [log(x['C'] - self.c_ext) for x in fen])
        q = -pente * self.volume
        self.dec = {'Q': q, 'Qatt': self.attendu(e['niveau']), 't': e['t'], 'niveau': e['niveau']}
        if fen[-1]['t'] - fen[0]['t'] >= 2 * DUREE_MIN_DECROISSANCE and JOURNEE[0] <= e['h'] <= JOURNEE[1]:
            self._retenir(self.debits_vide, e['t'], e['niveau'], q)
        if not self.vide['compare'] and fen[-1]['t'] - fen[0]['t'] >= 2 * DUREE_MIN_DECROISSANCE:
            self.vide['compare'] = True
            self._apres_depart(self.vide['occ_avant'], q, e['niveau'])

    def mesure_restante(self):
        """Minutes de ventilation stable qu'il faut encore pour finir la décroissance en cours (0 sinon)."""
        if not self.vide or self.vide['compare'] or self.vide['C0'] - self.c_ext < 150:
            return 0
        fin = self.vide['t'] + ATTENTE_DECROISSANCE + 2 * DUREE_MIN_DECROISSANCE + 1 / 60
        return max(0, round((fin - self.echantillons[-1]['t']) * 60))

    def _rapport(self, occ, q_dec, niveau_dec, brut=False):
        """Rapport entre les deux méthodes. Si la ventilation a changé de vitesse au départ des
        occupants, on compare chaque débit à celui attendu pour sa vitesse."""
        q_occ = occ['Q_brut'] if brut else occ['Q']
        if occ['niveau'] == niveau_dec:
            return q_occ / q_dec
        a_occ, a_dec = self.debits.get(occ['niveau']), self.debits.get(niveau_dec)
        if a_occ and a_dec:
            return (q_occ / a_occ) / (q_dec / a_dec)
        return None                     # vitesses différentes et débits inconnus : pas comparable

    def _apres_depart(self, occ_avant, q_dec, niveau_dec):
        """Une salle vient de se vider : on compare les deux méthodes (ou on se recale)."""
        # Débit de référence de la salle (ventilation inconnue) : les premières décroissances
        if self.q_ref is None and not self.debits:
            self.decroissances.append(q_dec)
            if len(self.decroissances) >= DEPARTS_CALIBRATION:
                self.q_ref = median(self.decroissances)
        rapport = self._rapport(occ_avant, q_dec, niveau_dec, brut=self.en_calibration()) if occ_avant else None
        if self.en_calibration():
            if rapport:
                self.rapports_bruts.append(rapport)
            if len(self.rapports_bruts) >= DEPARTS_CALIBRATION:
                self.biais = median(self.rapports_bruts)
                self.occ = None
            return
        if rapport:
            self.comparaisons.append(rapport)

    def _retenir(self, liste, t, niveau, q):
        if q > 0 and (not liste or t - liste[-1][2] >= 10 / 60 or liste[-1][0] != niveau):
            liste.append((niveau, q, t))
        elif q > 0 and liste and liste[-1][0] == niveau:
            liste[-1] = (niveau, q, t)          # même épisode : on garde la dernière estimation

    def debit_appris(self, occupee, niveau=None):
        """Débit de la salle pour la prévision : connu (automate), ou médiane des débits mesurés."""
        if niveau in self.debits:
            return self.debits[niveau]
        # Une seule mesure dans le bon état (salle occupée ou vide) vaut mieux que plusieurs dans l'autre :
        # avec une fenêtre ouverte pendant le cours, les deux débits n'ont rien à voir
        for liste in ((self.debits_occupee, self.debits_vide) if occupee else (self.debits_vide, self.debits_occupee)):
            valeurs = [q for n, q, _ in liste if n == niveau] or [q for _, q, _ in liste]
            if valeurs:
                return median(valeurs)
        return None

    # ---------- niveau de base la nuit ----------

    def _nuit(self, e):
        h = e['h']
        jour = int(e['t'] // 24)
        if NUIT[0] <= h < NUIT[1] and e['N'] == 0 and e['niveau'] != 'arret':
            if self.nuit['jour'] != jour:
                self.nuit = {'points': [], 'jour': jour}
            self.nuit['points'].append((e['t'], e['Cbrut'] - self.c_ext))
        elif h >= NUIT[1] and self.nuit['jour'] == jour and len(self.nuit['points']) >= 5:
            # On garde le dernier tiers de la fenêtre : l'air du dernier cours a eu le temps de partir
            points = self.nuit['points'][-max(5, len(self.nuit['points']) // 3):]
            self.nuit['points'] = []
            # Le CO2 doit être stable : sinon l'air de la journée n'est pas encore parti (vrai dans ROBOD)
            pente = regression_pente([p[0] for p in points], [p[1] for p in points])
            if abs(pente) > 40:
                self.nuit_refusee = e['t']
                return
            ecart = sum(p[1] for p in points) / len(points)
            self.base = {'ecart': ecart, 't': e['t']}
            nouvelle = ecart if abs(ecart) > SEUIL_DERIVE else 0.0
            if abs(nouvelle - self.correction) > 1:
                # Les estimations faites avec l'ancien réglage sont fausses : on les oublie
                self.occ = self.dec = self.anomalie_occ = None
                self.comparaisons.clear()
            self.correction = nouvelle

    # ---------- capteur mal placé ----------

    def _capteur_place(self, t):
        fen = [e for e in self.echantillons if e['t'] > t - 0.5]
        if len(fen) < 10 or fen[-1]['t'] - fen[0]['t'] < 0.45:
            return
        n_moy = sum(e['N'] for e in fen) / len(fen)
        q = self.attendu(fen[-1]['niveau'])
        if min(e['N'] for e in fen) < 10 or not q:
            self.mal_place_depuis = None
            return
        montee_attendue = n_moy * self.g * 1e6 / q
        montee = sum(e['C'] for e in fen[-5:]) / 5 - self.c_ext
        if montee_attendue >= 150 and montee < 40:
            if self.mal_place_depuis is None:
                self.mal_place_depuis = t
        else:
            self.mal_place_depuis = None

    # ---------- diagnostic ----------

    def _chute_temperature(self):
        avec_t = [e for e in self.echantillons if e['T'] is not None]
        if len(avec_t) < 2:
            return 0.0
        dernier = avec_t[-1]
        avant = next((e for e in avec_t if e['t'] >= dernier['t'] - 0.25), avec_t[0])
        return max(avant['T'] - dernier['T'], T_NORMALE - dernier['T'])

    def diagnostic(self):
        t = self.echantillons[-1]['t'] if self.echantillons else 0
        occ = self.occ if self.occ and t - self.occ['t'] < VALIDITE and self.occ['Qatt'] else None
        dec = self.dec if self.dec and t - self.dec['t'] < VALIDITE and self.dec['Qatt'] else None
        r_occ = occ['Q'] / occ['Qatt'] if occ else None
        r_dec = dec['Q'] / dec['Qatt'] if dec else None
        chute = self._chute_temperature()
        m3 = lambda q: f'{round(q)} m³/h'

        causes = {
            'ventilation': {'titre': 'Ventilation en panne', 'etat': 'attente', 'message': 'Pas encore assez de mesures.'},
            'fenetre': {'titre': 'Fenêtre ouverte', 'etat': 'ok', 'message': 'Température stable près de la fenêtre.'},
            'derive': {'titre': 'Capteur de CO₂ qui dérive', 'etat': 'attente', 'message': 'Vérification le soir (19 h 30 – 20 h 30).'},
            'comptage': {'titre': 'Comptage faux', 'etat': 'attente', 'message': 'Il faut des départs de la salle pour comparer.'},
            'capteur': {'titre': 'Capteur de CO₂ mal placé', 'etat': 'ok', 'message': 'Le CO₂ réagit aux personnes.'},
        }

        if self.nuit_refusee and (not self.base or self.nuit_refusee > self.base['t']):
            causes['derive'].update(message="Pas de vérification ce soir : le CO₂ n'était pas encore stable.")
        if self.base:
            ecart = round(self.base['ecart'])
            if abs(ecart) > SEUIL_DERIVE:
                causes['derive'].update(etat='detecte', message=f'Le soir, le capteur indique {self.c_ext + ecart} ppm au lieu d\'environ {self.c_ext}. Corrigé de {ecart} ppm.')
            else:
                causes['derive'].update(etat='ok', message=f'Le soir, le CO₂ revient à {self.c_ext + ecart} ppm : capteur juste.')

        if self.mal_place_depuis is not None and t - self.mal_place_depuis > 0.25:
            causes['capteur'].update(etat='detecte', message='Beaucoup de monde mais le CO₂ ne monte pas : capteur près d\'une bouche d\'air ou d\'une fenêtre ?')

        fort = (r_occ is not None and r_occ > 1.4) or (r_dec is not None and r_dec > 1.4)
        if chute >= 2 and fort:
            causes['fenetre'].update(etat='detecte', message=f'Température −{chute:.1f} °C près de la fenêtre et débit d\'air trop fort.')
        elif chute >= 2:
            causes['fenetre'].update(etat='suspect', message=f'Température −{chute:.1f} °C près de la fenêtre.')

        if self.en_calibration():
            n = len(self.rapports_bruts)
            texte = f'Recalage de la salle en cours ({n}/{DEPARTS_CALIBRATION} départs).'
            causes['ventilation'].update(etat='attente', message=texte)
            causes['comptage'].update(etat='attente', message=texte)
            return causes

        if r_occ is not None or r_dec is not None:
            faible_occ = r_occ is not None and r_occ < 0.6
            faible_dec = r_dec is not None and r_dec < 0.55
            if faible_occ and faible_dec:
                causes['ventilation'].update(etat='detecte', message=f'Débit mesuré {m3(dec["Q"])} au lieu de {m3(dec["Qatt"])}, avec et sans le comptage.')
            elif faible_occ or faible_dec:
                p = dec if faible_dec else occ
                causes['ventilation'].update(etat='suspect', message=f'Débit {m3(p["Q"])} au lieu de {m3(p["Qatt"])}, à confirmer par l\'autre méthode.')
            else:
                causes['ventilation'].update(etat='ok', message='Le débit mesuré correspond à ce qui est attendu.')

        # Comptage faux : médiane des derniers départs, décroissance normale, pas de fenêtre ouverte
        dec_normale = r_dec is not None and RATIO_MIN < r_dec < 1.4
        if len(self.comparaisons) >= 2 and dec_normale and chute < 2:
            rapport = median(self.comparaisons)
            if rapport > RATIO_MAX or rapport < RATIO_MIN:
                causes['comptage'].update(etat='detecte', message=f'Sur les {len(self.comparaisons)} derniers départs, le débit calculé avec le comptage vaut {round(rapport * 100)} % de celui sans comptage. Le comptage est faux.')
            else:
                causes['comptage'].update(etat='ok', message='Les deux méthodes donnent le même débit.')
        elif r_occ is not None and dec_normale and chute < 2 and (r_occ > RATIO_MAX or r_occ < RATIO_MIN):
            causes['comptage'].update(etat='suspect', message='Le débit calculé avec le comptage est anormal. Confirmation aux prochains départs.')
        elif r_occ is not None and r_dec is not None:
            causes['comptage'].update(etat='ok', message='Les deux méthodes donnent le même débit.')
        return causes

    def resume(self):
        """Ce que l'interface affiche."""
        return {
            'correction': round(self.correction),
            'q_occupation': round(self.occ['Q']) if self.occ else None,
            'q_decroissance': round(self.dec['Q']) if self.dec else None,
            'q_attendu': round(self.attendu(self.echantillons[-1]['niveau'])) if self.echantillons and self.attendu(self.echantillons[-1]['niveau']) else None,
            'calibration': None if not self.en_calibration() else f'{len(self.rapports_bruts)}/{DEPARTS_CALIBRATION}',
            'biais': round(self.biais, 2) if self.biais else None,
            'diagnostic': self.diagnostic(),
        }
