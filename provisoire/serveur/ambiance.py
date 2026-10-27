"""Chauffage et éclairage selon l'occupation réelle des salles.

Horaire fixe d'avant : chauffage en confort de 7 h à 19 h les jours de semaine (réduit sinon),
éclairage allumé de 8 h à 18 h.
Avec le jumeau :
  - chauffage : confort pendant un cours et 45 min avant (le temps de chauffer la salle), ou dès qu'il y
    a du monde ; réduit le reste de la journée (7 h – 20 h) ; hors-gel la nuit et le week-end ;
  - éclairage : allumé seulement quand il y a quelqu'un, ou un cours qui commence ; éteint quand la
    salle est vide.
La salle de l'automate (SAR 200) est vraiment pilotée : l'automate allume la lumière et le chauffage de
la maquette. Pour les autres salles, le jumeau calcule ce que ce pilotage économiserait.

Énergie (estimation, à remplacer par les vraies puissances des salles) : chauffage 50 W/m² en
confort, 60 % en réduit, 20 % en hors-gel ; éclairage LED 8 W/m².
"""

from datetime import datetime

from salle import heure_du_jour

MODES = ('hors_gel', 'reduit', 'confort')
PRECHAUFFE = 0.75             # h avant un cours
AVANT_COURS = 5 / 60          # h : la lumière s'allume pour l'arrivée des étudiants
JOURNEE = (7.0, 20.0)         # h : en dehors, hors-gel
FIXE_CHAUFFAGE = (7.0, 19.0)  # h : horaire fixe d'avant
FIXE_ECLAIRAGE = (8.0, 18.0)
CHAUFFAGE_W_M2 = 50
PART = {'confort': 1.0, 'reduit': 0.6, 'hors_gel': 0.2}
ECLAIRAGE_W_M2 = 8


def decider(cours, h, jour_semaine, personnes):
    """(éclairage allumé ?, mode de chauffage) d'une salle à l'heure h."""
    if personnes > 0 or any(c['debut'] - PRECHAUFFE <= h <= c['fin'] for c in cours):     # cours prévu, même un samedi
        chauffage = 'confort'
    elif jour_semaine < 5 and JOURNEE[0] <= h <= JOURNEE[1]:
        chauffage = 'reduit'
    else:
        chauffage = 'hors_gel'
    eclairage = personnes > 0 or any(c['debut'] - AVANT_COURS <= h <= c['fin'] for c in cours)
    return eclairage, chauffage


def horaire_fixe(h, jour_semaine):
    semaine = jour_semaine < 5
    chauffage = 'confort' if semaine and FIXE_CHAUFFAGE[0] <= h < FIXE_CHAUFFAGE[1] else 'reduit'
    return semaine and FIXE_ECLAIRAGE[0] <= h < FIXE_ECLAIRAGE[1], chauffage


def puissance(surface, eclairage, chauffage):
    """kW consommés par la salle."""
    return (surface * CHAUFFAGE_W_M2 * PART[chauffage] + (surface * ECLAIRAGE_W_M2 if eclairage else 0)) / 1000


class BilanAmbiance:
    """Énergie de la journée : pilotage par l'occupation / horaire fixe, salle de l'automate et bâtiment."""

    def __init__(self, salle_automate):
        self.salle_automate = salle_automate
        self.jour = None
        self.t = None
        self._cours = (None, {})                  # liste des cours du jour -> cours rangés par salle

    def avancer(self, campus, t):
        jour = datetime.fromtimestamp(t).date()
        if jour != self.jour:
            self.jour, self.t = jour, t
            self.energie = {'salle': {'jumeau': 0.0, 'fixe': 0.0}, 'batiment': {'jumeau': 0.0, 'fixe': 0.0}}
            self.heures_confort = {'jumeau': 0.0, 'fixe': 0.0}
            return
        heures = min(10.0, max(0.0, (t - self.t) / 60)) / 60
        self.t = t
        if not heures:
            return
        h = heure_du_jour(t)
        js = jour.weekday()
        cours = campus.planning.cours_du_jour(jour)
        if cours is not self._cours[0]:            # le planning ne change pas souvent : on range une fois
            par_salle = {}
            for c in cours:
                par_salle.setdefault(c['salle'], []).append(c)
            self._cours = (cours, par_salle)
        for s in campus.batiment['salles']:
            salle = campus.salles[s['id']]
            moi = decider(self._cours[1].get(s['id'], []), h, js, salle.nombre())
            fixe = horaire_fixe(h, js)
            for nom, choix in (('jumeau', moi), ('fixe', fixe)):
                kwh = puissance(s['surface'], *choix) * heures
                self.energie['batiment'][nom] += kwh
                if s['id'] == self.salle_automate:
                    self.energie['salle'][nom] += kwh
                    self.heures_confort[nom] += heures if choix[1] == 'confort' else 0

    def resume(self):
        if self.jour is None:
            return None

        def economie(e):
            return round(1 - e['jumeau'] / e['fixe'], 3) if e['fixe'] >= 1.0 else None

        return {
            'salle': {**{k: round(v, 1) for k, v in self.energie['salle'].items()}, 'economie': economie(self.energie['salle'])},
            'batiment': {**{k: round(v) for k, v in self.energie['batiment'].items()}, 'economie': economie(self.energie['batiment'])},
            'heures_confort': {k: round(v, 1) for k, v in self.heures_confort.items()},
        }
