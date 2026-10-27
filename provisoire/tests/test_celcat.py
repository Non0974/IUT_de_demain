"""Test de l'import CELCAT : un export au format CELCAT (la semaine de la classe, avec de faux noms
d'enseignants) donne les mêmes vrais cours que edt.json, sans aucun nom dans l'emploi du temps.
Rien n'est écrit dans le projet : tout se passe sur des copies.

    python tests/test_celcat.py
"""

import copy
import json
import sys
import tempfile
from datetime import date
from importlib import util
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
spec = util.spec_from_file_location('celcat', RACINE / 'outils' / 'celcat.py')
celcat = util.module_from_spec(spec)
spec.loader.exec_module(celcat)

EXEMPLE = RACINE / 'tests' / 'donnees' / 'celcat_exemple.json'
FAUX_NOMS = ['MARTIN', 'BERNARD', 'PETIT-JEAN', 'DUBOIS', 'ROUX', 'LEROY', 'MOREL']


def main():
    verifs = []
    donnees = RACINE / 'jumeau3d' / 'donnees'
    edt0 = json.loads((donnees / 'edt.json').read_text(encoding='utf-8'))
    bat0 = json.loads((donnees / 'salles.json').read_text(encoding='utf-8'))
    edt, bat = copy.deepcopy(edt0), copy.deepcopy(bat0)
    bat['salles'] = [s for s in bat['salles'] if s['id'] != 'SAR 105']        # une salle à redécouvrir
    pseudo = celcat.Pseudonymes(Path(tempfile.mkdtemp()) / 'enseignants.json')

    r = celcat.importer([EXEMPLE], date(2026, 11, 16), edt, bat, pseudo)
    reels = [c for c in edt['cours'] if c['reel']]
    print(r)
    verifs.append(('17 vrais cours (journée en entreprise et autre semaine ignorées)', r['reels'] == 17 and len(reels) == 17))
    ve = next(c for c in reels if c['jour'] == 0 and c['salle'] == 'SAR 102')
    verifs.append(('créneaux qui se suivent fusionnés (lundi 08h10-12h00)', (ve['debut'], ve['fin']) == (8.167, 12.0)))
    verifs.append(('TD1 = TP1 + TP2 (18 étudiants)', ve['cles'] == ['TP1', 'TP2'] and ve['effectif'] == 18))
    mercredi = sorted((c['salle'], c['cles']) for c in reels if c['jour'] == 2 and c['debut'] == 9.5)
    verifs.append(('cours en deux salles : un demi-groupe par salle', mercredi == [('SAR 103', ['TP1']), ('SAR 105', ['TP2'])]))
    s105 = next((s for s in bat['salles'] if s['id'] == 'SAR 105'), None)
    verifs.append(('salle inconnue ajoutée avec ses places', s105 and s105['places'] == 15 and s105['type'] == 'INFO' and s105['etage'] == 1))
    texte = json.dumps(edt, ensure_ascii=False)
    verifs.append(('aucun nom d\'enseignant dans l\'emploi du temps', not any(n in texte for n in FAUX_NOMS)))
    verifs.append(('7 enseignants pseudonymisés, vrais noms à part', len(pseudo.table) == 7 and 'PETIT-JEAN Luc' in pseudo.table.values()))
    # Mêmes cours que l'emploi du temps du projet (importé à la main depuis CELCAT)
    attendu = sorted((c['jour'], c['debut'], c['fin'], c['salle'], tuple(c['cles'])) for c in edt0['cours'] if c['reel'])
    obtenu = sorted((c['jour'], c['debut'], c['fin'], c['salle'], tuple(c['cles'])) for c in reels)
    verifs.append(('mêmes cours que edt.json', attendu == obtenu))
    conflits = [(a['id'], b['id']) for i, a in enumerate(edt['cours']) for b in edt['cours'][i + 1:]
                if (a['reel'] or b['reel']) and celcat.chevauche(a, b, marge=0)]
    verifs.append(('pas deux cours dans la même salle en même temps', not conflits))

    for texte, ok in verifs:
        print(('OK    ' if ok else 'ÉCHEC ') + texte)
    sys.exit(0 if all(ok for _, ok in verifs) else 1)


if __name__ == '__main__':
    main()
