"""Registre des présences : chaque séance, l'émargement de chaque étudiant, les corrections.

Le serveur y recopie l'émargement calculé à partir des badges (et des passages à la porte).
Un enseignant ou le directeur des études peut corriger un statut (oubli de badge, absence
justifiée...) : la correction est gardée avec son auteur, son motif et l'heure, et le calcul
automatique ne l'écrase plus. Base SQLite, fournie avec Python.

Statuts : attendu (le cours n'a pas encore commencé), présent, retard, absent,
à vérifier (carte peut-être prêtée), justifié (absence justifiée).
"""

import csv
import io
import json
import sqlite3
import threading
from datetime import date, datetime, timedelta

STATUTS_MANUELS = ('présent', 'retard', 'absent', 'justifié')
CLOTURE = 15 / 60            # h après la fin du cours : la séance est close, les "attendu" deviennent absents
FIN_MATIN = 12.5             # h : un cours qui finit avant appartient à la demi-journée du matin


def debut_semaine(jour):
    return jour - timedelta(days=jour.weekday())


class Registre:
    def __init__(self, chemin=':memory:', noms_groupes=None):
        self.base = sqlite3.connect(chemin, check_same_thread=False)
        self.base.row_factory = sqlite3.Row
        self.verrou = threading.RLock()
        self.noms_groupes = noms_groupes or {}      # clé de groupe -> nom affiché
        self.deja_ecrit = {}                        # (séance, étudiant) -> (statut, badge)
        with self.verrou:
            self.base.executescript('''
                CREATE TABLE IF NOT EXISTS seances (
                    id TEXT PRIMARY KEY, date TEXT, cours TEXT, salle TEXT, debut REAL, fin REAL,
                    matiere TEXT, enseignant TEXT, groupes TEXT, cles TEXT, reel INTEGER,
                    etat TEXT DEFAULT 'en cours');
                CREATE TABLE IF NOT EXISTS presences (
                    seance TEXT, etudiant TEXT, groupe TEXT, statut TEXT, badge REAL,
                    corrige INTEGER DEFAULT 0, PRIMARY KEY (seance, etudiant));
                CREATE TABLE IF NOT EXISTS corrections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, seance TEXT, etudiant TEXT,
                    avant TEXT, apres TEXT, motif TEXT, auteur TEXT, t REAL);
                CREATE TABLE IF NOT EXISTS anomalies (
                    seance TEXT, type TEXT, nombre INTEGER, detail TEXT, PRIMARY KEY (seance, type));
                CREATE TABLE IF NOT EXISTS changements (
                    date TEXT, cours TEXT, salle_avant TEXT, salle_apres TEXT, auteur TEXT, t REAL,
                    PRIMARY KEY (date, cours));
                CREATE TABLE IF NOT EXISTS propositions_ignorees (
                    date TEXT, cours TEXT, auteur TEXT, t REAL, PRIMARY KEY (date, cours));
                CREATE TABLE IF NOT EXISTS temoins (
                    seance TEXT PRIMARY KEY, verdict TEXT, personnes INTEGER, mini INTEGER, maxi INTEGER,
                    badges INTEGER, texte TEXT, t REAL);
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, salle TEXT, objet TEXT, quantite INTEGER, detail TEXT,
                    service TEXT, statut TEXT DEFAULT 'ouvert', auteur TEXT, login TEXT, source TEXT, cle TEXT,
                    places_perdues INTEGER DEFAULT 0, cree REAL, maj REAL);
                CREATE TABLE IF NOT EXISTS tickets_suivi (
                    ticket INTEGER, t REAL, auteur TEXT, statut TEXT, texte TEXT);
                CREATE INDEX IF NOT EXISTS seances_date ON seances (date);
                CREATE INDEX IF NOT EXISTS presences_etudiant ON presences (etudiant);
            ''')
            self.base.commit()

    # ---------- écriture ----------

    def noter(self, seance, liste, anomalies):
        """seance : dict (id, date, cours, salle, debut, fin, matiere, enseignant, groupes, cles, reel)
        liste : [{id, statut, badge}] ; anomalies : {'sans_badge': [...], 'pretes': [...], 'badges_seuls': [...]}"""
        with self.verrou:
            b = self.base
            b.execute('INSERT OR IGNORE INTO seances (id, date, cours, salle, debut, fin, matiere, enseignant, groupes, cles, reel) '
                      'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                      (seance['id'], seance['date'], seance['cours'], seance['salle'], seance['debut'], seance['fin'],
                       seance['matiere'], seance['enseignant'], json.dumps(seance['groupes'], ensure_ascii=False),
                       json.dumps(seance['cles']), int(seance['reel'])))
            for x in liste:
                cle = (seance['id'], x['id'])
                valeur = (x['statut'], x['badge'])
                if self.deja_ecrit.get(cle) == valeur:
                    continue
                b.execute('INSERT INTO presences (seance, etudiant, groupe, statut, badge) VALUES (?, ?, ?, ?, ?) '
                          'ON CONFLICT (seance, etudiant) DO UPDATE SET statut = excluded.statut, badge = excluded.badge '
                          'WHERE corrige = 0',
                          (seance['id'], x['id'], x['id'].rsplit('-', 1)[0], x['statut'], x['badge']))
                self.deja_ecrit[cle] = valeur
            types = {
                'carte prêtée': (len(anomalies['pretes']), '; '.join(' et '.join(ids) for ids, _ in anomalies['pretes'])),
                'entrée sans badge': (len(anomalies['sans_badge']), ''),
                'badge sans passage': (len(anomalies['badges_seuls']), ''),
            }
            for type_, (n, detail) in types.items():
                if n:
                    b.execute('INSERT INTO anomalies VALUES (?, ?, ?, ?) ON CONFLICT (seance, type) '
                              'DO UPDATE SET nombre = excluded.nombre, detail = excluded.detail',
                              (seance['id'], type_, n, detail))
            b.commit()

    def cloturer(self, maintenant):
        """Clôt les séances finies depuis plus de 15 min : ceux qui n'ont pas badgé sont absents."""
        with self.verrou:
            ouvertes = self.base.execute("SELECT id, date, fin FROM seances WHERE etat = 'en cours'").fetchall()
            for s in ouvertes:
                fin = datetime.fromisoformat(s['date']) + timedelta(hours=s['fin'] + CLOTURE)
                if maintenant >= fin:
                    self.base.execute("UPDATE presences SET statut = 'absent' WHERE seance = ? AND statut = 'attendu' AND corrige = 0", (s['id'],))
                    self.base.execute("UPDATE seances SET etat = 'terminée' WHERE id = ?", (s['id'],))
                    for cle in [k for k in self.deja_ecrit if k[0] == s['id']]:
                        del self.deja_ecrit[cle]
            self.base.commit()

    def corriger(self, seance, etudiant, statut, motif, auteur, t):
        if statut not in STATUTS_MANUELS:
            raise ValueError(f'Statut impossible : {statut}')
        if statut == 'justifié' and not (motif or '').strip():
            raise ValueError('Une absence justifiée demande un motif.')
        with self.verrou:
            ligne = self.base.execute('SELECT statut FROM presences WHERE seance = ? AND etudiant = ?', (seance, etudiant)).fetchone()
            if ligne is None:
                raise KeyError('Étudiant absent de cette séance.')
            self.base.execute('UPDATE presences SET statut = ?, corrige = 1 WHERE seance = ? AND etudiant = ?', (statut, seance, etudiant))
            self.base.execute('INSERT INTO corrections (seance, etudiant, avant, apres, motif, auteur, t) VALUES (?, ?, ?, ?, ?, ?, ?)',
                              (seance, etudiant, ligne['statut'], statut, (motif or '').strip(), auteur, t))
            self.base.commit()
            self.deja_ecrit.pop((seance, etudiant), None)

    # ---------- changements de salle (propositions du jumeau acceptées) ----------

    def changer_salle(self, jour, cours, avant, apres, auteur, t):
        with self.verrou:
            self.base.execute('INSERT OR REPLACE INTO changements VALUES (?, ?, ?, ?, ?, ?)',
                              (jour.isoformat(), cours, avant, apres, auteur, t))
            self.base.commit()

    def changements(self):
        with self.verrou:
            return {(r['date'], r['cours']): r['salle_apres'] for r in self.base.execute('SELECT * FROM changements')}

    def changements_du_jour(self, jour):
        with self.verrou:
            return [dict(r) for r in self.base.execute('SELECT * FROM changements WHERE date = ? ORDER BY t', (jour.isoformat(),))]

    def ignorer_proposition(self, jour, cours, auteur, t):
        with self.verrou:
            self.base.execute('INSERT OR REPLACE INTO propositions_ignorees VALUES (?, ?, ?, ?)', (jour.isoformat(), cours, auteur, t))
            self.base.commit()

    def propositions_ignorees(self, jour):
        with self.verrou:
            return {r['cours'] for r in self.base.execute('SELECT cours FROM propositions_ignorees WHERE date = ?', (jour.isoformat(),))}

    def presences_apprises(self, avant, jours=14):
        """Présents et étudiants attendus des séances closes des derniers jours, par groupe et par
        demi-journée de la semaine : {'groupes': {cle: [p, n]}, 'creneaux': {(jour, demi): [p, n]}, 'total': [p, n]}."""
        with self.verrou:
            lignes = self.base.execute(
                '''SELECT p.groupe, s.date, s.fin <= ? AS matin,
                          SUM(p.statut IN ('présent', 'retard')) AS presents,
                          SUM(p.statut IN ('présent', 'retard', 'absent', 'justifié', 'à vérifier')) AS decides
                   FROM presences p JOIN seances s ON s.id = p.seance
                   WHERE s.etat = 'terminée' AND s.date BETWEEN ? AND ?
                   GROUP BY p.groupe, s.date, matin''',
                (FIN_MATIN, (avant - timedelta(days=jours)).isoformat(), avant.isoformat())).fetchall()
        appris = {'groupes': {}, 'creneaux': {}, 'total': [0, 0]}
        for r in lignes:
            creneau = (date.fromisoformat(r['date']).weekday(), 'matin' if r['matin'] else 'après-midi')
            for compte in (appris['groupes'].setdefault(r['groupe'], [0, 0]),
                           appris['creneaux'].setdefault(creneau, [0, 0]), appris['total']):
                compte[0] += r['presents']
                compte[1] += r['decides']
        return appris

    # ---------- témoin CO₂ ----------

    def noter_temoin(self, seance, avis, t):
        with self.verrou:
            self.base.execute('INSERT OR REPLACE INTO temoins VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                              (seance, avis['verdict'], avis.get('personnes'), avis.get('min'), avis.get('max'),
                               avis['badges'], avis['texte'], t))
            self.base.commit()

    def temoin(self, seance):
        with self.verrou:
            r = self.base.execute('SELECT * FROM temoins WHERE seance = ?', (seance,)).fetchone()
        return {'verdict': r['verdict'], 'personnes': r['personnes'], 'min': r['mini'], 'max': r['maxi'],
                'badges': r['badges'], 'texte': r['texte']} if r else None

    def temoins_du_jour(self, jour):
        with self.verrou:
            return [dict(r) for r in self.base.execute(
                '''SELECT t.*, s.salle, s.matiere, s.debut, s.enseignant, s.groupes FROM temoins t JOIN seances s ON s.id = t.seance
                   WHERE s.date = ? ORDER BY s.debut''', (jour.isoformat(),))]

    # ---------- tickets (matériel manquant, pannes) ----------

    def ouvrir_ticket(self, ticket, auteur, login, source, t, cle=None):
        """Nouveau ticket. Si la même chose est déjà signalée dans la salle (ticket pas résolu), on ne
        l'ouvre pas deux fois : on note le nouveau signalement. Renvoie (id, déjà signalé)."""
        with self.verrou:
            deja = self.base.execute("SELECT id, quantite FROM tickets WHERE statut != 'résolu' AND salle = ? AND objet = ?",
                                     (ticket['salle'], ticket['objet'])).fetchone()
            if deja:
                if ticket.get('quantite') and ticket['quantite'] > (deja['quantite'] or 0):
                    self.base.execute('UPDATE tickets SET quantite = ?, places_perdues = ?, maj = ? WHERE id = ?',
                                      (ticket['quantite'], ticket['places_perdues'], t, deja['id']))
                self.base.execute('INSERT INTO tickets_suivi VALUES (?, ?, ?, ?, ?)',
                                  (deja['id'], t, auteur, None, 'Signalé aussi' + (f' : {ticket["detail"]}' if ticket['detail'] else '.')))
                self.base.commit()
                return deja['id'], True
            n = self.base.execute(
                'INSERT INTO tickets (salle, objet, quantite, detail, service, auteur, login, source, cle, places_perdues, cree, maj) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (ticket['salle'], ticket['objet'], ticket['quantite'], ticket['detail'], ticket['service'], auteur, login,
                 source, cle, ticket['places_perdues'], t, t)).lastrowid
            self.base.execute('INSERT INTO tickets_suivi VALUES (?, ?, ?, ?, ?)', (n, t, auteur, 'ouvert', ticket['detail'] or None))
            self.base.commit()
            return n, False

    def ouvrir_ticket_jumeau(self, ticket, cle, t, pause):
        """Ticket ouvert par le jumeau (panne détectée). Une seule fois : pas si le même ticket est encore
        ouvert, ni s'il a été résolu il y a moins de pause s (le diagnostic met du temps à se mettre à jour)."""
        with self.verrou:
            dernier = self.base.execute('SELECT statut, maj FROM tickets WHERE cle = ? ORDER BY id DESC LIMIT 1', (cle,)).fetchone()
            if dernier and (dernier['statut'] != 'résolu' or t - dernier['maj'] < pause):
                return None
        return self.ouvrir_ticket(ticket, 'CampusTwin (automatique)', None, 'jumeau', t, cle)[0]

    def ticket(self, ident):
        with self.verrou:
            r = self.base.execute('SELECT * FROM tickets WHERE id = ?', (ident,)).fetchone()
            if r is None:
                return None
            d = dict(r)
            d['suivi'] = [dict(x) for x in self.base.execute('SELECT t, auteur, statut, texte FROM tickets_suivi WHERE ticket = ? ORDER BY t, rowid', (ident,))]
            return d

    def tickets(self, resolus_depuis=None):
        """Tickets pas encore résolus, et ceux résolus depuis resolus_depuis (heure), avec leur suivi."""
        with self.verrou:
            lignes = self.base.execute("SELECT id FROM tickets WHERE statut != 'résolu' OR maj >= ? ORDER BY id",
                                       (resolus_depuis if resolus_depuis is not None else float('inf'),)).fetchall()
        return [self.ticket(r['id']) for r in lignes]

    def changer_ticket(self, ident, statut, texte, auteur, t):
        with self.verrou:
            if statut:
                self.base.execute('UPDATE tickets SET statut = ?, maj = ? WHERE id = ?', (statut, t, ident))
            self.base.execute('INSERT INTO tickets_suivi VALUES (?, ?, ?, ?, ?)', (ident, t, auteur, statut, texte or None))
            self.base.commit()

    def places_perdues(self):
        """Places perdues dans chaque salle (tables, chaises, postes manquants des tickets pas résolus)."""
        with self.verrou:
            return {r['salle']: r['n'] for r in self.base.execute(
                "SELECT salle, SUM(places_perdues) AS n FROM tickets WHERE statut != 'résolu' GROUP BY salle HAVING n > 0")}

    # ---------- lecture ----------

    def _seance_dict(self, s):
        d = dict(s)
        d['groupes'] = json.loads(d['groupes'])
        d['cles'] = json.loads(d['cles'])
        return d

    COMPTES = '''SUM(p.statut = 'présent') AS presents, SUM(p.statut = 'retard') AS retards,
                 SUM(p.statut = 'absent') AS absents, SUM(p.statut = 'justifié') AS justifies,
                 SUM(p.statut = 'à vérifier') AS a_verifier, SUM(p.statut = 'attendu') AS attendus,
                 COUNT(p.etudiant) AS inscrits'''

    def seances_du_jour(self, jour, enseignant=None):
        with self.verrou:
            requete = f'SELECT s.*, {self.COMPTES}, (SELECT COUNT(*) FROM corrections c WHERE c.seance = s.id) AS corrections, ' \
                      f'(SELECT COALESCE(SUM(nombre), 0) FROM anomalies a WHERE a.seance = s.id) AS anomalies ' \
                      f'FROM seances s LEFT JOIN presences p ON p.seance = s.id WHERE s.date = ?'
            args = [jour.isoformat()]
            if enseignant:
                requete += ' AND s.enseignant = ?'
                args.append(enseignant)
            lignes = self.base.execute(requete + ' GROUP BY s.id ORDER BY s.debut, s.salle', args).fetchall()
            return [self._seance_dict(s) for s in lignes]

    def seance(self, ident):
        with self.verrou:
            s = self.base.execute(f'SELECT s.*, {self.COMPTES} FROM seances s LEFT JOIN presences p ON p.seance = s.id '
                                  'WHERE s.id = ? GROUP BY s.id', (ident,)).fetchone()
            if s is None:
                return None
            d = self._seance_dict(s)
            d['presences'] = [dict(p) for p in self.base.execute(
                'SELECT etudiant, groupe, statut, badge, corrige FROM presences WHERE seance = ? ORDER BY etudiant', (ident,))]
            d['anomalies'] = [dict(a) for a in self.base.execute('SELECT type, nombre, detail FROM anomalies WHERE seance = ?', (ident,))]
            d['corrections'] = [dict(c) for c in self.base.execute(
                'SELECT etudiant, avant, apres, motif, auteur, t FROM corrections WHERE seance = ? ORDER BY t DESC', (ident,))]
            return d

    def classes(self, du, au, cles=None):
        """Bilan de chaque groupe sur la période (séances closes ou en cours)."""
        with self.verrou:
            lignes = self.base.execute(
                f'''SELECT p.groupe AS cle, COUNT(DISTINCT p.etudiant) AS etudiants, COUNT(DISTINCT p.seance) AS seances,
                    {self.COMPTES} FROM presences p JOIN seances s ON s.id = p.seance
                    WHERE s.date BETWEEN ? AND ? GROUP BY p.groupe ORDER BY p.groupe''',
                (du.isoformat(), au.isoformat())).fetchall()
            resultat = []
            for g in lignes:
                if cles is not None and g['cle'] not in cles:
                    continue
                d = dict(g)
                d['nom'] = self.noms_groupes.get(g['cle'], g['cle'])
                d['taux'] = taux(d)
                resultat.append(d)
            return resultat

    def classe(self, cle, du, au):
        """Tableau d'une classe : une ligne par étudiant, une colonne par séance."""
        with self.verrou:
            seances = [self._seance_dict(s) for s in self.base.execute(
                '''SELECT DISTINCT s.* FROM seances s JOIN presences p ON p.seance = s.id
                   WHERE p.groupe = ? AND s.date BETWEEN ? AND ? ORDER BY s.date, s.debut''',
                (cle, du.isoformat(), au.isoformat()))]
            cases = {}
            for p in self.base.execute(
                    '''SELECT p.etudiant, p.seance, p.statut, p.corrige FROM presences p JOIN seances s ON s.id = p.seance
                       WHERE p.groupe = ? AND s.date BETWEEN ? AND ?''', (cle, du.isoformat(), au.isoformat())):
                cases.setdefault(p['etudiant'], {})[p['seance']] = {'statut': p['statut'], 'corrige': p['corrige']}
            etudiants = []
            for e in sorted(cases):
                compte = {k: 0 for k in ('presents', 'retards', 'absents', 'justifies', 'a_verifier', 'attendus')}
                for c in cases[e].values():
                    compte[{'présent': 'presents', 'retard': 'retards', 'absent': 'absents', 'justifié': 'justifies',
                            'à vérifier': 'a_verifier', 'attendu': 'attendus'}[c['statut']]] += 1
                etudiants.append({'id': e, **compte, 'taux': taux(compte), 'cases': cases[e]})
            return {'cle': cle, 'nom': self.noms_groupes.get(cle, cle), 'seances': seances, 'etudiants': etudiants}

    def etudiant(self, ident, du, au):
        with self.verrou:
            lignes = [dict(x) for x in self.base.execute(
                '''SELECT s.id AS seance, s.date, s.debut, s.fin, s.matiere, s.salle, s.enseignant, p.statut, p.badge, p.corrige
                   FROM presences p JOIN seances s ON s.id = p.seance
                   WHERE p.etudiant = ? AND s.date BETWEEN ? AND ? ORDER BY s.date, s.debut''',
                (ident, du.isoformat(), au.isoformat()))]
            corrections = [dict(c) for c in self.base.execute(
                'SELECT seance, avant, apres, motif, auteur, t FROM corrections WHERE etudiant = ? ORDER BY t DESC', (ident,))]
            compte = {k: sum(1 for x in lignes if x['statut'] == s) for k, s in
                      (('presents', 'présent'), ('retards', 'retard'), ('absents', 'absent'),
                       ('justifies', 'justifié'), ('a_verifier', 'à vérifier'), ('attendus', 'attendu'))}
            groupe = ident.rsplit('-', 1)[0]
            return {'id': ident, 'groupe': groupe, 'nom_groupe': self.noms_groupes.get(groupe, groupe),
                    'seances': lignes, 'corrections': corrections, **compte, 'taux': taux(compte)}

    def alertes_assiduite(self, du, au, cles=None, seuil=3):
        """Étudiants avec beaucoup d'absences non justifiées ou de retards sur la période."""
        with self.verrou:
            lignes = self.base.execute(
                '''SELECT p.etudiant, p.groupe, SUM(p.statut = 'absent') AS absents, SUM(p.statut = 'retard') AS retards
                   FROM presences p JOIN seances s ON s.id = p.seance WHERE s.date BETWEEN ? AND ?
                   GROUP BY p.etudiant HAVING absents >= ? OR retards >= ? ORDER BY absents DESC, retards DESC''',
                (du.isoformat(), au.isoformat(), seuil, seuil)).fetchall()
            return [dict(x) for x in lignes if cles is None or x['groupe'] in cles]

    def export_csv(self, cle, du, au):
        """Feuille de présence d'une classe (Excel, séparateur ;) avec la présence par demi-journée pour le CFA."""
        c = self.classe(cle, du, au)
        demi = {}
        for s in c['seances']:
            demi.setdefault((s['date'], 'matin' if s['fin'] <= FIN_MATIN else 'après-midi'), []).append(s['id'])
        sortie = io.StringIO()
        w = csv.writer(sortie, delimiter=';')
        w.writerow([f'Classe : {c["nom"]}', f'du {du:%d/%m/%Y} au {au:%d/%m/%Y}'])
        w.writerow(['Étudiant']
                   + [f'{date.fromisoformat(s["date"]):%d/%m} {heure_texte(s["debut"])} {s["matiere"]}' for s in c['seances']]
                   + [f'{date.fromisoformat(j):%d/%m} {m}' for j, m in demi]
                   + ['Présences', 'Retards', 'Absences', 'Justifiées', 'Taux de présence'])
        for e in c['etudiants']:
            statuts = [e['cases'].get(s['id'], {}).get('statut', '') for s in c['seances']]
            demis = []
            for ids in demi.values():
                st = [e['cases'].get(i, {}).get('statut') for i in ids if i in e['cases']]
                if st and all(x in ('présent', 'retard') for x in st):
                    demis.append('présent')
                elif st and all(x in ('absent', 'justifié') for x in st):
                    demis.append('justifié' if all(x == 'justifié' for x in st) else 'absent')
                else:
                    demis.append('partiel' if st else '')
            w.writerow([e['id']] + statuts + demis + [e['presents'] + e['retards'], e['retards'], e['absents'],
                                                      e['justifies'], f'{e["taux"]:.0%}' if e['taux'] is not None else ''])
        return '﻿' + sortie.getvalue()


def taux(compte):
    """Taux de présence : présents et retards sur les séances déjà décidées."""
    decides = compte['presents'] + compte['retards'] + compte['absents'] + compte['justifies'] + compte['a_verifier']
    return (compte['presents'] + compte['retards']) / decides if decides else None


def heure_texte(h):
    minutes = round(h * 60)
    return f'{minutes // 60:02d}h{minutes % 60:02d}'
