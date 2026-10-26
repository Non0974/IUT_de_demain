"""Jumeau prédictif : le CO2 des prochaines heures de chaque salle.

On simule chaque salle minute par minute avec le même bilan que l'estimateur :
    V dC/dt = N(t) G - Q(t) (C - Cext)
  - N(t) : l'emploi du temps (qui arrive, quand, combien) et le taux de présence appris dans le
    registre ; pour le cours en cours, le nombre de personnes mesuré maintenant ;
  - Q(t) : le débit de la salle appris par l'estimateur (salle occupée / salle vide), ou connu
    pour la salle pilotée par l'automate (selon la vitesse prévue).
La précision des prévisions est mesurée en continu (prévu il y a 30 et 60 min / mesuré).
"""

from collections import deque
from datetime import datetime, timedelta
from math import exp

ARRIVEE_AVANT = 8 / 60          # h : les premiers arrivent 8 min avant le cours
ARRIVEE_APRES = 4 / 60          # h : les derniers 4 min après
SORTIE = 3 / 60                 # h
TAUX_PAR_DEFAUT = 0.88          # part des inscrits présents, tant que le registre est vide
DEBIT_PAR_PLACE = 18            # m3/h par place, débit supposé d'une salle pas encore recalée


def heure_de(t):
    d = datetime.fromtimestamp(t)
    return d.hour + d.minute / 60 + d.second / 3600


def profil(c, h, attendus):
    """Nombre de personnes d'un cours à l'heure h (arrivées et sortie étalées)."""
    a0, a1 = c['debut'] - ARRIVEE_AVANT, c['debut'] + ARRIVEE_APRES
    if h < a0 or h > c['fin'] + SORTIE:
        return 0.0
    if h < a1:
        return attendus * (h - a0) / (a1 - a0)
    if h <= c['fin']:
        return float(attendus)
    return attendus * (1 - (h - c['fin']) / SORTIE)


