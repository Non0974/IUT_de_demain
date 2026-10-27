"""CELCAT -> CampusTwin : met à jour l'emploi du temps (edt.json) et les salles (salles.json) à partir d'un
export CELCAT Calendar (la réponse JSON de /Home/GetCalendarData, voir celcat_export.js).

Deux usages :
  - la semaine de notre classe : un compte étudiant ne voit que son propre emploi du temps ;
  - toutes les salles : il faut un compte qui voit les salles (directeur des études, scolarité),
    qui exporte chaque salle, puis on donne tous les fichiers au script.

    python outils/celcat.py celcat_2026-11-16.json --lundi 2026-11-16 --essai
    python outils/celcat.py salle1.json salle2.json --lundi 2026-11-16

Ce que fait le script :
  - garde les cours du lundi au vendredi, et fusionne les créneaux qui se suivent (même cours, même salle) ;
  - un cours donné dans deux salles est coupé en deux : un demi-groupe (TP) par salle ;
  - ajoute au bâtiment les salles qu'il ne connaît pas, avec leurs places lues dans CELCAT ;
  - remplace les vrais cours de edt.json ; un cours simulé qui gêne change de salle ou disparaît ;
  - les enseignants deviennent « Enseignant A, B… » dans edt.json ; leurs vrais noms vont dans
    serveur/enseignants.json, qui reste sur le PC (pas sur GitHub).
"""

import argparse
import html
import json
import re
import string
from datetime import date, datetime, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DONNEES = RACINE / 'jumeau3d' / 'donnees'
ENSEIGNANTS = RACINE / 'serveur' / 'enseignants.json'

SALLE = re.compile(r'^(SAR (?:Amphi \d+|\d{3}(?:-\d{3})?))\s*(?:-\s*)?(.*?)\s*(\d+)\s*p$', re.IGNORECASE)
MODULE = re.compile(r'^(R\d|SAE|SAÉ|S\d|P\d)', re.IGNORECASE)
GROUPE = re.compile(r'(BUT|GEII|LP |LICENCE)', re.IGNORECASE)
FUSION = 10 / 60                 # h : deux créneaux séparés de moins de 10 min sont un même cours
M2_PAR_PLACE = {'TD': 2.0, 'TP': 3.0, 'INFO': 2.4, 'REUNION': 2.5, 'AMPHI': 1.0}
EFFECTIF_ESTIME = {'TP': 12, 'TD': 24, 'CM': 48}
MARGE = 0.25                     # h : une salle doit être libre 15 min avant et après un cours


def lignes_de(evenement):
    """Les lignes de la description CELCAT (séparées par <br />), sans le HTML."""
    texte = html.unescape(evenement.get('description') or '')
    return [re.sub(r'\s+', ' ', l).strip() for l in texte.split('<br />') if l.strip()]


def type_de_salle(libelle):
    l = libelle.upper()
    if 'AMPHI' in l:
        return 'AMPHI'
    if 'RÉUNION' in l or 'REUNION' in l:
        return 'REUNION'
    if 'INFORMATIQUE' in l:
        return 'INFO'
    return 'TP' if 'TP' in l.split() else 'TD'


def lire_salle(ligne):
    """« SAR 102 SALLE INFORMATIQUE 25p » -> {id, libelle, type, places, etage}."""
    m = SALLE.match(ligne)
    if not m:
        return None
    sid, libelle, places = ' '.join(m.group(1).split()), m.group(2).strip(' -'), int(m.group(3))
    libelle = re.sub(r'^\(cours\)\s*', '', libelle)
    chiffres = re.findall(r'\d+', sid)
    etage = 0 if 'Amphi' in sid or not chiffres else int(chiffres[0]) // 100
    return {'id': sid, 'libelle': libelle.capitalize(), 'type': type_de_salle(libelle), 'places': places, 'etage': etage}


def lire_evenement(e):
    """Un événement CELCAT -> (début, fin, matière, groupes, salles, enseignants), ou None (indisponibilité…)."""
    if e.get('allDay') or 'Indisponibilit' in (e.get('eventCategory') or ''):
        return None
    lignes = lignes_de(e)
    salles = [s for s in map(lire_salle, lignes) if s]
    groupes = [l for l in lignes if GROUPE.search(l) and not SALLE.match(l)]
    modules = [l for l in lignes if MODULE.match(l) and l not in groupes]
    connues = set(groupes) | set(modules) | {l for l in lignes if SALLE.match(l)} | {lignes[0] if lignes else ''}
    connues.add(e.get('eventCategory') or '')
    enseignants = [l for l in lignes if l not in connues and l.upper() == l and re.search(r'[A-Z]{2}', l)]
    matiere = re.sub(r'^\S+\s+', '', modules[0]) if modules else (lignes[0] if lignes else '?')
    return {'debut': datetime.fromisoformat(e['start']), 'fin': datetime.fromisoformat(e['end']), 'matiere': matiere,
            'groupes': groupes, 'salles': salles, 'enseignants': enseignants}


