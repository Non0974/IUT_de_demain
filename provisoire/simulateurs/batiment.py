"""Simulation de tout le bâtiment, pour tester le serveur sans matériel.

Elle envoie exactement les messages que enverront les vraies cartes ESP32 :
  co2      : {"type": "co2", "salle", "co2", "temp", "t"}            toutes les 30 s (SAR 200) ou 60 s
  passage  : {"type": "passage", "salle", "sens": +1/-1, "t"}        capteurs de la porte (SAR 200)
  presence : {"type": "presence", "salle", "presence": bool, "t"}    radar de la porte (SAR 200)
  badge    : {"type": "badge", "salle", "carte": empreinte, "t"}     lecteur NFC de chaque salle
  wifi     : {"type": "wifi", "bornes": {salle: appareils}, "t"}     export de la DSI, toutes les minutes
Le temps "t" est simulé (secondes depuis 1970), il peut aller plus vite que le vrai.
"""

import hashlib
import json
import random
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DONNEES = RACINE / 'jumeau3d' / 'donnees'

C_EXT = 420
G_REEL = 0.0195            # m3/h de CO2 par personne (un peu différent du modèle, exprès)
SEL = 'campustwin-demo'    # sel du hachage des cartes (le vrai est secret, dans la config du serveur)

# Débit de la ventilation de SAR 200 selon la commande de l'automate (m3/h, fuites comprises)
DEBITS_SAR200 = {'arret': 25, 'petite': 375, 'grande': 725}
DEBUT_SEMAINE = datetime(2026, 3, 9, 7, 0)   # lundi 9 mars 2026, 7 h
ABSENCES = (0.03, 0.20)     # part d'absents d'un groupe, tirée une fois pour chaque groupe
VENDREDI_APRES_MIDI = 0.08  # absents en plus le vendredi après-midi


def part_absents(cle, date, debut):
    """Probabilité qu'un étudiant du groupe manque ce cours (inventée, pour que le jumeau ait à apprendre)."""
    p = random.Random(f'absences-{cle}').uniform(*ABSENCES)
    return p + (VENDREDI_APRES_MIDI if date.weekday() == 4 and debut >= 12.5 else 0)


def empreinte(uid):
    return hashlib.sha256((SEL + uid).encode()).hexdigest()[:16]


class SalleSimulee:
    def __init__(self, salle, hauteur, alea):
        self.id = salle['id']
        self.places = salle['places']
        self.volume = salle['surface'] * hauteur
        self.ventilation = salle['ventilation']
        self.equipee = salle['equipee']
        self.alea = alea
        self.C = C_EXT + 30
        self.T_fenetre = 20.0
        self.n_reel = 0
        self.compteur_porte = 0     # ce que les capteurs de la porte ont compté
        self.pannes = {'ventilation': False, 'fenetre': False, 'derive': False, 'comptage': False,
                       'badgePrete': False, 'sansBadge': False}
        self.niveau = 'petite'

    def debit(self, heure):
        if self.equipee:
            q = DEBITS_SAR200[self.niveau]
            if self.pannes['ventilation']:
                q = 25 + 0.15 * (q - 25)
            return q + (450 if self.pannes['fenetre'] else 0)
        infiltration = 0.2 * self.volume
        if self.ventilation == 'meca':
            return infiltration + (25 * self.places if 7.5 <= heure <= 19.5 else 0)
        if self.ventilation == 'faible':
            return infiltration + 8 * self.places
        return infiltration + (12 * self.places if self.n_reel else 3 * self.places)

    def physique(self, dt_h, heure):
        q = self.debit(heure)
        production = self.n_reel * G_REEL * 1e6 / self.volume
        self.C += dt_h * (production - q / self.volume * (self.C - C_EXT))
        cible = 13 if self.pannes['fenetre'] else 20
        self.T_fenetre += (cible - self.T_fenetre) * min(1, dt_h / (5 / 60))

    def mesure_co2(self):
        derive = 150 if self.pannes['derive'] else 0
        return round(self.C + derive + self.alea.gauss(0, 8), 1)


