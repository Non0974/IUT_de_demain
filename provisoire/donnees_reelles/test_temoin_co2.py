"""Le CO₂ comme témoin de l'émargement, testé sur de vraies salles (ROBOD, Singapour).

Idée : le CO₂ d'une salle dit combien de personnes y ont respiré. Si 20 cartes ont badgé mais que le
CO₂ correspond à 13 personnes, il y a des cartes en trop (prêtées).

Bilan de CO₂ de la salle, écrit pour être appris sans connaître son volume :
    personnes = a × (montée du CO₂) + b × (CO₂ − extérieur) + c × (CO₂ − extérieur) × ventilation
« ventilation » : débit d'air soufflé (bureaux, bibliothèque) ou vitesse du ventilateur (salles de cours),
0 si on ne la connaît pas. À l'IUT, c'est la vitesse commandée par l'automate.

Deux façons d'apprendre a, b, c (le vrai comptage joue le rôle des badges honnêtes) :
  - « 1re semaine » : sur la première semaine seulement ;
  - « au fil de l'eau » : avant chaque cours, sur tous les cours d'avant (à l'IUT : les cours déjà vérifiés).
Fraude simulée : 2, 4, 6 ou 8 badges de trop. Alerte si badges − estimation > seuil, le seuil venant des
écarts vus sur les cours d'apprentissage (1,5 × le 90e centile, au moins 3 personnes).

    python test_temoin_co2.py <dossier ROBOD (fichiers combined_RoomN.csv)>
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

JOURS_APPRENTISSAGE = 7
DUREE_MIN = 45            # min d'occupation pour compter comme un cours
ARRIVEE = 15              # min ignorées au début (les gens arrivent)
FRAUDES = (2, 4, 6, 8)
SALLES = {1: 'Salle de cours 1', 2: 'Salle de cours 2', 3: 'Bureau 1', 4: 'Bureau 2', 5: 'Bibliothèque'}
VENTILATION = ('supply_air_flow [CMH]', 'fcu_fan_speed [Hz]')


def lire(dossier, salle):
    d = pd.read_csv(Path(dossier) / f'combined_Room{salle}.csv')
    d['t'] = pd.to_datetime(d['timestamp'].str[:16])
    d = d.rename(columns={'indoor_co2 [ppm]': 'c', 'outdoor_co2 [ppm]': 'c_ext', 'occupant_count [number]': 'n'})
    d['c'] = d['c'].rolling(3, center=True, min_periods=1).mean()                # bruit du capteur
    d['montee'] = d['c'].diff().shift(-1).rolling(3, center=True, min_periods=1).mean() * 12   # ppm/h (pas de 5 min)
    d['ecart'] = d['c'] - d['c_ext'].fillna(d['c_ext'].median())
    colonne = next((c for c in VENTILATION if c in d.columns), None)
    v = d[colonne].fillna(0) if colonne else 0
    d['ventile'] = d['ecart'] * (v / (np.max(v) or 1))
    return d.dropna(subset=['c', 'montee', 'ecart'])


def cours(d):
    """Blocs où la salle est occupée au moins 45 min ; on garde la partie après les arrivées."""
    occupe = d['n'] > 0
    bloc = (occupe != occupe.shift()).cumsum()
    return [g.iloc[ARRIVEE // 5:] for _, g in d[occupe].groupby(bloc[occupe]) if len(g) * 5 >= DUREE_MIN]


def evaluer(appris, testes, colonnes, fil_de_l_eau):
    """Écarts, fausses alertes et repérage des fraudes sur les cours testés."""
    def ajuster(blocs):
        x = np.concatenate([g[colonnes].to_numpy() for g in blocs])
        y = np.concatenate([g['n'].to_numpy() for g in blocs])
        return np.linalg.lstsq(x, y, rcond=None)[0]

    def estimer(g, coef):
        return float(np.mean(g[colonnes].to_numpy() @ coef)), float(g['n'].mean())

    resultats = []
    deja = list(appris)
    coef = ajuster(deja)
    for g in testes:
        if fil_de_l_eau:
            coef = ajuster(deja)
        residus = [abs(v - e) for e, v in (estimer(h, coef) for h in deja)]
        seuil = max(3.0, 1.5 * float(np.percentile(residus, 90)))
        e, v = estimer(g, coef)
        resultats.append((e, v, seuil))
        deja.append(g)
    ecarts = np.array([abs(e - v) for e, v, _ in resultats])
    fausses = np.mean([round(v) - e > s for e, v, s in resultats])
    reperes = [np.mean([round(v) + f - e > s for e, v, s in resultats]) for f in FRAUDES]
    return ecarts, fausses, reperes


def main(dossier):
    variantes = [('1re semaine, sans ventilation', ['montee', 'ecart'], False),
                 ('au fil de l\'eau, avec ventilation', ['montee', 'ecart', 'ventile'], True)]
    for titre, colonnes, fil in variantes:
        print(f'\n== {titre}')
        print(f"{'Salle':18} {'cours':>6} {'écart moyen':>12} {'à ±3':>6} {'fausses alertes':>16} "
              + ' '.join(f'{f:>2} cartes' for f in FRAUDES))
        for salle, nom in SALLES.items():
            d = lire(dossier, salle)
            debut = d['t'].dt.normalize().min()
            blocs = cours(d)
            appris = [g for g in blocs if (g['t'].iloc[0] - debut).days < JOURS_APPRENTISSAGE]
            testes = [g for g in blocs if (g['t'].iloc[0] - debut).days >= JOURS_APPRENTISSAGE]
            if len(appris) < 3 or len(testes) < 3:
                print(f'{nom:18} pas assez de cours')
                continue
            ecarts, fausses, reperes = evaluer(appris, testes, colonnes, fil)
            print(f'{nom:18} {len(testes):6d} {ecarts.mean():8.1f} pers {np.mean(ecarts <= 3):6.0%} {fausses:16.0%} '
                  + ' '.join(f'{r:8.0%}' for r in reperes))
    print('\nÉcart moyen : entre le nombre de personnes estimé par le CO₂ et le vrai nombre, moyenné sur le cours.')
    print('Fausses alertes : cours sans fraude signalés quand même. Colonnes de droite : part des cours où les cartes en trop sont repérées.')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