class Prevision:
    def __init__(self, campus, config):
        self.campus = campus
        self.config = config
        self._taux = (None, TAUX_PAR_DEFAUT)
        self.verifications = deque()            # (salle, heure visée, CO2 prévu, horizon en min)
        self.erreurs = {30: deque(maxlen=300), 60: deque(maxlen=300)}
        self.derniere_verif = 0

    # ---------- qui sera là ----------

    def taux(self, jour):
        """Taux de présence des 14 derniers jours (recalculé une fois par jour)."""
        if self._taux[0] != jour:
            self._taux = (jour, self.campus.registre.taux_presence(jour) or TAUX_PAR_DEFAUT)
        return self._taux[1]

    def attendus(self, c, jour):
        return round(c['effectif'] * self.taux(jour)) + 1            # + l'enseignant

    def occupation(self, salle_id, t, minutes, cours_en_plus=(), sans_cours=()):
        """Nombre de personnes prévu, minute par minute, à partir de maintenant."""
        jour = datetime.fromtimestamp(t).date()
        h0 = heure_de(t)
        cours = [c for c in self.campus.planning.cours_du_jour(jour)
                 if c['salle'] == salle_id and c['id'] not in sans_cours] + list(cours_en_plus)
        n0 = self.campus.salles[salle_id].nombre()
        attendus = {c['id']: self.attendus(c, jour) for c in cours}
        # Cours déjà commencé : on part du nombre mesuré maintenant plutôt que du nombre attendu
        echelle = {}
        en_cours = [c for c in cours if c['debut'] + ARRIVEE_APRES <= h0 <= c['fin']]
        prevu_maintenant = sum(profil(c, h0, attendus[c['id']]) for c in en_cours)
        for c in en_cours:
            echelle[c['id']] = n0 / prevu_maintenant if prevu_maintenant else 1.0
        dans_un_cours = any(profil(c, h0, attendus[c['id']]) > 0 for c in cours)
        serie = []
        for k in range(minutes):
            h = h0 + k / 60
            n = sum(profil(c, h, attendus[c['id']]) * echelle.get(c['id'], 1.0) for c in cours)
            if not dans_un_cours and n0:
                n += n0 * max(0.0, 1 - (h - h0) / 0.25)                 # présents hors cours : partis dans 15 min
            serie.append(n)
        return serie

    # ---------- avec quel débit ----------

    def debit(self, salle_id, occupee, niveau=None):
        """Débit (m3/h) et d'où il vient : 'automate', 'appris' ou 'a priori'."""
        s = self.campus.salles[salle_id]
        q = s.estimateur.debit_appris(occupee, niveau)
        if niveau in s.estimateur.debits:
            return q, 'automate'
        if q:
            return q, 'appris'
        return DEBIT_PAR_PLACE * s.salle['places'], 'a priori'

    def simuler(self, salle_id, c0, occupation, niveaux=None):
        """CO2 minute par minute. niveaux : vitesse de ventilation de chaque minute (salle de l'automate)."""
        s = self.campus.salles[salle_id]
        v = s.estimateur.volume
        g = self.config.G_PERSONNE
        c_ext = self.config.C_EXT
        debits = {}                              # (occupée, niveau) -> débit, calculé une fois
        c = c0
        serie = []
        for k, n in enumerate(occupation):
            cle = (n >= 1, niveaux[k] if niveaux else None)
            if cle not in debits:
                q = self.debit(salle_id, *cle)[0]
                debits[cle] = (q, exp(-q / v / 60))
            q, amorti = debits[cle]
            c_eq = c_ext + n * g * 1e6 / q
            c = c_eq + (c - c_eq) * amorti
            serie.append(c)
        return serie

    # ---------- prévision d'une salle ----------

    def prevoir(self, salle_id, t, minutes=120, niveaux=None, cours_en_plus=(), sans_cours=()):
        s = self.campus.salles[salle_id]
        if s.co2 is None:
            return None
        c0 = s.co2 - s.estimateur.correction
        n = self.occupation(salle_id, t, minutes, cours_en_plus, sans_cours)
        if s.estimateur.debits:
            # Salle de l'automate : le plan du jumeau, puis (au-delà, ou sans plan) les règles qu'il suit :
            # au moins la petite vitesse quand il y a du monde, la grande au-dessus de 15 personnes
            plan = list(niveaux or [])
            repos = plan[-1] if plan else (s.niveau or 'petite')
            niveaux = [plan[k] if k < len(plan) else ('grande' if n[k] > 15 else 'petite' if n[k] >= 1 else repos)
                       for k in range(minutes)]
        co2 = self.simuler(salle_id, c0, n, niveaux)
        h0 = heure_de(t)
        pic = max(range(len(co2)), key=lambda k: co2[k]) if co2 else 0

        def premier_au_dessus(seuil):
            k = next((i for i, x in enumerate(co2) if x >= seuil), None)
            return h0 + k / 60 if k is not None else None

        _, source = self.debit(salle_id, True, niveaux[0] if niveaux else None)
        return {
            'salle': salle_id,
            'maintenant': round(c0),
            'heure': h0,
            'co2': co2,
            'personnes': n,
            'pic': {'co2': round(co2[pic]), 'heure': h0 + pic / 60} if co2 else None,
            'au_dessus_1000': premier_au_dessus(1000),
            'au_dessus_1200': premier_au_dessus(1200),
            'source_debit': source,
        }

    def resume(self, p, pas=5):
        """Version légère pour l'interface : un point toutes les 5 min."""
        if p is None:
            return None
        return {k: v for k, v in p.items() if k not in ('co2', 'personnes')} | {
            'serie': [{'heure': p['heure'] + k / 60, 'co2': round(p['co2'][k]), 'personnes': round(p['personnes'][k], 1)}
                      for k in range(0, len(p['co2']), pas)]}

    # ---------- précision des prévisions ----------

    def verifier(self, t, plans=None):
        """Toutes les 10 min : on note ce qu'on prévoit à 30 et 60 min, et on compare aux mesures arrivées."""
        if abs(t - self.derniere_verif) < 600:
            return
        self.derniere_verif = t
        for sid, s in self.campus.salles.items():
            p = self.prevoir(sid, t, 61, niveaux=(plans or {}).get(sid))
            if p:
                for horizon in (30, 60):
                    self.verifications.append((sid, t + horizon * 60, p['co2'][horizon], horizon))
        restantes = deque()
        for sid, cible, prevu, horizon in self.verifications:
            if cible > t:
                restantes.append((sid, cible, prevu, horizon))
                continue
            mesure = next((c for tm, c, _ in reversed(self.campus.salles[sid].historique) if abs(tm - cible) <= 90), None)
            if mesure is not None:
                self.erreurs[horizon].append(abs(prevu - mesure))
        self.verifications = restantes

    def precision(self):
        return {f'{h} min': {'erreur_moyenne': round(sum(e) / len(e)) if e else None, 'n': len(e)}
                for h, e in self.erreurs.items()}
