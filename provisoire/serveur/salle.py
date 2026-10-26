"""État d'une salle côté serveur : nombre de personnes, émargement, Wi-Fi et air."""

from collections import deque
from datetime import datetime

from estimateur import EstimateurSalle
from planning import Planning

TOLERANCE = 10 / 3600           # h : un badge et un passage à moins de 10 s vont ensemble
DOUBLE_BADGE = 3                # s : deux cartes badgées à moins de 3 s pour un seul passage = carte prêtée
RETARD = 10 / 60                # h après le début du cours


def heure_du_jour(t):
    d = datetime.fromtimestamp(t)
    return d.hour + d.minute / 60 + d.second / 3600


def seance_id(cours, t):
    """Une séance = un cours de l'emploi du temps, un jour donné (le même cours revient chaque semaine)."""
    return f'{datetime.fromtimestamp(t):%Y-%m-%d}_{cours["id"]}'


def anomalies_vides():
    return {'sans_badge': [], 'pretes': [], 'badges_seuls': []}


class ModeleWifi:
    """Nombre de personnes = a x appareils + b.
    On part d'un modèle commun, puis chaque salle s'en éloigne doucement à mesure qu'elle accumule
    de vraies mesures (capteurs de la porte, ou badges + enseignant pendant les cours).
    Sur ROBOD, recaler une salle sur 1 à 3 jours faisait parfois pire que ne rien faire :
    il faut des semaines de données, d'où le mélange avec le modèle commun (POIDS_COMMUN)."""

    POIDS_COMMUN = 1500          # le modèle commun pèse autant que 1500 minutes de mesures de la salle

    def __init__(self, a=1 / 1.1, b=0.0):
        self.a_commun, self.b_commun = a, b
        self.a, self.b = a, b
        self.points = deque(maxlen=20000)       # environ 6 semaines de cours
        self.lisse = 0.0

    def apprendre(self, appareils, vrai):
        self.points.append((appareils, vrai))
        n = len(self.points)
        if n >= 60 and n % 20 == 0:
            xs = [p[0] for p in self.points]
            ys = [p[1] for p in self.points]
            mx, my = sum(xs) / n, sum(ys) / n
            vx = sum((x - mx) ** 2 for x in xs)
            if vx > 10:
                a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx
                b = my - a * mx
                poids = n / (n + self.POIDS_COMMUN)
                self.a = poids * a + (1 - poids) * self.a_commun
                self.b = poids * b + (1 - poids) * self.b_commun

    def estimer(self, appareils):
        self.lisse += (appareils - self.lisse) * 0.3
        return max(0, round(self.a * self.lisse + self.b))