class SimulateurBatiment:
    def __init__(self, envoyer, niveau_commande=lambda salle: 'petite', graine=1, debut=DEBUT_SEMAINE, cours_du_jour=None):
        """envoyer(message) : reçoit chaque message ; niveau_commande(salle) : commande de l'automate ;
        debut : date et heure du début de la simulation ;
        cours_du_jour(date) : cours du jour avec les salles changées (par défaut, l'emploi du temps tel quel)."""
        self.envoyer = envoyer
        self.niveau_commande = niveau_commande
        self.alea = random.Random(graine)
        bat = json.loads((DONNEES / 'salles.json').read_text(encoding='utf-8'))
        edt = json.loads((DONNEES / 'edt.json').read_text(encoding='utf-8'))
        self.groupes = edt['groupes']
        self.cours = edt['cours']
        self.cours_du_jour = cours_du_jour or (lambda d: [c for c in self.cours if c['jour'] == d.weekday()])
        self.salles = {s['id']: SalleSimulee(s, bat['hauteur'], self.alea) for s in bat['salles']}
        self.t = debut.timestamp()
        self.jour_prepare = None
        self.cartes = {}            # empreinte -> {id, groupe}
        self.uid = {}               # id étudiant -> uid de sa carte
        self.prochain_co2 = {s: 0 for s in self.salles}
        self.prochain_wifi = 0

    # ---------- étudiants et cartes ----------

    def _carte(self, etudiant, groupe):
        if etudiant not in self.uid:
            uid = ''.join(f'{self.alea.randrange(256):02X}' for _ in range(7))
            self.uid[etudiant] = uid
            self.cartes[empreinte(uid)] = {'id': etudiant, 'groupe': groupe}
        return self.uid[etudiant]

    def annuaire(self):
        """Ce que la scolarité donnerait au serveur : empreinte de carte -> étudiant (pseudonyme) ou enseignant."""
        for c in self.cours:
            self._carte(c['enseignant'], 'enseignant')
            for cle in c['cles']:
                effectif = self.groupes[cle]['effectif'] if cle in self.groupes else c['effectif']
                for i in range(effectif):
                    self._carte(f'{cle}-{i + 1:02d}', cle)
        return dict(self.cartes)

    def _preparer_jour(self, date):
        alea = random.Random(1000 + date.toordinal())
        self.participations = {}
        for c in self.cours_du_jour(date.date()):
            if not c['salle']:
                continue
            personnes = []
            for cle in c['cles']:
                effectif = self.groupes[cle]['effectif'] if cle in self.groupes else c['effectif']
                absents = part_absents(cle, date, c['debut'])
                for i in range(effectif):
                    retard = alea.random() < 0.06
                    personnes.append({
                        'id': f'{cle}-{i + 1:02d}', 'groupe': cle, 'etudiant': True,
                        'absent': alea.random() < absents,
                        'arrivee': c['debut'] + (10 + 15 * alea.random() if retard else -8 + 12 * alea.random()) / 60,
                        'depart': c['fin'] + 3 * alea.random() / 60,
                        'badge': alea.random() > 0.03,
                        'appareils': 0 if alea.random() < 0.15 else (1 if alea.random() < 0.7 else 2),
                        'dedans': False, 'a_badge': False,
                    })
            # l'enseignant badge aussi en arrivant : il ouvre la séance
            personnes.append({'id': c['enseignant'], 'groupe': 'enseignant', 'etudiant': False, 'absent': False,
                              'arrivee': c['debut'] - 5 / 60, 'depart': c['fin'] + 5 / 60, 'badge': True,
                              'appareils': 1, 'dedans': False, 'a_badge': False})
            self.participations[c['id']] = (c, personnes)
        self.fraudes_faites = set()

    # ---------- un pas de temps ----------

    def pas(self, dt_s=10):
        self.t += dt_s
        date = datetime.fromtimestamp(self.t)
        heure = date.hour + date.minute / 60 + date.second / 3600
        if date.date() != self.jour_prepare:
            self.jour_prepare = date.date()
            self._preparer_jour(date)
        if heure >= 21:                        # nuit : on saute au lendemain 7 h (week-end compris)
            suivant = datetime.fromordinal(date.toordinal() + 1).replace(hour=7)
            while suivant.weekday() >= 5:
                suivant = datetime.fromordinal(suivant.toordinal() + 1).replace(hour=7)
            self.t = suivant.timestamp()
            for s in self.salles.values():
                s.C = C_EXT + 20 + (s.C - C_EXT) * 0.05
            return

        entrees = {s: [] for s in self.salles}
        sorties = {s: [] for s in self.salles}
        appareils = {s: 0 for s in self.salles}
        salles_du_jour = {c['id']: c['salle'] for c in self.cours_du_jour(date.date())}
        for c, personnes in self.participations.values():
            salle = self.salles[salles_du_jour.get(c['id']) or c['salle']]   # un cours déplacé va dans sa nouvelle salle
            for p in personnes:
                dedans = not p['absent'] and p['arrivee'] <= heure < p['depart']
                if dedans and not p['dedans']:
                    instant = self.t - dt_s + self.alea.random() * dt_s      # heure précise dans le pas
                    entrees[salle.id].append(instant)
                    if p['badge'] and not p['a_badge']:
                        p['a_badge'] = True
                        if p['etudiant'] and salle.pannes['sansBadge'] and ('sans', c['id']) not in self.fraudes_faites:
                            self.fraudes_faites.add(('sans', c['id']))     # il entre sans badger
                        else:
                            self._badge(salle.id, self._carte(p['id'], p['groupe']), instant)
                            if p['etudiant'] and salle.pannes['badgePrete'] and ('pret', c['id']) not in self.fraudes_faites:
                                absent = next((q for q in personnes if q['etudiant'] and q['absent']), None)
                                if absent:
                                    # il badge aussi la carte d'un absent, juste après la sienne
                                    self.fraudes_faites.add(('pret', c['id']))
                                    self._badge(salle.id, self._carte(absent['id'], absent['groupe']), instant + 1.5)
                elif not dedans and p['dedans']:
                    sorties[salle.id].append(self.t - dt_s + self.alea.random() * dt_s)
                p['dedans'] = dedans
                if dedans:
                    appareils[salle.id] += sum(1 for _ in range(p['appareils']) if self.alea.random() < 0.92)

        for s in self.salles.values():
            s.n_reel += len(entrees[s.id]) - len(sorties[s.id])
            if s.equipee:
                s.niveau = self.niveau_commande(s.id)
                self._porte(s, entrees[s.id], sorties[s.id])
            s.physique(dt_s / 3600, heure)
            if self.t >= self.prochain_co2[s.id]:
                self.prochain_co2[s.id] = self.t + (30 if s.equipee else 60)
                msg = {'type': 'co2', 'salle': s.id, 'co2': s.mesure_co2(), 't': self.t}
                if s.equipee:
                    msg['temp'] = round(s.T_fenetre + self.alea.gauss(0, 0.1), 2)
                    self.envoyer({'type': 'presence', 'salle': s.id, 'presence': s.n_reel > 0, 't': self.t})
                self.envoyer(msg)
        if self.t >= self.prochain_wifi:
            self.prochain_wifi = self.t + 60
            bornes = {k: v + (1 if self.alea.random() < 0.15 else 0) for k, v in appareils.items()}
            self.envoyer({'type': 'wifi', 'bornes': bornes, 't': self.t})

    def _badge(self, salle, uid, instant):
        self.envoyer({'type': 'badge', 'salle': salle, 'carte': empreinte(uid), 't': instant})

    def _porte(self, s, entrees, sorties):
        """Fusion ToF + thermique + radar : ~97 % des passages bien comptés."""
        for sens, instants in ((1, entrees), (-1, sorties)):
            for instant in instants:
                r = self.alea.random()
                comptes = 0 if r < 0.02 else (2 if r < 0.03 else 1)
                if s.pannes['comptage'] and sens > 0 and self.alea.random() < 0.5:
                    comptes += 1                   # panne : un passage d'entrée sur deux compté double
                for k in range(comptes):
                    self.envoyer({'type': 'passage', 'salle': s.id, 'sens': sens, 't': instant + 0.5 * k})


