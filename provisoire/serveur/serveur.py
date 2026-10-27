"""Serveur CampusTwin : reçoit les mesures des cartes ESP32, calcule l'état de chaque salle
(personnes, émargement, Wi-Fi, air, diagnostic), tient le registre des présences, pilote
l'automate et sert l'interface de suivi des classes et le jumeau 3D.

Python seul suffit (aucune bibliothèque à installer), sauf pour l'assistant IA : pip install anthropic.

    python serveur/serveur.py                         vraies cartes et vrai automate (voir config.py)
    python serveur/serveur.py --simulation            bâtiment simulé + automate simulé, pour tester
    python serveur/serveur.py --simulation --vitesse 300 --historique 0

Puis ouvrir http://localhost:8000 (interface de suivi des classes).
En simulation, comptes de démonstration : directeur / demo, enseignant / demo et technique / demo.
"""

import argparse
import csv
import functools
import json
import sys
import threading
import time
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib import util
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
sys.path.insert(0, str(ICI))

import config                                   # noqa: E402
from assistant import SUGGESTIONS, Assistant, ErreurIA, Indisponible, Occupe   # noqa: E402
from ambiance import BilanAmbiance, decider as decider_ambiance   # noqa: E402
from automate import PontAutomate, niveau_automatique   # noqa: E402
from capacite import capacite                    # noqa: E402
from commande import HORIZON, BilanVentilation, CommandePredictive, bornes_vitesse   # noqa: E402
from comptes import Comptes, comptes_de_demo    # noqa: E402
from planning import Planning                   # noqa: E402
from prevision import Prevision                 # noqa: E402
from reaffectation import propositions          # noqa: E402
from registre import Registre                   # noqa: E402
from salle import EtatSalle, heure_du_jour, seance_id   # noqa: E402
from stockage import Stockage                   # noqa: E402
from suivi import TOUT_VOIR, Refus, Suivi, periode     # noqa: E402
from temoin import Temoin                       # noqa: E402
from ondes import ENTETE as ENTETE_ONDES, ligne_csv   # noqa: E402
from tickets import OBJETS, SERVICES, STATUTS, analyser, nouveau, pannes_detectees, titre, trier   # noqa: E402
from transports import PontPrim, Transports     # noqa: E402

WEB = RACINE / 'jumeau3d'
DONNEES = WEB / 'donnees'
FICHIER_CARTES = ICI / 'cartes.json'            # empreinte de carte -> étudiant (fourni par la scolarité)
FICHIER_ONDES = ICI / 'ondes.csv'              # mesures des ondes Wi-Fi + vrai nombre de personnes (apprentissage)
FICHIER_ENSEIGNANTS = ICI / 'enseignants.json'  # "Enseignant A" -> vrai nom (seulement en local, pas sur GitHub)
SYNCHRO = 30                                    # s entre deux copies de l'émargement dans le registre
VERIF_PANNES = 300                              # s entre deux recherches de pannes (tickets du jumeau)
PAUSE_TICKET = 12 * 3600                        # s : un ticket du jumeau résolu n'est pas rouvert avant
TICKETS_RESOLUS = 7 * 86400                     # s : les tickets résolus restent visibles une semaine


def charger_enseignants():
    """« Enseignant A » -> vrai nom, si serveur/enseignants.json existe (seulement en local)."""
    return json.loads(FICHIER_ENSEIGNANTS.read_text(encoding='utf-8')) if FICHIER_ENSEIGNANTS.exists() else {}


def charger_edt():
    """Emploi du temps. Dans le dépôt public, les enseignants s'appellent « Enseignant A, B… » ;
    si serveur/enseignants.json existe, on remet les vrais noms."""
    edt = json.loads((DONNEES / 'edt.json').read_text(encoding='utf-8'))
    noms = charger_enseignants()
    for c in edt['cours']:
        c['enseignant'] = noms.get(c['enseignant'], c['enseignant'])
    return edt


def enseignant_de_demo(edt):
    """Compte « enseignant » de la démonstration : l'enseignant du premier vrai cours de la semaine."""
    return min((c for c in edt['cours'] if c['reel'] and c['salle']), key=lambda c: (c['jour'], c['debut']))['enseignant']


