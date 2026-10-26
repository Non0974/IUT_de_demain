"""Ventilation anticipée de la salle pilotée par l'automate (commande prédictive).

Chaque minute, le jumeau essaie les vitesses possibles pour les 20 prochaines minutes (deux blocs
de 10 min, 9 combinaisons), simule la suite jusqu'à 90 min (en choisissant ensuite, bloc par bloc,
la vitesse la moins coûteuse) et garde le meilleur plan :
    coût = énergie (ventilateur + chauffage de l'air neuf)
         + pénalité quand le CO2 dépasse 800 ppm, beaucoup plus forte au-dessus de 1000 ppm.
Il ventile donc AVANT que la salle se remplisse, et coupe quand l'air est bon et que personne n'arrive.

Contraintes :
  - salle occupée : au moins la petite vitesse (air neuf obligatoire) ;
  - fenêtres de mesure du jumeau : exactement la petite vitesse (débit stable et connu), sinon il ne
    peut plus mesurer la décroissance du CO2 ni vérifier le capteur le soir :
      * 20 min après chaque fin de cours ;
      * de 18 h 30 à 20 h 30 les jours de cours (l'air doit être revenu à l'extérieur à 19 h 30).
    Sans ces fenêtres, les essais montraient que la dérive du capteur et le comptage faux n'étaient
    plus détectés : le jumeau économisait de l'énergie mais ne se surveillait plus.

On compare en continu avec la règle simple d'avant (ventilation selon le nombre de personnes, petite
vitesse toute la journée) : le jumeau la simule en parallèle sur les mêmes occupants.
"""

from datetime import datetime
from math import exp

NIVEAUX = ('arret', 'petite', 'grande')
BLOC = 10                 # min
HORIZON = 90              # min
CHANGEMENT = 0.01         # kWh-équivalent : on évite de changer de vitesse pour rien
APRES_COURS = 20 / 60     # h de ventilation gardée après un cours (mesure de la décroissance)
SOIR = (18.5, 20.5)       # purge puis vérification du capteur (19 h 30 – 20 h 30)


class CommandePredictive:
    def __init__(self, config, volume):
        self.debits = config.DEBITS[config.SALLE_AUTOMATE]
        self.volume = volume
        self.g, self.c_ext = config.G_PERSONNE, config.C_EXT
        self.config = config
        self.dernier = 'petite'
        self.plan = []
        self.amorti = {n: exp(-q / volume / 60) for n, q in self.debits.items()}

    def puissance(self, niveau):
        """kW : chauffage de l'air neuf entrant + ventilateur."""
        q = self.debits[niveau]
        cfg = self.config
        chauffage = 0.34 * q * max(0, cfg.T_INTERIEUR - cfg.T_EXTERIEUR) * (1 - cfg.RECUPERATION_CHALEUR)
        ventilateur = cfg.PUISSANCE_VENTILATEUR * (q - self.debits['arret'])
        return (chauffage + ventilateur) / 1000

    def pas(self, c, n, niveau, minutes=1):
        q = self.debits[niveau]
        c_eq = self.c_ext + n * self.g * 1e6 / q
        return c_eq + (c - c_eq) * self.amorti[niveau] ** minutes

    def cout(self, c, niveau):
        cfg = self.config
        return (self.puissance(niveau) / 60 + cfg.PENALITE_800 * max(0.0, c - 800)
                + cfg.PENALITE_1000 * max(0.0, c - 1000))

    def _bloc(self, c, occupation, bornes, k0, niveau):
        """Simule un bloc de 10 min à vitesse fixe ; None si la vitesse est interdite sur ce bloc."""
        cout = 0.0
        i = NIVEAUX.index(niveau)
        for k in range(k0, min(k0 + BLOC, len(occupation))):
            bas, haut = bornes[k]
            if not NIVEAUX.index(bas) <= i <= NIVEAUX.index(haut):
                return None, None
            c = self.pas(c, occupation[k], niveau)
            cout += self.cout(c, niveau)
        return c, cout

    def _suite(self, c, occupation, bornes, k0):
        """Après les 20 premières minutes : bloc par bloc, la vitesse la moins coûteuse."""
        total, plan = 0.0, []
        for k in range(k0, len(occupation), BLOC):
            essais = [(cout, n, c2) for n in NIVEAUX for c2, cout in [self._bloc(c, occupation, bornes, k, n)] if cout is not None]
            if not essais:                 # bloc à cheval sur deux contraintes : on prend la vitesse imposée au début
                n = bornes[k][0]
                essais = [(0.0, n, self.pas(c, occupation[k], n, min(BLOC, len(occupation) - k)))]
            cout, n, c = min(essais)
            total += cout
            plan += [n] * min(BLOC, len(occupation) - k)
        return total, plan

    def decider(self, c0, occupation, bornes):
        """occupation : personnes prévues minute par minute ; bornes : (vitesse min, vitesse max) de chaque minute."""
        occupation, bornes = occupation[:HORIZON], bornes[:HORIZON]
        meilleur = None
        for n1 in NIVEAUX:
            c1, k1 = self._bloc(c0, occupation, bornes, 0, n1)
            if k1 is None:
                continue
            for n2 in NIVEAUX:
                c2, k2 = self._bloc(c1, occupation, bornes, BLOC, n2)
                if k2 is None:
                    continue
                reste, plan = self._suite(c2, occupation, bornes, 2 * BLOC)
                total = k1 + k2 + reste + (CHANGEMENT if n1 != self.dernier else 0)
                if meilleur is None or total < meilleur[0]:
                    meilleur = (total, n1, [n1] * BLOC + [n2] * BLOC + plan)
        if meilleur is None:              # contraintes qui changent dans le bloc : on suit la contrainte de maintenant
            n1 = bornes[0][0] if bornes[0][0] == bornes[0][1] else max(bornes[0][0], 'petite', key=NIVEAUX.index)
            meilleur = (0, n1, [n1] * len(occupation))
        _, self.dernier, self.plan = meilleur
        return self.dernier


