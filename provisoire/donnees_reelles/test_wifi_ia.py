# IA du Wi-Fi : est-ce qu'un vrai modèle d'apprentissage fait mieux que la droite
# "personnes = a x appareils + b", et combien faut-il de jours pour recaler une nouvelle salle ?
# Données réelles ROBOD (5 salles, une mesure toutes les 5 min, vrai nombre de personnes).
#
# Utilisation : python test_wifi_ia.py <dossier des CSV ROBOD>

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

NOMS = {1: "Salle de cours 1", 2: "Salle de cours 2", 3: "Bureau 1", 4: "Bureau 2", 5: "Bibliothèque"}


def lire(dossier, salle):
    d = pd.read_csv(Path(dossier) / f"combined_Room{salle}.csv")
    d["t"] = pd.to_datetime(d["timestamp"].str[:16])
    d["jour"] = d["timestamp"].str[:10]
    d = d.rename(columns={"wifi_connected_devices [number]": "wifi", "occupant_count [number]": "n",
                          "indoor_co2 [ppm]": "co2"})
    d["salle"] = salle
    return d


def variables(d):
    """Ce que le modèle voit : le Wi-Fi maintenant et juste avant, l'heure et le jour."""
    v = pd.DataFrame(index=d.index)
    g = d.groupby("jour")["wifi"]
    v["wifi"] = d["wifi"]
    for k in (1, 2, 3, 6):                       # 5, 10, 15 et 30 min avant
        v[f"wifi_{k}"] = g.shift(k).fillna(d["wifi"])
    v["moy_15"] = g.transform(lambda s: s.rolling(3, min_periods=1).mean())
    v["max_30"] = g.transform(lambda s: s.rolling(6, min_periods=1).max())
    v["heure"] = d["t"].dt.hour + d["t"].dt.minute / 60
    v["semaine"] = d["t"].dt.weekday
    return v


def score(pred, reel):
    pred = np.clip(np.round(pred), 0, None)
    occ = reel > 0
    err = np.abs(pred - reel)
    return err[occ].mean(), 100 * (err[occ] <= 2).mean()


def main(dossier):
    salles = {s: lire(dossier, s) for s in NOMS}

    print("1) Même salle : appris sur la 1re moitié des jours, testé sur la 2e moitié")
    print(f"{'Salle':<18}| droite              | IA (gradient boosting)")
    for s, d in salles.items():
        jours = sorted(d.jour.unique())
        app = d.jour.isin(jours[:len(jours) // 2])
        a, b = np.polyfit(d.wifi[app], d.n[app], 1)
        e1, p1 = score(a * d.wifi[~app] + b, d.n[~app])
        X = variables(d)
        ia = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=0).fit(X[app], d.n[app])
        e2, p2 = score(ia.predict(X[~app]), d.n[~app])
        print(f"{NOMS[s]:<18}| {e1:.1f} pers., {p1:.0f} % ±2 | {e2:.1f} pers., {p2:.0f} % ±2")

    print("\n2) Nouvelle salle : IA apprise sur les 4 autres salles, puis recalée (facteur d'échelle) avec quelques jours de la nouvelle")
    print(f"{'Salle':<18}| sans recalage       | 1 jour de recalage  | 3 jours de recalage")
    for s, d in salles.items():
        autres = pd.concat([x for k, x in salles.items() if k != s], ignore_index=True)
        ia = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=0).fit(variables(autres), autres.n)
        jours = sorted(d.jour.unique())
        test = d.jour.isin(jours[len(jours) // 2:])
        X = variables(d)
        brut = ia.predict(X)
        ligne = [f"{NOMS[s]:<18}"]
        e, p = score(brut[test], d.n[test])
        ligne.append(f"{e:.1f} pers., {p:.0f} % ±2")
        for n_jours in (1, 3):
            # Recalage prudent : un seul facteur d'échelle (pas de droite complète, qui colle trop à un jour),
            # appris sur les premiers jours occupés de la salle, et borné entre 0,5 et 2
            recal = d.jour.isin([j for j in jours[:len(jours) // 2] if d[d.jour == j].n.max() > 0][:n_jours])
            a = np.clip(d.n[recal].sum() / max(brut[recal].sum(), 1e-6), 0.5, 2)
            e, p = score(a * brut[test], d.n[test])
            ligne.append(f"{e:.1f} pers., {p:.0f} % ±2")
        print(" | ".join(ligne))


if __name__ == "__main__":
    main(sys.argv[1])