def charger_simulateur(nom):
    """Charge un module de simulateurs/ (il porte parfois le même nom qu'un module du serveur)."""
    spec = util.spec_from_file_location(f'{nom}_simule', RACINE / 'simulateurs' / f'{nom}.py')
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Campus:
    def __init__(self, stockage, pont, registre=None):
        bat = json.loads((DONNEES / 'salles.json').read_text(encoding='utf-8'))
        self.edt = charger_edt()
        self.annuaire = json.loads(FICHIER_CARTES.read_text(encoding='utf-8')) if FICHIER_CARTES.exists() else {}
        noms_groupes = {cle: c['groupes'][i] for c in self.edt['cours'] for i, cle in enumerate(c['cles'])}
        self.registre = registre or Registre(noms_groupes=noms_groupes)
        self.registre.noms_groupes = noms_groupes
        self.planning = Planning(self.edt, self.registre)
        self.batiment = bat
        self.batiment_salles = {s['id']: s for s in bat['salles']}
        self.perdues = self.registre.places_perdues()      # places perdues par salle (tickets pas résolus)
        self.derniere_verif_pannes = 0
        self.fichier_ondes = FICHIER_ONDES if stockage else None   # pas en simulation
        self.salles = {s['id']: EtatSalle(s, bat['hauteur'], config, self.edt, self.annuaire, self.planning)
                       for s in bat['salles']}
        self.stockage = stockage
        self.pont = pont
        self.verrou = threading.RLock()
        self.t = time.time()
        self.simulation = None
        self.avance_rapide = False
        self.mode = {'auto': True, 'niveau': 'petite', 'strategie': config.STRATEGIE}
        self.messages = 0
        self.derniere_synchro = 0
        self.cartes_inconnues = {}                   # empreinte -> {salle, t} : badgée, pas encore enregistrée
        self.temoin = Temoin(config)                 # le CO₂ témoin de l'émargement
        self.transports = Transports()               # RER perturbé -> retards prévus
        self.temoins_faits = set()
        # Jumeau prédictif et ventilation anticipée
        self.prevision = Prevision(self, config)
        auto = self.salles.get(config.SALLE_AUTOMATE)
        self.commande = CommandePredictive(config, auto.estimateur.volume) if auto else None
        self.bilan = BilanVentilation(self.commande) if auto else None
        self.bilan_ambiance = BilanAmbiance(config.SALLE_AUTOMATE)
        self.ambiance = (True, 'reduit')              # éclairage, chauffage demandés pour la salle de l'automate
        self.consigne = None
        self.derniere_decision = 0
        self._previsions = (None, None)              # (minute, résultat) : recalculé une fois par minute

    @property
    def noms(self):
        """Vrais noms des étudiants, si la scolarité les a donnés avec les cartes (sinon : pseudonymes)."""
        return {p['id']: p['nom'] for p in self.annuaire.values() if p.get('nom')}

    # ---------- messages des capteurs ----------

    def recevoir(self, m):
        with self.verrou:
            type_ = m.get('type')
            if type_ not in ('wifi', 'transport') and m.get('salle') not in self.salles:
                raise ValueError(f'Salle inconnue : {m.get("salle")}')
            if self.simulation:
                # temps simulé : un message sans heure prend l'heure de la simulation
                t = float(m['t']) if m.get('t') else self.t
                self.t = max(self.t, t)
            elif m.get('t'):
                t = float(m['t'])
                self.t = time.time()
            else:
                # carte sans heure exacte : elle donne l'âge du message (il a pu attendre dans sa file)
                self.t = time.time()
                t = self.t - float(m.get('age_ms', 0)) / 1000
            self.messages += 1
            if self.stockage:
                self.stockage.enregistrer({**m, 't': t})
            if type_ == 'transport':
                self.transports.recevoir(t, str(m['ligne']), bool(m['perturbe']), str(m.get('texte', '')))
                return
            if type_ == 'wifi':
                for salle, n in m.get('bornes', {}).items():
                    if salle in self.salles:
                        self.salles[salle].mesure_wifi(t, int(n))
                return
            salle = self.salles[m['salle']]
            if type_ == 'ondes':
                salle.mesure_ondes(t, m)
                self._garder_ondes(t, salle, m)
                return
            if type_ == 'co2':
                salle.mesure_co2(t, float(m['co2']), m.get('temp'))
            elif type_ == 'passage':
                salle.passage(t, 1 if int(m['sens']) > 0 else -1)
            elif type_ == 'presence':
                salle.presence_radar(t, bool(m['presence']))
            elif type_ == 'badge':
                carte = str(m['carte'])
                salle.badge(t, carte)
                if carte not in self.annuaire:
                    self.cartes_inconnues[carte] = {'salle': salle.id, 't': t}
                return {'connue': carte in self.annuaire}     # le lecteur s'allume en vert ou en orange
            else:
                raise ValueError(f'Type de message inconnu : {type_}')

    def _garder_ondes(self, t, salle, m):
        """Chaque mesure des ondes avec le vrai nombre de personnes : de quoi apprendre à compter."""
        if not self.fichier_ondes:
            return
        nouveau = not self.fichier_ondes.exists()
        with open(self.fichier_ondes, 'a', newline='', encoding='utf-8') as f:
            w = csv.writer(f, delimiter=';')
            if nouveau:
                w.writerow(ENTETE_ONDES)
            w.writerow(ligne_csv(t, salle.id, m, salle.n_porte if salle.porte else None, salle.n_wifi,
                                 bool(salle.cours_actifs(t))))

    def ajouter_cartes(self, cartes):
        with self.verrou:
            self.annuaire.update(cartes)
            self._garder_cartes()

    def _garder_cartes(self):
        if not self.simulation:          # la table des cartes est gardée pour le prochain démarrage
            FICHIER_CARTES.write_text(json.dumps(self.annuaire, ensure_ascii=False, indent=1), encoding='utf-8')

    # ---------- enregistrement des cartes (page « Cartes ») ----------

    def places_cartes(self):
        """Qui peut recevoir une carte : les étudiants des vrais groupes (TP1-01…) et les enseignants."""
        porteurs = {p['id']: p for p in self.annuaire.values()}
        groupes = [{'cle': cle, 'nom': g['nom'],
                    'etudiants': [{'id': i, 'nom': porteurs.get(i, {}).get('nom'), 'carte': i in porteurs}
                                  for i in (f'{cle}-{k + 1:02d}' for k in range(g['effectif']))]}
                   for cle, g in self.edt['groupes'].items()]
        enseignants = sorted({c['enseignant'] for c in self.edt['cours'] if c['reel'] and c['enseignant'] != '—'})
        return groupes, [{'id': e, 'carte': e in porteurs} for e in enseignants]

    def associer_carte(self, empreinte, ident, nom=''):
        """Donne une carte à un étudiant (ou à un enseignant). Elle remplace sa carte d'avant (perdue, changée)."""
        groupes, enseignants = self.places_cartes()
        etudiants = {e['id']: g['cle'] for g in groupes for e in g['etudiants']}
        if ident in etudiants:
            groupe = etudiants[ident]
        elif ident in {e['id'] for e in enseignants}:
            groupe = 'enseignant'
        else:
            raise ValueError('Étudiant ou enseignant inconnu.')
        if not (isinstance(empreinte, str) and len(empreinte) == 16 and all(c in '0123456789abcdef' for c in empreinte)):
            raise ValueError('Empreinte de carte incorrecte.')
        with self.verrou:
            for ancienne in [k for k, p in self.annuaire.items() if p['id'] == ident]:
                del self.annuaire[ancienne]
            self.annuaire[empreinte] = {'id': ident, 'groupe': groupe, **({'nom': nom.strip()} if nom.strip() else {})}
            self.cartes_inconnues.pop(empreinte, None)
            self._garder_cartes()

    def retirer_carte(self, empreinte):
        with self.verrou:
            if self.annuaire.pop(empreinte, None) is None:
                raise KeyError('Carte inconnue.')
            self._garder_cartes()

    # ---------- pilotage de la ventilation ----------

    def piloter(self):
        with self.verrou:
            salle = self.salles.get(config.SALLE_AUTOMATE)
            if salle is None:
                return
            h = heure_du_jour(self.t)
            jour = datetime.fromtimestamp(self.t).date()
            cours = [c for c in self.planning.cours_du_jour(jour) if c['salle'] == salle.id]
            fins = [c['fin'] for c in cours]
            co2 = salle.co2 - salle.estimateur.correction if salle.co2 is not None else None

            def regle(n, c):
                """Règle simple d'avant : selon le nombre de personnes, petite vitesse toute la journée."""
                return niveau_automatique(n, c, h, max(fins) if fins else None)

            if not self.mode['auto']:
                consigne = self.mode['niveau']
            elif self.mode['strategie'] == 'predictive' and co2 is not None and self.commande:
                # Le jumeau décide une fois par minute, en regardant 90 min devant
                if self.consigne is None or abs(self.t - self.derniere_decision) >= 60:
                    occupation = self.prevision.occupation(salle.id, self.t, HORIZON)
                    bornes = bornes_vitesse(cours, h, HORIZON, occupation, salle.estimateur.mesure_restante())
                    self.consigne = self.commande.decider(co2, occupation, bornes)
                    self.derniere_decision = self.t
                consigne = self.consigne
            else:
                consigne = regle(salle.nombre(), co2)
            # Lumière et chauffage selon l'occupation : le jumeau décide, l'automate applique (et garde la sécurité)
            self.ambiance = decider_ambiance(cours, h, jour.weekday(), salle.nombre())
            self.pont.regler(consigne, personnes=salle.nombre(), eclairage=self.ambiance[0], chauffage=self.ambiance[1])
            etat = self.pont.etat
            # La ventilation suit ce que l'automate applique vraiment (ou la consigne s'il ne répond pas,
            # ou si la simulation avance trop vite pour lui)
            connecte = etat.get('connecte') and etat.get('vitesse') != '?' and not self.avance_rapide
            salle.niveau = etat['vitesse'] if connecte else consigne
            if co2 is not None and self.bilan:
                self.bilan.avancer(self.t, salle.nombre(), co2, salle.niveau, regle)
            self.bilan_ambiance.avancer(self, self.t)

    # ---------- registre des présences ----------

    def synchroniser(self, force=False):
        """Recopie l'émargement des séances en cours dans le registre, et clôt les séances finies."""
        with self.verrou:
            t = self.t
            if not force and abs(t - self.derniere_synchro) < SYNCHRO:
                return
            self.derniere_synchro = t
            for salle in self.salles.values():
                for c in salle.cours_actifs(t, marge_avant=15 / 60):
                    liste, anomalies, _ = salle.emargement(c, t)
                    seance = {'id': seance_id(c, t), 'date': datetime.fromtimestamp(t).date().isoformat(),
                              'cours': c['id'], 'salle': c['salle'], 'debut': c['debut'], 'fin': c['fin'],
                              'matiere': c['matiere'], 'enseignant': c['enseignant'], 'groupes': c['groupes'],
                              'cles': c['cles'], 'reel': c['reel']}
                    self.registre.noter(seance, liste, anomalies)
            self.registre.cloturer(datetime.fromtimestamp(t))
            self._temoigner(t)
            if abs(t - self.derniere_verif_pannes) >= VERIF_PANNES:
                self.derniere_verif_pannes = t
                self._tickets_du_jumeau(t)
            for s in self.registre.seances_du_jour(datetime.fromtimestamp(t).date()):
                if s['etat'] == 'terminée':
                    self.transports.apprendre(s)
            plan = {config.SALLE_AUTOMATE: self.commande.plan} if self.commande and self.commande.plan else None
            self.prevision.verifier(t, plan)

    def _temoigner(self, t):
        """5 min après la fin de chaque cours, le CO₂ dit combien de personnes ont respiré dans la salle."""
        jour = datetime.fromtimestamp(t).date()
        h = heure_du_jour(t)
        seances = {s['cours']: s for s in self.registre.seances_du_jour(jour)}
        cours_du_jour = self.planning.cours_du_jour(jour)
        for salle in self.salles.values():
            cours = [c for c in cours_du_jour if c['salle'] == salle.id]
            for c in cours:
                sid = seance_id(c, t)
                if sid in self.temoins_faits or h < c['fin'] + 5 / 60 or c['id'] not in seances:
                    continue
                self.temoins_faits.add(sid)
                # Deux cours en même temps dans la salle : le CO₂ voit tout le monde, on compte tous les badges
                ensemble = [x for x in cours if x['debut'] < c['fin'] and x['fin'] > c['debut'] and x['id'] in seances]
                badges = sum(seances[x['id']]['presents'] + seances[x['id']]['retards'] + seances[x['id']]['a_verifier'] + 1
                             for x in ensemble)                  # + 1 : l'enseignant
                avis = self.temoin.evaluer(salle, min(x['debut'] for x in ensemble), max(x['fin'] for x in ensemble), t, badges)
                self.registre.noter_temoin(sid, avis, t)
                if len(ensemble) == 1:
                    self.temoin.apprendre(salle.id, avis)

    # ---------- tickets (matériel manquant, pannes) ----------

    def places_restantes(self, salle):
        """Places de la salle, moins les tables, chaises ou postes manquants (tickets pas résolus)."""
        return max(0, self.batiment_salles[salle]['places'] - self.perdues.get(salle, 0))

    def _places_changees(self):
        self.perdues = self.registre.places_perdues()
        self._previsions = (None, None)            # capacité et propositions refaites avec les places qui restent

    def _tickets_du_jumeau(self, t):
        """Une panne détectée par le jumeau ouvre un ticket, une seule fois tant qu'il n'est pas résolu."""
        ouverts = False
        for (salle, objet), messages in pannes_detectees(self, t, config.SALLE_AUTOMATE).items():
            ticket = {'salle': salle, 'objet': objet, 'quantite': None, 'detail': ' '.join(messages),
                      'service': OBJETS[objet]['service'], 'places_perdues': 0}
            ouverts |= self.registre.ouvrir_ticket_jumeau(ticket, f'{salle}:{objet}', t, PAUSE_TICKET) is not None
        if ouverts:
            self._places_changees()

    def signaler(self, u, corps):
        ticket = nouveau(self.batiment_salles, str(corps.get('salle', '')), str(corps.get('objet', '')),
                         corps.get('quantite'), corps.get('detail'))
        with self.verrou:
            ident, deja = self.registre.ouvrir_ticket(ticket, u['nom'], u['login'],
                                                      'direction' if u['role'] in TOUT_VOIR else u['role'], self.t)
            self._places_changees()
        return {'id': ident, 'deja': deja}

    def changer_ticket(self, u, corps):
        try:
            ident = int(corps.get('id'))
        except (TypeError, ValueError):
            raise ValueError('Ticket inconnu.') from None
        ticket = self.registre.ticket(ident)
        if ticket is None:
            raise KeyError('Ticket inconnu.')
        statut = corps.get('statut') or None
        texte = str(corps.get('texte') or '').strip()[:300]
        if statut is not None and statut not in STATUTS:
            raise ValueError('Statut inconnu.')
        if not statut and not texte:
            raise ValueError('Rien à changer.')
        # Un enseignant commente, ou ferme le ticket qu'il a ouvert ; le service technique et la direction font tout
        if u['role'] == 'enseignant' and statut and not (statut == 'résolu' and ticket['login'] == u['login']):
            raise Refus("Seuls le service technique et la direction changent l'état d'un ticket.")
        with self.verrou:
            self.registre.changer_ticket(ident, statut, texte, u['nom'], self.t)
            self._places_changees()

    def liste_tickets(self):
        """Tickets pas résolus (les plus urgents d'abord) et résolus de la semaine, avec ce qu'en dit le jumeau."""
        with self.verrou:
            t = self.t
            liste = [{**x, 'titre': titre(x['objet'], x['quantite'], x['detail']), 'objet_nom': OBJETS[x['objet']]['nom'],
                      'service_nom': SERVICES[x['service']], **analyser(self, x, t, self.perdues.get(x['salle'], 0))}
                     for x in self.registre.tickets(resolus_depuis=t - TICKETS_RESOLUS)]
            return trier(liste)

    def boucle(self):
        while True:
            try:
                self.piloter()
                self.synchroniser()
            except Exception as e:      # le pilotage ne doit jamais arrêter le serveur
                print('Erreur de pilotage :', e)
            time.sleep(0.5)

    # ---------- état pour le jumeau 3D ----------

    def etat(self):
        with self.verrou:
            d = datetime.fromtimestamp(self.t)
            return {
                't': self.t,
                'date': d.strftime('%d/%m/%Y'),
                'heure': heure_du_jour(self.t),
                'jour': d.weekday(),
                'simulation': self.simulation is not None,
                'pannes': self.simulation.salles[config.SALLE_AUTOMATE].pannes if self.simulation else None,
                'mode': self.mode,
                'automate': self.pont.etat,
                'messages': self.messages,
                'salles': {i: s.etat(self.t) for i, s in self.salles.items()},
            }

    # ---------- jumeau prédictif ----------

    def previsions(self, frais=False):
        """Prévision de chaque salle, plan de ventilation, bilan d'énergie, capacité, propositions de salles."""
        with self.verrou:
            minute = int(self.t // 60)
            if not frais and self._previsions[0] == minute:
                return self._previsions[1]
            resultat = self._calculer_previsions()
            self._previsions = (minute, resultat)
            return resultat

    def _calculer_previsions(self):
        with self.verrou:
            t = self.t
            jour = datetime.fromtimestamp(t).date()
            plan = self.commande.plan if self.commande and self.mode['strategie'] == 'predictive' else None
            salles = []
            for sid in self.salles:
                p = self.prevision.prevoir(sid, t, 120, niveaux=plan if sid == config.SALLE_AUTOMATE else None)
                if p:
                    salles.append(self.prevision.resume(p))
            h0 = heure_du_jour(t)
            segments = []
            for k, n in enumerate(plan or []):
                if segments and segments[-1]['niveau'] == n:
                    segments[-1]['fin'] = h0 + (k + 1) / 60
                else:
                    segments.append({'debut': h0 + k / 60, 'fin': h0 + (k + 1) / 60, 'niveau': n})
            auto = self.salles.get(config.SALLE_AUTOMATE)
            return {
                'date': jour.isoformat(), 'heure': h0,
                'salles': salles,
                'precision': self.prevision.precision(),
                'taux_presence': round(self.prevision.taux(jour), 3),
                'commande': {
                    'salle': config.SALLE_AUTOMATE,
                    'strategie': self.mode['strategie'], 'auto': self.mode['auto'],
                    'niveau': auto.niveau if auto else None,
                    'plan': segments,
                    'bilan': self.bilan.resume() if self.bilan else None,
                },
                'capacite': capacite(self, t),
                'ambiance': {
                    'salle': config.SALLE_AUTOMATE, 'eclairage': self.ambiance[0], 'chauffage': self.ambiance[1],
                    'automate': {k: self.pont.etat.get(k) for k in ('connecte', 'eclairage', 'chauffage', 'radiateur')},
                    'bilan': self.bilan_ambiance.resume(),
                },
                'propositions': propositions(self, t),
                'changements': self.registre.changements_du_jour(jour),
            }

    def historique(self, salle):
        with self.verrou:
            s = self.salles.get(salle)
            return [{'t': t, 'heure': heure_du_jour(t), 'C': c, 'N': n} for t, c, n in s.historique] if s else []


# Adresses ouvertes sans compte : la connexion, et ce qu'envoient les capteurs (protégé par leur clé)
PUBLIQUES = {'/api/connexion', '/api/mesure', '/api/cartes', '/api/info'}
# Adresses réservées au directeur des études et à la scolarité (le jumeau 3D voit tout le bâtiment)
DIRECTION = {'/api/etat', '/api/flux', '/api/historique', '/api/commande', '/api/simulation/panne',
             '/api/previsions', '/api/proposition',
             '/api/cartes/inconnues', '/api/cartes/liste', '/api/cartes/associer', '/api/cartes/retirer'}
# Le service technique ne voit que les tickets (pas les présences des étudiants)
TECHNIQUE = {'/api/moi', '/api/tickets', '/api/tickets/changer', '/api/deconnexion'}


def creer_gestionnaire(campus, comptes, client_ia=None):
    """client_ia : faux client de l'API Claude, pour les tests."""
    suivi = Suivi(campus)
    assistant = Assistant(campus, suivi, charger_enseignants(), config, client_ia)

    class Gestionnaire(SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('X-Content-Type-Options', 'nosniff')
            super().end_headers()

        def log_message(self, *args):
            pass                                # pas une ligne par requête dans la console

        # ---------- réponses ----------

        def _json(self, donnees, code=200, entetes=()):
            corps = json.dumps(donnees, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(corps)))
            for k, v in entetes:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(corps)

        def _corps(self):
            n = int(self.headers.get('Content-Length', 0))
            if n > 1_000_000:
                raise ValueError('Message trop gros.')
            return json.loads(self.rfile.read(n) or b'{}')

        def _jeton(self):
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            return cookie['session'].value if 'session' in cookie else None

        def _utilisateur(self):
            jeton = self._jeton()
            return comptes.utilisateur(jeton) if jeton else None

        def _verifier_acces(self, chemin):
            """Renvoie l'utilisateur, ou répond 401 / 403 et renvoie None."""
            if chemin in PUBLIQUES:
                return {}
            u = self._utilisateur()
            if u is None:
                self._json({'erreur': 'connexion nécessaire'}, 401)
                return None
            if chemin in DIRECTION and u['role'] not in TOUT_VOIR:
                self._json({'erreur': 'réservé au directeur des études et à la scolarité'}, 403)
                return None
            if u['role'] == 'technique' and chemin not in TECHNIQUE:
                self._json({'erreur': 'le service technique voit seulement les tickets'}, 403)
                return None
            return u

        # ---------- GET ----------

        def do_GET(self):
            url = urlparse(self.path)
            chemin = url.path
            if chemin == '/':
                self.send_response(302)
                self.send_header('Location', '/suivi/')
                self.end_headers()
                return
            if chemin == '/donnees/edt.json':
                return self._json(campus.edt)          # avec les vrais noms des enseignants s'ils sont connus
            if not chemin.startswith('/api/'):
                return super().do_GET()
            u = self._verifier_acces(chemin)
            if u is None:
                return
            p = parse_qs(url.query)
            un = lambda cle: p.get(cle, [''])[0]
            aujourd_hui = datetime.fromtimestamp(campus.t).date()
            try:
                if chemin == '/api/info':
                    d = datetime.fromtimestamp(campus.t)
                    return self._json({'simulation': campus.simulation is not None, 'date': d.date().isoformat(),
                                       'heure': heure_du_jour(campus.t)})
                if chemin == '/api/moi':
                    return self._json({k: u[k] for k in ('login', 'role', 'nom', 'enseignant')} |
                                      {'simulation': campus.simulation is not None})
                if chemin == '/api/tableau':
                    return self._json(suivi.tableau(u))
                if chemin == '/api/seances':
                    jour = date.fromisoformat(un('date')) if un('date') else aujourd_hui
                    return self._json(suivi.seances(u, jour))
                if chemin == '/api/seance':
                    return self._json(suivi.seance(u, un('id')))
                if chemin == '/api/classes':
                    return self._json(suivi.classes(u, *periode(p, aujourd_hui)))
                if chemin == '/api/classe':
                    return self._json(suivi.classe(u, un('id'), *periode(p, aujourd_hui)))
                if chemin == '/api/etudiant':
                    return self._json(suivi.etudiant(u, un('id'), *periode(p, aujourd_hui)))
                if chemin == '/api/export':
                    du, au = periode(p, aujourd_hui)
                    corps = suivi.export(u, un('classe'), du, au).encode('utf-8')
                    nom = f'presences_{un("classe")}_{du:%Y%m%d}_{au:%Y%m%d}.csv'
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/csv; charset=utf-8')
                    self.send_header('Content-Disposition', f'attachment; filename="{quote(nom)}"')
                    self.send_header('Content-Length', str(len(corps)))
                    self.end_headers()
                    self.wfile.write(corps)
                    return
                if chemin == '/api/cartes/inconnues':
                    groupes, enseignants = campus.places_cartes()
                    with campus.verrou:
                        inconnues = sorted(({'empreinte': k, **v} for k, v in campus.cartes_inconnues.items()),
                                           key=lambda x: -x['t'])
                    return self._json({'cartes': [{**x, 'heure': heure_du_jour(x['t'])} for x in inconnues[:30]],
                                       'groupes': groupes, 'enseignants': enseignants})
                if chemin == '/api/cartes/liste':
                    groupes, enseignants = campus.places_cartes()
                    gardes = {e['id'] for g in groupes for e in g['etudiants']} | {e['id'] for e in enseignants}
                    with campus.verrou:
                        cartes = [{'empreinte': k, **p} for k, p in campus.annuaire.items() if p['id'] in gardes]
                    return self._json({'cartes': sorted(cartes, key=lambda c: (c['groupe'], c['id']))})
                if chemin == '/api/assistant':
                    role = 'direction' if u['role'] in TOUT_VOIR else 'enseignant'
                    return self._json(assistant.etat() | {'suggestions': SUGGESTIONS[role],
                                                          'conversation': assistant.historique(self._jeton())})
                if chemin == '/api/tickets':
                    tickets = [{k: v for k, v in x.items() if k != 'login'} | {'mien': x['login'] == u['login']}
                               for x in campus.liste_tickets()]
                    return self._json({
                        'tickets': tickets, 'statuts': STATUTS, 'services': SERVICES,
                        'objets': {k: {'nom': o['nom'], 'quantite': bool(o.get('quantite')), 'places': o.get('places', 0)}
                                   for k, o in OBJETS.items() if not o.get('jumeau')},
                        'salles': [{k: s[k] for k in ('id', 'libelle', 'type', 'places', 'etage')}
                                   | {'places_restantes': campus.places_restantes(s['id'])} for s in campus.batiment['salles']],
                        'peut_changer': u['role'] != 'enseignant'})
                if chemin == '/api/previsions':
                    return self._json(campus.previsions())
                if chemin == '/api/etat':
                    return self._json(campus.etat())
                if chemin == '/api/historique':
                    return self._json(campus.historique(un('salle')))
                if chemin == '/api/flux':
                    return self._flux()
                self._json({'erreur': 'adresse inconnue'}, 404)
            except Refus as e:
                self._json({'erreur': str(e)}, 403)
            except (ValueError, KeyError) as e:
                self._json({'erreur': str(e).strip('\'"')}, 400)

        def _flux(self):
            """Server-Sent Events : le jumeau reçoit l'état toutes les secondes, sans recharger."""
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            try:
                while True:
                    self.wfile.write(f'data: {json.dumps(campus.etat(), ensure_ascii=False)}\n\n'.encode())
                    self.wfile.flush()
                    time.sleep(1)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        # ---------- POST ----------

        def do_POST(self):
            chemin = urlparse(self.path).path
            u = self._verifier_acces(chemin)
            if u is None:
                return
            try:
                if chemin in ('/api/mesure', '/api/cartes'):
                    if config.CLE_CAPTEURS and self.headers.get('X-Cle') != config.CLE_CAPTEURS:
                        return self._json({'erreur': 'clé des capteurs incorrecte'}, 403)
                    corps = self._corps()
                    if chemin == '/api/cartes':
                        campus.ajouter_cartes(corps)
                        return self._json({'ok': True})
                    reponses = [campus.recevoir(m) for m in (corps if isinstance(corps, list) else [corps])]
                    return self._json({'ok': True, **next((r for r in reversed(reponses) if r), {})})
                if chemin == '/api/connexion':
                    corps = self._corps()
                    try:
                        jeton = comptes.connecter(str(corps.get('login', '')), str(corps.get('mot_de_passe', '')),
                                                  self.client_address[0])
                    except PermissionError as e:
                        return self._json({'erreur': str(e)}, 429)
                    if not jeton:
                        return self._json({'erreur': 'Identifiant ou mot de passe incorrect.'}, 401)
                    cookie = f'session={jeton}; HttpOnly; SameSite=Strict; Path=/; Max-Age=36000'
                    u = comptes.utilisateur(jeton)
                    return self._json({k: u[k] for k in ('login', 'role', 'nom')}, entetes=[('Set-Cookie', cookie)])
                if chemin == '/api/deconnexion':
                    comptes.deconnecter(self._jeton())
                    return self._json({'ok': True}, entetes=[('Set-Cookie', 'session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')])
                if chemin == '/api/cartes/associer':
                    corps = self._corps()
                    campus.associer_carte(str(corps.get('empreinte', '')), str(corps.get('etudiant', '')), str(corps.get('nom', '')))
                    return self._json({'ok': True})
                if chemin == '/api/cartes/retirer':
                    campus.retirer_carte(str(self._corps().get('empreinte', '')))
                    return self._json({'ok': True})
                if chemin == '/api/assistant':
                    corps = self._corps()
                    if corps.get('nouvelle'):
                        assistant.oublier(self._jeton())
                        return self._json({'ok': True})
                    try:
                        return self._json(assistant.repondre(u, self._jeton(), str(corps.get('question', ''))))
                    except Indisponible as e:
                        return self._json({'erreur': str(e)}, 503)
                    except Occupe as e:
                        return self._json({'erreur': str(e)}, 429)
                    except ErreurIA as e:
                        return self._json({'erreur': str(e)}, 502)
                if chemin == '/api/tickets':
                    return self._json(campus.signaler(u, self._corps()))
                if chemin == '/api/tickets/changer':
                    campus.changer_ticket(u, self._corps())
                    return self._json({'ok': True})
                if chemin == '/api/seance/statut':
                    return self._json(suivi.corriger(u, self._corps()))
                if chemin == '/api/commande':
                    corps = self._corps()
                    with campus.verrou:
                        if 'auto' in corps:
                            campus.mode['auto'] = bool(corps['auto'])
                        if corps.get('niveau') in ('arret', 'petite', 'grande'):
                            campus.mode['niveau'] = corps['niveau']
                        if corps.get('strategie') in ('predictive', 'reactive'):
                            campus.mode['strategie'] = corps['strategie']
                            campus.consigne = None
                    return self._json({'ok': True, 'mode': campus.mode})
                if chemin == '/api/proposition':
                    corps = self._corps()
                    with campus.verrou:
                        jour = datetime.fromtimestamp(campus.t).date()
                        if corps.get('action') == 'accepter':
                            echange = corps.get('echange') or {}
                            if corps.get('salle') not in campus.salles or (echange and echange.get('salle') not in campus.salles):
                                raise ValueError('Salle inconnue.')
                            campus.planning.changer_salle(jour, corps['cours'], corps['salle'], u['nom'], campus.t)
                            if echange:                       # les deux cours échangent leurs salles
                                campus.planning.changer_salle(jour, echange['cours'], echange['salle'], u['nom'], campus.t)
                        elif corps.get('action') == 'ignorer':
                            campus.registre.ignorer_proposition(jour, corps['cours'], u['nom'], campus.t)
                        else:
                            raise ValueError('Action inconnue.')
                        campus.previsions(frais=True)
                    return self._json({'ok': True})
                if chemin == '/api/simulation/panne':
                    if not campus.simulation:
                        return self._json({'erreur': 'pas en mode simulation'}, 400)
                    corps = self._corps()
                    salle = campus.simulation.salles[corps.get('salle', config.SALLE_AUTOMATE)]
                    salle.pannes[corps['panne']] = not salle.pannes[corps['panne']]
                    return self._json({'ok': True, 'pannes': salle.pannes})
                self._json({'erreur': 'adresse inconnue'}, 404)
            except Refus as e:
                self._json({'erreur': str(e)}, 403)
            except (ValueError, KeyError, TypeError) as e:
                self._json({'erreur': str(e).strip('\'"')}, 400)

    return functools.partial(Gestionnaire, directory=str(WEB))


# Tickets de la démonstration (lundi 7 h) : la page Tickets n'est pas vide
TICKETS_DEMO = [
    {'salle': 'SAR 101', 'objet': 'table', 'quantite': 2, 'detail': 'Deux tables cassées enlevées vendredi.'},
    {'salle': 'SAR 102', 'objet': 'feutres', 'detail': 'Plus aucun feutre qui marche.'},
    {'salle': 'SAR 221', 'objet': 'videoprojecteur', 'detail': "L'image clignote."},
    {'salle': 'SAR 084', 'objet': 'prise', 'detail': 'Prise du bureau enseignant hors service.'},
]


def lancer_simulation(campus, vitesse, jours_historique=5, tickets_demo=False):
    """Simule le bâtiment. Avec un historique, la semaine précédente est jouée d'un coup au
    démarrage : le registre a déjà des séances, et la salle SAR 200 est déjà recalée."""
    module = charger_simulateur('batiment')
    debut_direct = module.DEBUT_SEMAINE
    debut = debut_direct - timedelta(days=7) if jours_historique else debut_direct
    sim = module.SimulateurBatiment(campus.recevoir, lambda salle: campus.salles[salle].niveau or 'petite', debut=debut,
                                    cours_du_jour=campus.planning.cours_du_jour)
    campus.simulation = sim
    campus.t = sim.t
    campus.ajouter_cartes(sim.annuaire())
    if jours_historique:
        print('Simulation de la semaine précédente (quelques secondes)...')
        campus.avance_rapide = True
        n = 0
        while sim.t < debut_direct.timestamp():
            sim.pas(10)
            n += 1
            if n % 6 == 0:                            # chaque minute simulée
                campus.piloter()
                campus.synchroniser(force=True)
        campus.avance_rapide = False
        campus.synchroniser(force=True)
    if tickets_demo:
        campus.t = max(campus.t, sim.t)               # lundi 7 h
        for corps in TICKETS_DEMO:
            campus.signaler({'nom': 'Enseignant (démo)', 'login': 'enseignant', 'role': 'enseignant'}, corps)

    def boucle():
        pas = 10                                     # s simulées par pas
        while True:
            debut_pas = time.time()
            sim.pas(pas)
            time.sleep(max(0.0, pas / vitesse - (time.time() - debut_pas)))

    threading.Thread(target=boucle, daemon=True, name='simulation').start()


def main():
    p = argparse.ArgumentParser(description='Serveur CampusTwin')
    p.add_argument('--simulation', action='store_true', help='bâtiment et automate simulés')
    p.add_argument('--vitesse', type=float, default=60, help='simulation : secondes simulées par seconde réelle')
    p.add_argument('--historique', type=int, default=5, help='simulation : jouer la semaine précédente au démarrage (0 = non)')
    p.add_argument('--port', type=int, default=config.PORT_WEB)
    a = p.parse_args()

    if a.simulation:
        charger_simulateur('automate').demarrer(5020)
        pont = PontAutomate('127.0.0.1', 5020, config.AUTOMATE_PERIODE)
        stockage = None                              # on n'enregistre pas la simulation
        registre = Registre()                        # en mémoire
        edt = charger_edt()
        comptes = comptes_de_demo(enseignant_de_demo(edt))
    else:
        pont = PontAutomate(config.AUTOMATE_IP, config.AUTOMATE_PORT, config.AUTOMATE_PERIODE)
        stockage = Stockage(str(ICI / config.BASE))
        registre = Registre(str(ICI / config.BASE_REGISTRE))
        comptes = Comptes()
        if not comptes.comptes:
            print('Aucun compte : créez-en un avec  python serveur/comptes.py ajouter <login> --role directeur --nom "..."')

    campus = Campus(stockage, pont, registre)
    pont.demarrer()
    if not a.simulation and config.PRIM_CLE:
        PontPrim(campus, config.PRIM_CLE, config.LIGNES_TRANSPORT).demarrer()
    if a.simulation:
        lancer_simulation(campus, a.vitesse, a.historique, tickets_demo=True)
    threading.Thread(target=campus.boucle, daemon=True, name='pilotage').start()

    serveur = ThreadingHTTPServer(('0.0.0.0', a.port), creer_gestionnaire(campus, comptes))
    serveur.daemon_threads = True
    print(f'CampusTwin : http://localhost:{a.port}  ({"simulation" if a.simulation else "capteurs réels"})')
    if a.simulation:
        print('Comptes de démonstration : directeur / demo, enseignant / demo, technique / demo')
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if stockage:
            stockage.fermer()


if __name__ == '__main__':
    main()
