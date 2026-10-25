# Test : peut-on compter les personnes d'une salle avec le nombre d'appareils connectés au Wi-Fi ?
# Données réelles ROBOD (Université nationale de Singapour, 2021) : 5 salles, une mesure toutes les 5 min,
# avec le vrai nombre de personnes.
#
# Utilisation : python test_wifi_robod.py <dossier des CSV ROBOD> [dossier des figures]

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BLEU, ORANGE = "#2a78d6", "#eb6834"
ENCRE, ENCRE2, FOND = "#0b0b0b", "#52514e", "#fcfcfb"
NOMS = {1: "Salle de cours 1", 2: "Salle de cours 2", 3: "Bureau 1", 4: "Bureau 2", 5: "Bibliothèque"}


def lire(dossier, salle):
    d = pd.read_csv(Path(dossier) / f"combined_Room{salle}.csv")
    d["t"] = pd.to_datetime(d["timestamp"].str[:16])
    d["jour"] = d["timestamp"].str[:10]
    return d.rename(columns={"wifi_connected_devices [number]": "wifi", "occupant_count [number]": "n"})


def modele(entrainement):
    # Le plus simple possible : personnes = a * appareils + b
    a, b = np.polyfit(entrainement.wifi, entrainement.n, 1)
    return lambda wifi: np.clip(np.round(a * wifi + b), 0, None), a, b


def erreurs(pred, reel):
    occupee = reel > 0
    err = np.abs(pred - reel)
    return err[occupee].mean(), 100 * (err[occupee] <= 2).mean(), reel[occupee].mean()


def main(dossier, sortie):
    Path(sortie).mkdir(parents=True, exist_ok=True)
    print("Salle             | modèle               | erreur moy. (salle occupée) | à ±2 près | personnes en moy.")
    resultats = {}
    for salle in NOMS:
        d = lire(dossier, salle)
        jours = sorted(d.jour.unique())
        moitie = len(jours) // 2
        app, test = d[d.jour.isin(jours[:moitie])], d[d.jour.isin(jours[moitie:])]
        predire, a, b = modele(app)
        e, p2, moy = erreurs(predire(test.wifi), test.n)
        resultats[salle] = (test, predire)
        print(f"{NOMS[salle]:<17} | n = {a:.2f} x wifi {b:+.2f} | {e:.1f} pers.                   | {p2:.0f} %      | {moy:.1f}")

    # Une salle sert de référence, on applique son modèle à une autre sans recaler
    d1, d2 = lire(dossier, 1), lire(dossier, 2)
    predire, _, _ = modele(d1)
    e, p2, _ = erreurs(predire(d2.wifi), d2.n)
    print(f"\nModèle de la salle 1 utilisé tel quel dans la salle 2 : {e:.1f} pers. d'erreur, {p2:.0f} % à ±2 près")

    # Figure : salle de cours 1, trois jours de test
    test, predire = resultats[1]
    jours = [j for j in sorted(test.jour.unique()) if test[test.jour == j].n.max() >= 15][:3]
    fig, axes = plt.subplots(1, len(jours), figsize=(11, 3.2), sharey=True, facecolor=FOND)
    for ax, j in zip(np.atleast_1d(axes), jours):
        s = test[(test.jour == j) & (test.t.dt.hour.between(8, 22))]
        ax.set_facecolor(FOND)
        ax.step(s.t, s.n, where="post", color=BLEU, lw=2, label="Vrai nombre")
        ax.step(s.t, predire(s.wifi), where="post", color=ORANGE, lw=2, label="Estimé avec le Wi-Fi")
        ax.set_title(pd.Timestamp(j).strftime("%d/%m/%Y"), color=ENCRE, fontsize=10)
        ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%Hh"))
        for c in ["top", "right"]:
            ax.spines[c].set_visible(False)
        for c in ["left", "bottom"]:
            ax.spines[c].set_color(ENCRE2)
        ax.tick_params(colors=ENCRE2, labelsize=8)
        ax.grid(axis="y", color="#e4e3df", lw=0.8)
    np.atleast_1d(axes)[0].set_ylabel("Personnes", color=ENCRE2)
    np.atleast_1d(axes)[0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.suptitle("ROBOD, salle de cours 1 : comptage par le Wi-Fi (jours de test)", color=ENCRE, fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(Path(sortie) / "wifi_robod_salle1.png", dpi=160)
    print(f"Figure : {Path(sortie) / 'wifi_robod_salle1.png'}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else Path(__file__).parent / "figures")