def fusionner(evenements):
    """Créneaux qui se suivent pour un même cours -> un seul cours."""
    cours = []
    for e in sorted(evenements, key=lambda e: e['debut']):
        cle = (e['debut'].date(), e['matiere'], tuple(e['groupes']), tuple(s['id'] for s in e['salles']), tuple(e['enseignants']))
        precedent = next((c for c in reversed(cours) if c['cle'] == cle), None)
        if precedent and (e['debut'] - precedent['fin']).total_seconds() / 3600 <= FUSION:
            precedent['fin'] = max(precedent['fin'], e['fin'])
        else:
            cours.append({**e, 'cle': cle})
    return cours


def heure(d):
    return round(d.hour + d.minute / 60, 3)


def cle_de_groupe(nom, groupes):
    """Clé courte d'un groupe CELCAT (« … TP1 » -> TP1), réutilisée si le groupe est déjà connu."""
    for cle, g in groupes.items():
        if g['nom'] == nom:
            return cle
    fin = nom.split()[-1]
    if fin not in groupes:
        return fin
    sigle = ''.join(m[0] for m in nom.split()[:-1] if m[0].isalnum())
    return f'{sigle}-{fin}'


def groupes_du_cours(noms, groupes):
    """Noms CELCAT -> (noms affichés, clés, effectif). Un TD n = les TP 2n-1 et 2n s'ils existent."""
    affiches, cles = [], []
    for nom in noms:
        fin = nom.split()[-1]
        m = re.fullmatch(r'TD(\d+)', fin)
        if m:
            n = int(m.group(1))
            prefixe = nom[:-len(fin)]
            tp = [f'{prefixe}TP{k}' for k in (2 * n - 1, 2 * n)]
            if all(cle_de_groupe(t, groupes) in groupes for t in tp):
                for t in tp:
                    affiches.append(t)
                    cles.append(cle_de_groupe(t, groupes))
                continue
        cle = cle_de_groupe(nom, groupes)
        if cle not in groupes:
            type_ = next((t for t in EFFECTIF_ESTIME if fin.startswith(t)), 'TD')
            groupes[cle] = {'nom': nom, 'effectif': EFFECTIF_ESTIME[type_], 'estime': True}
        affiches.append(nom)
        cles.append(cle)
    effectif = sum(groupes[c]['effectif'] for c in cles)
    return affiches, cles, effectif


