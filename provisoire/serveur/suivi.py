"""Ce que lit l'interface de suivi des classes : tableau de bord, séances, classes, étudiants.

Règles d'accès (données personnelles, RGPD) :
  directeur, scolarite : tout l'IUT
  enseignant           : ses séances, et les classes et étudiants qu'il a en cours
"""

from datetime import date, datetime, timedelta

from registre import debut_semaine, taux
from salle import heure_du_jour, seance_id

TOUT_VOIR = ('directeur', 'scolarite')


class Refus(Exception):
    """L'utilisateur n'a pas le droit de voir ou de faire ça."""


def periode(params, aujourd_hui):
    """Période demandée (du, au), par défaut la semaine en cours."""
    try:
        du = date.fromisoformat(params.get('du', [''])[0])
        au = date.fromisoformat(params.get('au', [''])[0])
    except ValueError:
        du = debut_semaine(aujourd_hui)
        au = du + timedelta(days=6)
    if au < du:
        du, au = au, du
    return du, au


class Suivi:
    def __init__(self, campus):
        self.campus = campus

    # ---------- droits ----------

    def cles_de(self, utilisateur):
        """Groupes visibles : tous, ou ceux qu'a l'enseignant dans l'emploi du temps."""
        if utilisateur['role'] in TOUT_VOIR:
            return None
        return {cle for c in self.campus.edt['cours'] if c['enseignant'] == utilisateur['enseignant'] for cle in c['cles']}

    def voit_seance(self, utilisateur, seance):
        return utilisateur['role'] in TOUT_VOIR or seance['enseignant'] == utilisateur['enseignant']

    def nom(self, ident):
        return self.campus.noms.get(ident)

    def _avec_noms(self, lignes, champ='etudiant'):
        for x in lignes:
            x['nom'] = self.nom(x[champ])
        return lignes

    # ---------- tableau de bord ----------

    def tableau(self, utilisateur):
        campus = self.campus
        with campus.verrou:
            t = campus.t
            aujourd_hui = datetime.fromtimestamp(t).date()
            h = heure_du_jour(t)
            enseignant = None if utilisateur['role'] in TOUT_VOIR else utilisateur['enseignant']
            seances = campus.registre.seances_du_jour(aujourd_hui, enseignant)
            ids_en_cours = set()
            en_cours = []
            for salle in campus.salles.values():
                for c in salle.cours_actifs(t):
                    sid = seance_id(c, t)
                    s = next((x for x in seances if x['id'] == sid), None)
                    if s is None or sid in ids_en_cours:
                        continue
                    ids_en_cours.add(sid)
                    etat = salle.etat(t)
                    en_cours.append({**s, 'personnes': etat['personnes'], 'source': etat['source'], 'co2': etat['co2'],
                                     'alertes': etat['alertes']})
            en_cours.sort(key=lambda s: (s['salle'], s['debut']))
            # Séances à venir aujourd'hui (pas encore dans le registre) : emploi du temps
            a_venir = [c for c in campus.edt['cours'] if c['jour'] == aujourd_hui.weekday() and c['debut'] > h
                       and c['salle'] and (enseignant is None or c['enseignant'] == enseignant)]
            a_venir.sort(key=lambda c: c['debut'])
            terminees = [s for s in seances if s['etat'] == 'terminée']

            def somme(liste, cle):
                return sum(s[cle] or 0 for s in liste)

            decides_jour = sum(somme(seances, k) for k in ('presents', 'retards', 'absents', 'justifies', 'a_verifier'))
            alertes = []
            for s in en_cours:
                for a in s['alertes']:
                    if a['niveau'] == 'detecte':
                        alertes.append({'niveau': 'detecte', 'salle': s['salle'], 'seance': s['id'], 'texte': a['texte']})
            du = debut_semaine(aujourd_hui)
            for e in campus.registre.alertes_assiduite(du, du + timedelta(days=6), self.cles_de(utilisateur)):
                alertes.append({'niveau': 'suspect', 'etudiant': e['etudiant'], 'nom': self.nom(e['etudiant']),
                                'texte': f'{e["absents"]} absences non justifiées et {e["retards"]} retards cette semaine.'})
            return {
                'date': aujourd_hui.isoformat(),
                'heure': h,
                'simulation': campus.simulation is not None,
                'chiffres': {
                    'seances_en_cours': len(en_cours),
                    'presents_maintenant': somme(en_cours, 'presents') + somme(en_cours, 'retards'),
                    'absents_maintenant': somme(en_cours, 'absents'),
                    'attendus_maintenant': somme(en_cours, 'attendus'),
                    'seances_du_jour': len(seances) + len(a_venir),
                    'seances_terminees': len(terminees),
                    'taux_jour': (somme(seances, 'presents') + somme(seances, 'retards')) / decides_jour if decides_jour else None,
                    'alertes': len(alertes),
                },
                'en_cours': en_cours,
                'a_venir': [{k: c[k] for k in ('id', 'salle', 'debut', 'fin', 'matiere', 'enseignant', 'groupes', 'reel', 'effectif')}
                            for c in a_venir[:8]],
                'alertes': alertes,
            }

    # ---------- séances ----------

    def seances(self, utilisateur, jour):
        """Séances d'un jour : celles du registre, plus celles de l'emploi du temps pas encore commencées."""
        enseignant = None if utilisateur['role'] in TOUT_VOIR else utilisateur['enseignant']
        liste = self.campus.registre.seances_du_jour(jour, enseignant)
        deja = {s['cours'] for s in liste}
        with self.campus.verrou:
            maintenant = datetime.fromtimestamp(self.campus.t)
        h = heure_du_jour(maintenant.timestamp())
        if jour >= maintenant.date():
            for c in self.campus.edt['cours']:
                if c['jour'] != jour.weekday() or not c['salle'] or c['id'] in deja:
                    continue
                if enseignant and c['enseignant'] != enseignant:
                    continue
                if jour > maintenant.date() or c['debut'] - 15 / 60 > h:
                    liste.append({'id': f'{jour.isoformat()}_{c["id"]}', 'date': jour.isoformat(), 'cours': c['id'],
                                  'salle': c['salle'], 'debut': c['debut'], 'fin': c['fin'], 'matiere': c['matiere'],
                                  'enseignant': c['enseignant'], 'groupes': c['groupes'], 'cles': c['cles'],
                                  'reel': int(c['reel']), 'etat': 'à venir', 'inscrits': c['effectif'],
                                  'presents': 0, 'retards': 0, 'absents': 0, 'justifies': 0, 'a_verifier': 0,
                                  'attendus': c['effectif'], 'corrections': 0, 'anomalies': 0})
        liste.sort(key=lambda s: (s['debut'], s['salle']))
        return {'date': jour.isoformat(), 'seances': liste}

    def seance(self, utilisateur, ident):
        s = self.campus.registre.seance(ident)
        if s is None:
            raise KeyError('Séance inconnue.')
        if not self.voit_seance(utilisateur, s):
            raise Refus('Cette séance n\'est pas la vôtre.')
        self._avec_noms(s['presences'])
        s['peut_corriger'] = True
        # Séance en cours : on ajoute ce que voit la salle maintenant
        salle = self.campus.salles.get(s['salle'])
        if salle and s['etat'] == 'en cours':
            with self.campus.verrou:
                etat = salle.etat(self.campus.t)
            s['salle_maintenant'] = {k: etat[k] for k in ('personnes', 'source', 'co2', 'alertes')}
        return s

    def corriger(self, utilisateur, corps):
        s = self.campus.registre.seance(corps.get('seance', ''))
        if s is None:
            raise KeyError('Séance inconnue.')
        if not self.voit_seance(utilisateur, s):
            raise Refus('Vous ne pouvez corriger que vos séances.')
        self.campus.registre.corriger(s['id'], corps['etudiant'], corps['statut'], corps.get('motif', ''),
                                      utilisateur['nom'], self.campus.t)
        return self.seance(utilisateur, s['id'])

    # ---------- classes et étudiants ----------

    def classes(self, utilisateur, du, au):
        classes = self.campus.registre.classes(du, au, self.cles_de(utilisateur))
        for c in classes:
            c['reel'] = c['cle'] in self.campus.edt['groupes']      # les autres groupes sont simulés
        classes.sort(key=lambda c: (not c['reel'], c['nom']))
        return {'du': du.isoformat(), 'au': au.isoformat(), 'classes': classes}

    def classe(self, utilisateur, cle, du, au):
        cles = self.cles_de(utilisateur)
        if cles is not None and cle not in cles:
            raise Refus('Vous n\'avez pas cette classe en cours.')
        c = self.campus.registre.classe(cle, du, au)
        self._avec_noms(c['etudiants'], 'id')
        return {'du': du.isoformat(), 'au': au.isoformat(), **c}

    def etudiant(self, utilisateur, ident, du, au):
        e = self.campus.registre.etudiant(ident, du, au)
        cles = self.cles_de(utilisateur)
        if cles is not None and e['groupe'] not in cles:
            raise Refus('Cet étudiant n\'est pas dans vos classes.')
        if cles is not None:            # un enseignant ne voit que ses propres séances
            e['seances'] = [x for x in e['seances'] if x['enseignant'] == utilisateur['enseignant']]
            e['corrections'] = [c for c in e['corrections'] if any(x['seance'] == c['seance'] for x in e['seances'])]
            for cle, statut in (('presents', 'présent'), ('retards', 'retard'), ('absents', 'absent'),
                                ('justifies', 'justifié'), ('a_verifier', 'à vérifier'), ('attendus', 'attendu')):
                e[cle] = sum(1 for x in e['seances'] if x['statut'] == statut)
            e['taux'] = taux(e)
        e['nom'] = self.nom(ident)
        return {'du': du.isoformat(), 'au': au.isoformat(), **e}

    def export(self, utilisateur, cle, du, au):
        cles = self.cles_de(utilisateur)
        if cles is not None and cle not in cles:
            raise Refus('Vous n\'avez pas cette classe en cours.')
        return self.campus.registre.export_csv(cle, du, au)
