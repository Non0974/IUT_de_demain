# Test de notre méthode sur une vraie salle de cours (Université du Danemark du Sud, bâtiment OU44, 2018-2019).
# Salle de 461 m3, 84 places, comptage par caméras aux portes, CO2 mesuré environ toutes les 5 min,
# volet de ventilation piloté par le CO2.
#
# À chaque fois que la salle se vide, on calcule le débit d'air de deux façons, comme dans le jumeau :
#  - avec le comptage, sur les 30 min avant les départs : Q = N x G / (C - C_base)
#  - sans le comptage, par la décroissance du CO2 dans les 16 min qui suivent
# Si la méthode marche, les deux débits doivent être proches.
#
# Utilisation : python test_co2_salle_danoise.py <dossier Dataset> [dossier des figures]

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

V = 461.48           # m3 (roominfo.txt)
G = 0.018            # m3/h de CO2 par personne assise
BLEU, ORANGE = "#2a78d6", "#eb6834"
ENCRE, ENCRE2, FOND, GRILLE = "#0b0b0b", "#52514e", "#fcfcfb", "#e4e3df"


def lire(dossier):
    def un(nom):
        return pd.read_csv(Path(dossier) / "filleddata" / f"{nom}_room_1.csv")["room_1"].values
    c = pd.read_csv(Path(dossier) / "filleddata" / "co2_room_1.csv").rename(columns={"room_1": "C"})
    c["N"], c["volet"] = un("occupant_count"), un("vav")
    brut = pd.read_csv(Path(dossier) / "original" / "co2_room_1.csv").rename(columns={"room_1": "C"})
    brut["minute"] = pd.to_timedelta(brut.Time).dt.total_seconds() / 60
    return c.sort_values(["DayId", "Time"]), brut


def departs(c, brut):
    lignes = []
    for jour, g in c.groupby("DayId"):
        g = g.reset_index(drop=True)
        C, N, volet = g.C.values, g.N.values, g.volet.values
        if (N == 0).sum() < 60:
            continue
        base = np.quantile(C[N == 0], 0.05)          # niveau de la salle vide ce jour-là
        i = 45
        while i < len(g) - 20:
            avant = slice(i - 45, i - 15)
            depart = (N[i] <= 2 and N[i - 15:i].max() >= 10
                      and N[avant].mean() >= 10 and N[avant].min() >= 0.5 * N[avant].mean()
                      and N[i:i + 16].max() <= 2)
            if not depart:
                i += 1
                continue
            exces = C[avant].mean() - base
            q_comptage = N[avant].mean() * G * 1e6 / exces if exces > 50 else np.nan
            m = brut[(brut.DayId == jour) & (brut.minute >= i) & (brut.minute <= i + 16)]
            ex = m.C.values - base
            if len(m) >= 3 and (ex > 15).all() and ex[0] > 60:
                pente = np.polyfit((m.minute.values - i) / 60, np.log(ex), 1)[0]
                lignes.append(dict(jour=jour, personnes=N[avant].mean(), Q_comptage=q_comptage,
                                   Q_decroissance=-pente * V, volet_avant=volet[avant].mean(),
                                   volet_apres=volet[i:i + 16].mean()))
            i += 30
    E = pd.DataFrame(lignes).dropna()
    E = E[E.Q_decroissance > 0]
    E["rapport"] = E.Q_comptage / E.Q_decroissance
    return E


def style(ax):
    ax.set_facecolor(FOND)
    for c in ["top", "right"]:
        ax.spines[c].set_visible(False)
    for c in ["left", "bottom"]:
        ax.spines[c].set_color(ENCRE2)
    ax.tick_params(colors=ENCRE2, labelsize=8)


def figure_journee(c, sortie, jour=19):
    g = c[c.DayId == jour]
    h = pd.to_timedelta(g.Time).dt.total_seconds() / 3600 + 2   # heure d'été au Danemark (UTC+2)
    m = (h >= 7) & (h <= 16)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 4.6), sharex=True, facecolor=FOND)
    a1.plot(h[m], g.C[m], color=BLEU, lw=2)
    a1.set_ylabel("CO₂ (ppm)", color=ENCRE2)
    a2.step(h[m], g.N[m], where="post", color=BLEU, lw=2)
    a2.set_ylabel("Personnes", color=ENCRE2)
    a2.set_xlabel("Heure", color=ENCRE2)
    for a in (a1, a2):
        style(a)
        a.grid(axis="y", color=GRILLE, lw=0.8)
    fig.suptitle("Salle de cours danoise (461 m³, 84 places) : une journée réelle", color=ENCRE, fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(Path(sortie) / "co2_journee_salle_danoise.png", dpi=160)


def figure_departs(E, sortie):
    fig, ax = plt.subplots(figsize=(5.6, 4.6), facecolor=FOND)
    style(ax)
    lim = [50, 15000]
    ax.plot(lim, lim, color=ENCRE2, lw=1, ls="--")
    ax.fill_between(lim, [x / 2 for x in lim], [x * 2 for x in lim], color=GRILLE, alpha=0.6, lw=0)
    ok = E.rapport.between(0.5, 2)
    ax.scatter(E.Q_decroissance[ok], E.Q_comptage[ok], s=55, color=BLEU, edgecolor=FOND, lw=2, label="Les deux méthodes d'accord (×2)", zorder=3)
    ax.scatter(E.Q_decroissance[~ok], E.Q_comptage[~ok], s=55, marker="s", color=ORANGE, edgecolor=FOND, lw=2, label="Désaccord", zorder=3)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel("Débit sans comptage, par la décroissance (m³/h)", color=ENCRE2)
    ax.set_ylabel("Débit avec le comptage (m³/h)", color=ENCRE2)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.set_title(f"Chaque point = une salle qui se vide ({len(E)} départs)", color=ENCRE, fontsize=10, loc="left")
    fig.tight_layout()
    fig.savefig(Path(sortie) / "co2_departs_salle_danoise.png", dpi=160)


def main(dossier, sortie):
    Path(sortie).mkdir(parents=True, exist_ok=True)
    c, brut = lire(dossier)
    E = departs(c, brut)
    pd.set_option("display.width", 160)
    print(E.round(1).to_string(index=False))
    ok = E.rapport.between(0.5, 2)
    print(f"\n{len(E)} départs exploitables, {ok.sum()} où les deux débits sont d'accord à un facteur 2 près")
    print(f"Sur ces {ok.sum()} départs : rapport médian {E.rapport[ok].median():.2f} "
          f"(de {E.rapport[ok].min():.2f} à {E.rapport[ok].max():.2f})")
    base = c[c.N == 0].groupby("DayId").C.quantile(0.05)
    print(f"Niveau de la salle vide selon les jours : de {base.min():.0f} à {base.max():.0f} ppm (capteur non recalé)")
    figure_journee(c, sortie)
    figure_departs(E, sortie)
    print(f"Figures dans {sortie}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else Path(__file__).parent / "figures")