class Pseudonymes:
    """Vrais noms des enseignants -> « Enseignant A, B… » (les vrais noms restent dans serveur/enseignants.json)."""

    def __init__(self, chemin):
        self.chemin = chemin
        self.table = json.loads(chemin.read_text(encoding='utf-8')) if chemin.exists() else {}
        self.par_nom = {v.upper(): k for k, v in self.table.items()}

    def __call__(self, nom):
        if nom.upper() not in self.par_nom:
            n = len(self.table)
            lettres = string.ascii_uppercase[n % 26] if n < 26 else string.ascii_uppercase[n // 26 - 1] + string.ascii_uppercase[n % 26]
            pseudo = f'Enseignant {lettres}'
            mots = nom.split()
            self.table[pseudo] = ' '.join(mots[:-1] + [mots[-1].capitalize()]) if len(mots) > 1 else nom
            self.par_nom[nom.upper()] = pseudo
        return self.par_nom[nom.upper()]

    def garder(self):
        self.chemin.write_text(json.dumps(self.table, ensure_ascii=False, indent=1), encoding='utf-8')


def chevauche(a, b, marge=MARGE):
    return a['jour'] == b['jour'] and a['salle'] == b['salle'] and a['debut'] - marge < b['fin'] and a['fin'] + marge > b['debut']


def importer(fichiers, lundi, edt, batiment, pseudonymes):
    """Met à jour edt et batiment (dictionnaires) avec les vrais cours de la semaine. Renvoie un résumé."""
    evenements = [lire_evenement(e) for f in fichiers for e in json.loads(Path(f).read_text(encoding='utf-8'))]
    semaine = [e for e in evenements if e and lundi <= e['debut'].date() < lundi + timedelta(days=5) and e['salles']]
    # Une même salle exportée deux fois (export par salle) : on ne garde chaque cours qu'une fois
    uniques = {(e['debut'], e['matiere'], tuple(e['groupes']), tuple(s['id'] for s in e['salles'])): e for e in semaine}
    cours_reels = fusionner(uniques.values())

    salles_connues = {s['id']: s for s in batiment['salles']}
    nouvelles = []
    for c in cours_reels:
        for s in c['salles']:
            if s['id'] not in salles_connues:
                salle = {**s, 'surface': round(s['places'] * M2_PAR_PLACE[s['type']], 1), 'ventilation': 'meca', 'equipee': False}
                batiment['salles'].append(salle)
                salles_connues[s['id']] = salle
                nouvelles.append(s['id'])

    nouveaux = []
    for c in cours_reels:
        noms, cles, effectif = groupes_du_cours(c['groupes'], edt['groupes'])
        base = {'jour': c['debut'].weekday(), 'debut': heure(c['debut']), 'fin': heure(c['fin']), 'matiere': c['matiere'],
                'enseignant': ', '.join(pseudonymes(e) for e in c['enseignants']) or '—', 'reel': True}
        if len(c['salles']) > 1 and len(cles) == len(c['salles']):
            # Un cours dans deux salles : un demi-groupe par salle
            for nom, cle, s in zip(noms, cles, c['salles']):
                nouveaux.append({**base, 'groupes': [nom], 'cles': [cle], 'effectif': edt['groupes'][cle]['effectif'], 'salle': s['id']})
        else:
            nouveaux.append({**base, 'groupes': noms, 'cles': cles, 'effectif': effectif, 'salle': c['salles'][0]['id']})
    for i, c in enumerate(sorted(nouveaux, key=lambda c: (c['jour'], c['debut'], c['salle']))):
        c['id'] = f'r{i}'

    # Les cours simulés qui gênent un vrai cours changent de salle (même type, assez grande, libre), sinon disparaissent
    types = {s['id']: s['type'] for s in batiment['salles']}
    places = {s['id']: s['places'] for s in batiment['salles']}
    simules = [c for c in edt['cours'] if not c['reel']]
    cours = list(nouveaux)
    deplaces = supprimes = 0
    for c in simules:
        if not any(chevauche(c, r) for r in nouveaux):
            cours.append(c)
            continue
        for sid in sorted(places, key=places.get):
            essai = {**c, 'salle': sid}
            if types[sid] == types.get(c['salle']) and places[sid] >= c['effectif'] and not any(
                    chevauche(essai, x) for x in cours + [s for s in simules if s is not c]):
                cours.append(essai)
                deplaces += 1
                break
        else:
            supprimes += 1
    edt['cours'] = sorted(cours, key=lambda c: (c['jour'], c['debut'], c['salle'] or ''))
    edt['jours'] = [f'{j} {lundi + timedelta(days=k):%d/%m}' for k, j in enumerate(['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi'])]
    return {'reels': len(nouveaux), 'salles_ajoutees': nouvelles, 'deplaces': deplaces, 'supprimes': supprimes,
            'effectifs_estimes': sorted(k for k, g in edt['groupes'].items() if g.get('estime'))}


def main():
    p = argparse.ArgumentParser(description='CELCAT -> emploi du temps de CampusTwin')
    p.add_argument('fichiers', nargs='+', help='exports JSON de CELCAT (celcat_export.js)')
    p.add_argument('--lundi', required=True, help='lundi de la semaine à importer, AAAA-MM-JJ')
    p.add_argument('--essai', action='store_true', help='affiche ce qui changerait, sans rien écrire')
    a = p.parse_args()
    edt_chemin, salles_chemin = DONNEES / 'edt.json', DONNEES / 'salles.json'
    edt = json.loads(edt_chemin.read_text(encoding='utf-8'))
    batiment = json.loads(salles_chemin.read_text(encoding='utf-8'))
    pseudonymes = Pseudonymes(ENSEIGNANTS)
    resume = importer(a.fichiers, date.fromisoformat(a.lundi), edt, batiment, pseudonymes)
    print(f'{resume["reels"]} vrais cours ; salles ajoutées : {", ".join(resume["salles_ajoutees"]) or "aucune"} ; '
          f'cours simulés déplacés : {resume["deplaces"]}, supprimés : {resume["supprimes"]}')
    if resume['effectifs_estimes']:
        print(f'Effectifs estimés, à corriger dans edt.json (« groupes ») : {", ".join(resume["effectifs_estimes"])}')
    if a.essai:
        print('Essai : rien n\'a été écrit.')
        return
    edt_chemin.write_text(json.dumps(edt, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    salles_chemin.write_text(json.dumps(batiment, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    pseudonymes.garder()
    print('edt.json, salles.json et serveur/enseignants.json mis à jour. Relancer le serveur.')


if __name__ == '__main__':
    main()
