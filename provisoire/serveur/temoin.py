"""Le CO₂ comme témoin de l'émargement : combien de personnes ont vraiment respiré dans la salle,
comparé au nombre de badges.

Il repère les cartes badgées en groupe pour des absents (un étudiant qui badge pour 6 copains), même
dans une salle sans capteurs à la porte, et les personnes entrées sans badger. Bilan de CO₂ sur le
cours, le jumeau connaissant le volume V de la salle et ayant appris son débit d'air Q :

    personnes en moyenne = (V × montée du CO₂ par heure + Q × (CO₂ moyen − extérieur)) / production d'une personne

Les 5 premiers cours d'une salle servent à l'apprendre (pas d'alerte) : badges supposés honnêtes, comme
la première semaine de l'essai sur données réelles. Ensuite, la salle se recale sur ses cours sans alerte
(facteur = médiane badges / estimation).
Testé sur de vraies salles (ROBOD, voir donnees_reelles/test_temoin_co2.py) : il repère 6 à 8 cartes en
trop dans la plupart des salles avec peu de fausses alertes. Il ne voit pas 1 ou 2 cartes (c'est le rôle
du comptage à la porte), ni rien dans une salle si ventilée que le CO₂ ne monte presque pas : il le dit.
"""

from collections import deque
from statistics import median

from salle import heure_du_jour

DEBUT_MESURE = 15 / 60      # h après le début du cours : tout le monde est arrivé
DUREE_MIN = 0.5             # h de mesures au moins
SIGNAL_MIN = 80             # ppm au-dessus de l'extérieur en moyenne : en dessous, le CO₂ ne dit rien
SEUIL_MIN = 3               # personnes : écart toléré au minimum
INCERTITUDE = 0.2           # part d'incertitude tant que la salle n'est pas recalée
RECALAGE = 5                # cours sans alerte avant de se fier au recalage de la salle

VERDICTS = {
    'coherent': 'Le CO₂ confirme les badges.',
    'badges_en_trop': 'Plus de badges que de personnes : cartes badgées pour des absents ?',
    'personnes_sans_badge': 'Plus de personnes que de badges : oublis de badge, ou personnes extérieures ?',
    'signal_faible': "Le CO₂ monte trop peu dans cette salle (très ventilée) : pas d'avis.",
    'pas_de_debit': "Débit d'air de la salle pas encore mesuré : pas d'avis.",
    'attente': 'Pas encore assez de mesures (il faut 30 min de cours).',
    'apprentissage': "Le témoin apprend encore cette salle : pas d'avis.",
}


class Temoin:
    def __init__(self, config):
        self.g = config.G_PERSONNE
        self.c_ext = config.C_EXT
        self.recalage = {}           # salle -> (badges, estimation brute) des derniers cours sans alerte

    def _facteur(self, salle_id):
        r = self.recalage.get(salle_id)
        return median(b / e for b, e in r if e > 0) if r and len(r) >= RECALAGE else 1.0

    def _seuil(self, salle_id, estimation):
        r = self.recalage.get(salle_id)
        if r and len(r) >= RECALAGE:
            k = self._facteur(salle_id)
            ecarts = sorted(abs(b - k * e) for b, e in r)
            return max(SEUIL_MIN, 1.5 * ecarts[int(0.9 * (len(ecarts) - 1))])
        return max(SEUIL_MIN, INCERTITUDE * estimation + 1.5)

    def evaluer(self, salle, debut, fin, t, badges):
        """Avis du CO₂ sur un cours (ou sur ce qui en est passé). badges : personnes qui ont badgé, enseignant compris."""
        h = heure_du_jour(t)
        points = [(heure_du_jour(tm), c) for tm, c, _ in salle.historique
                  if debut + DEBUT_MESURE <= heure_du_jour(tm) <= min(fin, h)]
        if len(points) < 3 or points[-1][0] - points[0][0] < DUREE_MIN:
            return self._avis('attente', badges)
        q = salle.estimateur.debit_appris(True, salle.niveau if salle.niveau in salle.estimateur.debits else None)
        if not q:
            return self._avis('pas_de_debit', badges)
        ecart = sum(c for _, c in points) / len(points) - self.c_ext
        if ecart < SIGNAL_MIN:
            return self._avis('signal_faible', badges)
        # Montée du CO₂ : bouts de la fenêtre lissés sur 3 mesures (le capteur bruite)
        duree = points[-1][0] - points[0][0]
        montee = (sum(c for _, c in points[-3:]) - sum(c for _, c in points[:3])) / 3 / duree
        brute = (salle.estimateur.volume * montee + q * ecart) / (self.g * 1e6)
        estimation = self._facteur(salle.id) * brute
        seuil = self._seuil(salle.id, estimation)
        appris = len(self.recalage.get(salle.id, ()))
        if appris < RECALAGE:
            verdict = 'apprentissage'
        elif badges - estimation > seuil:
            verdict = 'badges_en_trop'
        elif estimation - badges > seuil:
            verdict = 'personnes_sans_badge'
        else:
            verdict = 'coherent'
        avis = {**self._avis(verdict, badges), 'personnes': round(estimation), 'brute': round(brute, 2),
                'min': max(0, round(estimation - seuil)), 'max': round(estimation + seuil)}
        if verdict == 'apprentissage':
            avis['texte'] = f"Le témoin apprend encore cette salle ({appris}/{RECALAGE} cours) : pas d'avis."
        return avis

    def _avis(self, verdict, badges):
        return {'verdict': verdict, 'texte': VERDICTS[verdict], 'badges': badges}

    def apprendre(self, salle_id, avis):
        """Un cours sans alerte (ou un des premiers cours de la salle) recale la salle."""
        if avis['verdict'] in ('coherent', 'apprentissage') and avis.get('brute'):
            self.recalage.setdefault(salle_id, deque(maxlen=30)).append((avis['badges'], avis['brute']))