if __name__ == '__main__':
    # Envoie la simulation à un serveur distant, comme le feraient les cartes ESP32
    import argparse
    import time
    import urllib.request

    p = argparse.ArgumentParser(description='Simulation du bâtiment qui envoie ses mesures au serveur')
    p.add_argument('--url', default='http://localhost:8000', help='adresse du serveur')
    p.add_argument('--cle', default='', help='clé des capteurs (config du serveur)')
    p.add_argument('--vitesse', type=float, default=60, help='secondes simulées par seconde réelle')
    a = p.parse_args()

    def poster(chemin, message):
        req = urllib.request.Request(a.url + chemin, data=json.dumps(message).encode(), method='POST',
                                     headers={'Content-Type': 'application/json', 'X-Cle': a.cle})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read() or b'{}')

    def niveau(salle):
        try:
            with urllib.request.urlopen(a.url + '/api/etat', timeout=5) as r:
                return json.loads(r.read())['salles'][salle].get('niveau') or 'petite'
        except Exception:
            return 'petite'

    sim = SimulateurBatiment(lambda m: poster('/api/mesure', m), niveau)
    poster('/api/cartes', sim.annuaire())
    while True:
        debut = time.time()
        sim.pas(10)
        time.sleep(max(0, 10 / a.vitesse - (time.time() - debut)))
