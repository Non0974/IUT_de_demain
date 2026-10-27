"""Est-ce que les ondes Wi-Fi comptent les personnes ? Analyse du fichier serveur/ondes.csv, où le serveur
garde chaque mesure des ondes avec le nombre de personnes comptées à la porte.

  - présence : le seuil est appris sur la salle vide (première moitié des mesures), puis on regarde sur
    la deuxième moitié si « mouvement au-dessus du seuil » correspond à « quelqu'un dans la salle » ;
  - comptage : régression linéaire personnes = f(mouvement, mouvement², turbulence, RSSI), apprise sur la
    première moitié et testée sur la deuxième. On compare à « répondre toujours la moyenne ».

    python outils/ondes_wifi.py serveur/ondes.csv
    python outils/ondes_wifi.py serveur/ondes.csv --salle "SAR 200"
"""

import argparse
import csv
import sys
from statistics import mean, pstdev

ECARTS = 4


def lire(chemin, salle=None):
    with open(chemin, encoding='utf-8') as f:
        lignes = [l for l in csv.DictReader(f, delimiter=';')
                  if l['personnes_porte'] != '' and int(l['paquets']) >= 100 and (salle is None or l['salle'] == salle)]
    return [{'mouvement': float(l['mouvement']), 'turbulence': float(l['turbulence']), 'rssi': float(l['rssi']),
             'personnes': int(l['personnes_porte'])} for l in lignes]


def variables(x):
    return [1.0, x['mouvement'], x['mouvement'] ** 2, x['turbulence'], x['rssi']]


def moindres_carres(xs, ys):
    """Résout (XᵀX) b = Xᵀy par élimination de Gauss (pas besoin de numpy)."""
    n = len(xs[0])
    a = [[sum(x[i] * x[j] for x in xs) + (1e-6 if i == j else 0) for j in range(n)] + [sum(x[i] * y for x, y in zip(xs, ys))]
         for i in range(n)]
    for i in range(n):
        p = max(range(i, n), key=lambda k: abs(a[k][i]))
        a[i], a[p] = a[p], a[i]
        for k in range(n):
            if k != i:
                f = a[k][i] / a[i][i]
                a[k] = [u - f * v for u, v in zip(a[k], a[i])]
    return [a[i][n] / a[i][i] for i in range(n)]


def analyser(mesures):
    """Résultats sur la deuxième moitié des mesures (la première sert à apprendre)."""
    moitie = len(mesures) // 2
    appris, test = mesures[:moitie], mesures[moitie:]
    vides = [x['mouvement'] for x in appris if x['personnes'] == 0]
    if len(vides) < 12 or not test:
        raise ValueError('Pas assez de mesures (il faut des moments où la salle est vide).')
    seuil = mean(vides) + ECARTS * max(pstdev(vides), 0.05 * mean(vides), 1e-3)
    bons = sum((x['mouvement'] > seuil) == (x['personnes'] > 0) for x in test)
    occupees = [x for x in test if x['personnes'] > 0]
    vues = sum(x['mouvement'] > seuil for x in occupees)
    fausses = sum(x['mouvement'] > seuil for x in test if x['personnes'] == 0)
    b = moindres_carres([variables(x) for x in appris], [x['personnes'] for x in appris])
    prevus = [max(0.0, sum(c * v for c, v in zip(b, variables(x)))) for x in test]
    erreurs = [abs(p - x['personnes']) for p, x in zip(prevus, test)]
    moyenne = mean(x['personnes'] for x in appris)
    erreurs_moyenne = [abs(moyenne - x['personnes']) for x in test]
    sur_occupees = [e for e, x in zip(erreurs, test) if x['personnes'] > 0]
    return {
        'mesures': len(mesures), 'seuil': seuil,
        'presence_juste': bons / len(test),
        'occupee_vue': vues / len(occupees) if occupees else None,
        'fausses_presences': fausses / max(1, len(test) - len(occupees)),
        'erreur': mean(erreurs), 'erreur_occupee': mean(sur_occupees) if sur_occupees else None,
        'a_2_pres': sum(e <= 2 for e in erreurs) / len(erreurs),
        'erreur_sans_ondes': mean(erreurs_moyenne),
    }


def main():
    p = argparse.ArgumentParser(description='Les ondes Wi-Fi comptent-elles les personnes ?')
    p.add_argument('fichier', help='serveur/ondes.csv')
    p.add_argument('--salle')
    a = p.parse_args()
    r = analyser(lire(a.fichier, a.salle))
    print(f"{r['mesures']} mesures avec le comptage de la porte (moitié pour apprendre, moitié pour tester)")
    print(f"Présence : juste dans {r['presence_juste']:.0%} des cas ; salle occupée vue {r['occupee_vue']:.0%} du temps ; "
          f"fausses présences {r['fausses_presences']:.0%}")
    print(f"Comptage : {r['erreur']:.1f} personnes d'erreur en moyenne ({r['a_2_pres']:.0%} à 2 près), "
          f"{r['erreur_occupee']:.1f} quand la salle est occupée")
    print(f"Sans les ondes (toujours la moyenne) : {r['erreur_sans_ondes']:.1f} personnes d'erreur")


if __name__ == '__main__':
    sys.exit(main())