def bornes_vitesse(cours, h0, minutes, occupation):
    """(Vitesse min, vitesse max) de chaque minute : petite imposée pendant les fenêtres de mesure,
    au moins petite si la salle est occupée, libre sinon."""
    fins = [c['fin'] for c in cours]
    bornes = []
    for k in range(minutes):
        h = h0 + k / 60
        mesure = any(f <= h <= f + APRES_COURS for f in fins) or (bool(fins) and SOIR[0] <= h <= SOIR[1])
        if mesure and occupation[k] < 1:
            bornes.append(('petite', 'petite'))
        elif occupation[k] >= 1:
            bornes.append(('petite', 'grande'))
        else:
            bornes.append(('arret', 'grande'))
    return bornes


class BilanVentilation:
    """Énergie et minutes de mauvais air de la journée : commande du jumeau / règle simple simulée."""

    def __init__(self, commande):
        self.commande = commande
        self.jour = None
        self.t = None

    def remettre(self, jour, c):
        self.jour = jour
        self.c_regle = c
        self.energie = {'jumeau': 0.0, 'regle': 0.0}
        self.minutes_1000 = {'jumeau': 0.0, 'regle': 0.0}
        self.minutes_800 = {'jumeau': 0.0, 'regle': 0.0}

    def avancer(self, t, n, c_mesure, niveau, niveau_regle):
        """niveau : vitesse appliquée ; niveau_regle(n, c) : ce qu'aurait choisi la règle simple."""
        jour = datetime.fromtimestamp(t).date()
        if jour != self.jour:
            self.remettre(jour, c_mesure)
            self.t = t
            return
        minutes = min(10.0, max(0.0, (t - self.t) / 60))
        self.t = t
        if minutes == 0:
            return
        heures = minutes / 60
        regle = niveau_regle(n, self.c_regle)
        self.c_regle = self.commande.pas(self.c_regle, n, regle, minutes)
        self.energie['jumeau'] += self.commande.puissance(niveau) * heures
        self.energie['regle'] += self.commande.puissance(regle) * heures
        for nom, c in (('jumeau', c_mesure), ('regle', self.c_regle)):
            if c > 1000:
                self.minutes_1000[nom] += minutes
            if c > 800:
                self.minutes_800[nom] += minutes

    def resume(self):
        if self.jour is None:
            return None
        e = self.energie
        return {
            'energie_kwh': {k: round(v, 2) for k, v in e.items()},
            'economie': round(1 - e['jumeau'] / e['regle'], 3) if e['regle'] >= 1.0 else None,
            'minutes_au_dessus_1000': {k: round(v) for k, v in self.minutes_1000.items()},
            'minutes_au_dessus_800': {k: round(v) for k, v in self.minutes_800.items()},
            'c_regle': round(self.c_regle),
        }