class EtatSalle:
    def __init__(self, salle, hauteur, config, edt, annuaire, planning=None):
        self.id = salle['id']
        self.salle = salle
        self.edt = edt
        self.planning = planning or Planning(edt)   # cours du jour, salles changées comprises
        self.annuaire = annuaire            # empreinte de carte -> {id, groupe}
        self.porte = salle['equipee']        # capteurs de comptage à la porte
        debits = config.DEBITS.get(self.id)
        # Le biais compare le comptage de la porte et la décroissance : sans capteurs à la porte, il n'a
        # pas de sens. Il mélangerait même deux débits vraiment différents (fenêtre ouverte en cours).
        biais = config.BIAIS_CONNU.get(self.id, None if salle['equipee'] else 1.0)
        self.estimateur = EstimateurSalle(salle['surface'] * hauteur, debits, config.G_PERSONNE, config.C_EXT, biais=biais)
        self.wifi = ModeleWifi()
        self.n_porte = 0
        self.n_wifi = None
        self.appareils = None
        self.presence = None
        self.sans_presence_depuis = None
        self.co2 = None
        self.temp = None
        self.niveau = None                   # commande de ventilation (connue pour la salle de l'automate)
        self.t = None
        self.attente_badges = deque()        # (identité, t)
        self.badges_apparies = deque(maxlen=30)   # badges qui ont eu leur passage
        self.attente_passages = deque()      # t
        self.badges = {}                     # id séance -> {id étudiant: heure du badge}
        self.anomalies = {}                  # id séance -> {'sans_badge': [t], 'pretes': [[ids], t], 'badges_seuls': [t]}
        self.historique = deque(maxlen=14 * 60)   # (t, CO2, N) une fois par minute

    # ---------- nombre de personnes ----------

    def nombre(self):
        if self.porte:
            return self.n_porte
        return self.n_wifi if self.n_wifi is not None else 0

    def source(self):
        return 'porte' if self.porte else 'wifi'

    # ---------- messages des capteurs ----------

    def passage(self, t, sens):
        self.n_porte = max(0, self.n_porte + sens)
        if sens > 0:
            self.attente_passages.append(t)
        self._apparier(t)

    def presence_radar(self, t, presence):
        # Le radar ne voit personne pendant 2 min : la salle est vide, on remet le compteur à 0
        self.presence = presence
        if presence:
            self.sans_presence_depuis = None
        else:
            self.sans_presence_depuis = self.sans_presence_depuis or t
            if t - self.sans_presence_depuis > 120:
                self.n_porte = 0

    def badge(self, t, carte):
        cours = self.cours_actifs(t, marge_avant=15 / 60)
        personne = self.annuaire.get(carte)
        ident = personne['id'] if personne else f'carte inconnue {carte[:6]}'
        if not personne or personne['groupe'] != 'enseignant':     # l'enseignant badge pour ouvrir la séance
            for c in cours:
                if not personne or personne['groupe'] in c['cles']:
                    self.badges.setdefault(seance_id(c, t), {}).setdefault(ident, t)
        if self.porte:
            self.attente_badges.append((ident, t))
            self._apparier(t)

    def mesure_wifi(self, t, appareils):
        self.appareils = appareils
        self.n_wifi = self.wifi.estimer(appareils)
        # Recalage du Wi-Fi sur une vraie mesure du nombre de personnes
        if self.porte:
            self.wifi.apprendre(appareils, self.n_porte)
        else:
            cours = self.cours_actifs(t)
            if cours and all(t / 3600 > c_debut + 0.25 for c_debut in self._debuts_absolus(cours, t)):
                vrais = sum(len(self.badges.get(seance_id(c, t), {})) for c in cours) + len(cours)
                self.wifi.apprendre(appareils, vrais)
            elif not cours:
                self.wifi.apprendre(appareils, 0)

    def mesure_co2(self, t, co2, temp=None):
        self.t = t
        self.co2 = co2
        if temp is not None:
            self.temp = temp
        self.estimateur.ajouter(t / 3600, heure_du_jour(t), co2, self.nombre(), self.niveau, temp)
        if not self.historique or t - self.historique[-1][0] >= 60:
            if self.historique and heure_du_jour(t) < heure_du_jour(self.historique[-1][0]):
                self.historique.clear()          # nouveau jour
            self.historique.append((t, co2 - self.estimateur.correction, self.nombre()))

    # ---------- émargement vérifié (salle avec capteurs à la porte) ----------

    def _apparier(self, t):
        h = t / 3600
        cours = self.cours_actifs(t, marge_avant=15 / 60)
        cle = seance_id(cours[0], t) if cours else None
        anomalies = self.anomalies.setdefault(cle, anomalies_vides()) if cle else None
        # On associe d'abord le badge et le passage les plus proches dans le temps (moins de 10 s),
        # sinon un passage raté décalerait toutes les paires suivantes
        while True:
            paires = [(abs(p - b[1]), b, p) for b in self.attente_badges for p in self.attente_passages
                      if abs(p - b[1]) <= TOLERANCE * 3600]
            if not paires:
                break
            _, b, p = min(paires, key=lambda x: x[0])
            self.attente_passages.remove(p)
            self.attente_badges.remove(b)
            self.badges_apparies.append(b)
        # Badges restés seuls plus de 10 s
        seuls = [b for b in self.attente_badges if h - b[1] / 3600 > TOLERANCE]
        for ident, tb in seuls:
            # carte prêtée : un autre badge, lui avec son passage, moins de 3 s avant ou après
            voisin = next((b for b in self.badges_apparies if b[0] != ident and abs(tb - b[1]) <= DOUBLE_BADGE), None)
            if anomalies is not None:
                if voisin:
                    # deux cartes en 3 s pour un seul passage : quelqu'un badge pour un absent
                    anomalies['pretes'].append([[voisin[0], ident], tb])
                else:
                    anomalies['badges_seuls'].append(tb)   # plutôt un passage que la porte n'a pas compté
        if seuls:
            self.attente_badges = deque(b for b in self.attente_badges if h - b[1] / 3600 <= TOLERANCE)
        # Passages restés seuls plus de 10 s
        passages_seuls = [p for p in self.attente_passages if h - p / 3600 > TOLERANCE]
        if passages_seuls:
            if anomalies is not None:
                anomalies['sans_badge'].extend(passages_seuls)
            self.attente_passages = deque(p for p in self.attente_passages if h - p / 3600 <= TOLERANCE)

    # ---------- emploi du temps ----------

    def _debuts_absolus(self, cours, t):
        d = datetime.fromtimestamp(t)
        minuit = datetime(d.year, d.month, d.day).timestamp() / 3600
        return [minuit + c['debut'] for c in cours]

    def cours_actifs(self, t, marge_avant=10 / 60):
        d = datetime.fromtimestamp(t)
        h = heure_du_jour(t)
        return [c for c in self.planning.cours_du_jour(d.date()) if c['salle'] == self.id
                and c['debut'] - marge_avant <= h <= c['fin'] + 5 / 60]

    def inscrits(self, cours):
        ids = []
        for cle in cours['cles']:
            groupe = self.edt['groupes'].get(cle)
            effectif = groupe['effectif'] if groupe else cours['effectif']
            ids += [f'{cle}-{i + 1:02d}' for i in range(effectif)]
        return ids

    # ---------- émargement d'une séance ----------

    def emargement(self, c, t):
        """Statut de chaque inscrit de la séance à l'heure t, et les anomalies badge / passage."""
        h = heure_du_jour(t)
        sid = seance_id(c, t)
        badges = self.badges.get(sid, {})
        anomalies = self.anomalies.get(sid, anomalies_vides())
        suspects = {i for ids, _ in anomalies['pretes'] for i in ids}
        liste = []
        for ident in self.inscrits(c):
            tb = badges.get(ident)
            if ident in suspects:
                statut = 'à vérifier'
            elif tb is not None:
                statut = 'retard' if heure_du_jour(tb) > c['debut'] + RETARD else 'présent'
            else:
                statut = 'attendu' if h < c['debut'] + RETARD else 'absent'
            liste.append({'id': ident, 'statut': statut, 'badge': tb})
        return liste, anomalies, len(badges)

    def alertes_emargement(self, anomalies):
        alertes = []
        n_sans = len(anomalies['sans_badge'])
        n_seuls = len(anomalies['badges_seuls'])
        if n_sans >= 3:
            alertes.append({'niveau': 'suspect', 'texte': f"{n_sans} passages de plus que de badges : c'est sûrement le comptage qui se trompe."})
        elif n_sans:
            pluriel = 's' if n_sans > 1 else ''
            alertes.append({'niveau': 'suspect', 'texte': f"{n_sans} entrée{pluriel} sans badge (oubli, ou erreur de comptage). L'enseignant vérifie."})
        if n_seuls >= 3:
            alertes.append({'niveau': 'suspect', 'texte': f'{n_seuls} badges sans passage compté : la porte compte mal ?'})
        for ids, tb in anomalies['pretes']:
            alertes.append({'niveau': 'detecte', 'texte': f'{" et ".join(ids)} : {len(ids)} badges pour un seul passage. Une carte est prêtée.'})
        return alertes

    # ---------- ce qu'on envoie à l'interface ----------

    def etat(self, t):
        cours = []
        alertes = []
        for c in self.cours_actifs(t):
            liste, anomalies, n_badges = self.emargement(c, t)
            alertes += self.alertes_emargement(anomalies)
            cours.append({**c, 'seance': seance_id(c, t), 'badges': n_badges,
                          'emargement': [{'id': x['id'], 'statut': x['statut']} for x in liste]})

        if self.co2 is not None:
            c_aff = self.co2 - self.estimateur.correction
            if c_aff >= 1200:
                alertes.append({'niveau': 'detecte', 'texte': f'Air mauvais : {round(c_aff)} ppm de CO₂. Il faut aérer.'})
            elif c_aff >= 800:
                alertes.append({'niveau': 'suspect', 'texte': f'Air moyen : {round(c_aff)} ppm de CO₂.'})
        # Plus de monde que de places pendant 5 min, en plein cours (pas au croisement de deux cours, ni à la
        # sortie : le Wi-Fi est lissé, il suit les départs avec retard). Le Wi-Fi compte à 2 personnes près :
        # on lui laisse cette marge. + 1 : l'enseignant.
        h = heure_du_jour(t)
        en_plein_cours = any(c['debut'] + 10 / 60 <= h <= c['fin'] for c in cours)
        places = self.salle['places'] + 1 + (0 if self.porte else 2)
        recents = [n for _, _, n in list(self.historique)[-5:]]
        if en_plein_cours and len(recents) == 5 and min(recents + [self.nombre()]) > places:
            alertes.append({'niveau': 'detecte' if self.porte else 'suspect',
                            'texte': f'Plus de monde que de places : {self.nombre()} personnes pour {self.salle["places"]} places.'})
        if not self.porte and cours and self.n_wifi is not None:
            badges = sum(c['badges'] for c in cours) + len(cours)
            if self.n_wifi - badges >= 6:
                alertes.append({'niveau': 'suspect', 'texte': f'Le Wi-Fi voit {self.n_wifi} personnes pour {badges - len(cours)} badges : à vérifier.'})

        estim = self.estimateur.resume()
        if not self.porte:
            estim['diagnostic'].pop('comptage', None)
        for cle, cause in estim['diagnostic'].items():
            if cause['etat'] == 'detecte' and cle not in ('derive',):
                alertes.append({'niveau': 'detecte', 'texte': f'{cause["titre"]} : {cause["message"]}'})
        return {
            'id': self.id,
            'personnes': self.nombre(),
            'source': self.source(),
            'n_wifi': self.n_wifi,
            'appareils': self.appareils,
            'co2': round(self.co2 - self.estimateur.correction) if self.co2 is not None else None,
            'co2_brut': self.co2,
            'temp': self.temp,
            'niveau': self.niveau,
            'cours': cours,
            'alertes': alertes,
            'air': estim,
            'wifi_modele': {'a': round(self.wifi.a, 3), 'b': round(self.wifi.b, 2), 'points': len(self.wifi.points)},
        }
