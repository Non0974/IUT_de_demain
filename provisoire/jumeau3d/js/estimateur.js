// Estimation du débit d'air réel et diagnostic des 4 causes.
// Deux méthodes indépendantes :
//  - salle occupée : bilan de CO2 intégré sur 10 min, à partir du comptage N ;
//  - salle qui se vide : décroissance exponentielle du CO2, sans besoin du comptage.
// La nuit, le CO2 doit revenir vers l'air extérieur : sinon le capteur dérive.

import { SALLE, C_EXT, G_MODELE, DEBITS, INFILTRATION } from './simulation.js';

const PAS_H = 5 / 3600;            // une mesure toutes les 5 s
const FENETRE_OCC = 10 / 60;       // 10 min pour l'estimation en occupation
const MOYENNE_BORNES = 1 / 60;     // moyenne sur 1 min aux deux bouts de la fenêtre
const ATTENTE_DECROISSANCE = 3 / 60;
const DUREE_MIN_DECROISSANCE = 6 / 60;
const NUIT_DEBUT = 19.5;
const NUIT_FIN = 20.5;
const SEUIL_DERIVE = 80;           // ppm
const VALIDITE_PREUVE = 14;        // h : la décroissance de la veille au soir reste utilisable le matin
const T_NORMALE = 20;              // °C dans la salle
const RATIO_MIN = 0.7;             // débit estimé / attendu considéré comme normal
const RATIO_MAX = 1.25;
const RETOUR_NORMAL = 0.5;         // h de mesures normales avant d'oublier une anomalie

export function debitAttendu(niveau) {
  return DEBITS[niveau] + INFILTRATION;
}

export function creerEstimateur() {
  return {
    echantillons: [],     // { ta, C, Cbrut, N, niveau, T }
    correction: 0,        // ppm retirés au capteur de CO2 après détection d'une dérive
    occ: null,            // dernière estimation en occupation { Q, Qatt, ta, niveau }
    dec: null,            // dernière estimation par décroissance { Q, Qatt, ta }
    base: null,           // dernière mesure de nuit { ecart, ta }
    debutVide: null,
    nuit: { somme: 0, n: 0, jour: null },
    anomalieOcc: null,    // début de l'anomalie sur l'estimation en occupation
    normalDepuis: null,
  };
}

function moyenne(tab, champ) {
  return tab.reduce((s, e) => s + e[champ], 0) / tab.length;
}

export function ajouterMesure(est, sim) {
  const ta = (sim.jour - 1) * 24 + sim.t;
  const e = {
    ta,
    Cbrut: sim.mesures.C,
    C: sim.mesures.C - est.correction,
    N: sim.N_mesure,
    niveau: sim.niveau,
    T: sim.mesures.T_fenetre,
  };
  est.echantillons.push(e);
  // On garde 3 h d'historique
  while (est.echantillons.length && est.echantillons[0].ta < ta - 3) est.echantillons.shift();

  estimerOccupation(est, ta);
  estimerDecroissance(est, e);
  mesurerNuit(est, sim, e);
}

function estimerOccupation(est, ta) {
  const fen = est.echantillons.filter(e => e.ta > ta - FENETRE_OCC);
  if (fen.length < FENETRE_OCC / PAS_H * 0.9) return;
  const niveau = fen[0].niveau;
  if (!fen.every(e => e.N >= 8 && e.niveau === niveau)) return;
  if (moyenne(fen, 'C') - C_EXT < 300) return;

  const n = Math.round(MOYENNE_BORNES / PAS_H);
  const Cdebut = moyenne(fen.slice(0, n), 'C');
  const Cfin = moyenne(fen.slice(-n), 'C');
  let production = 0;   // ppm produits sur la fenêtre
  let exces = 0;        // intégrale de (C - Cext) en ppm.h
  for (const e of fen) {
    production += (e.N * G_MODELE / SALLE.volume) * 1e6 * PAS_H;
    exces += (e.C - C_EXT) * PAS_H;
  }
  const Q = SALLE.volume * (production - (Cfin - Cdebut)) / exces;
  const Qatt = debitAttendu(niveau);
  est.occ = { Q, Qatt, ta, niveau };
  const r = Q / Qatt;
  if (r < RATIO_MIN || r > RATIO_MAX) {
    est.normalDepuis = null;
    if (est.anomalieOcc === null) est.anomalieOcc = ta;
  } else {
    if (est.normalDepuis === null) est.normalDepuis = ta;
    if (ta - est.normalDepuis > RETOUR_NORMAL) est.anomalieOcc = null;
  }
}

function estimerDecroissance(est, e) {
  if (e.N > 0 || e.niveau === 'arret') {
    est.debutVide = null;
    return;
  }
  if (est.debutVide === null) {
    est.debutVide = { ta: e.ta, niveau: e.niveau, Cdebut: e.C };
    return;
  }
  if (e.niveau !== est.debutVide.niveau) {
    est.debutVide = { ta: e.ta, niveau: e.niveau, Cdebut: e.C };
    return;
  }
  if (est.debutVide.Cdebut - C_EXT < 150) return;

  const fen = est.echantillons.filter(x => x.ta >= est.debutVide.ta + ATTENTE_DECROISSANCE
    && x.C - C_EXT > 40);
  if (fen.length < DUREE_MIN_DECROISSANCE / PAS_H) return;

  // Régression linéaire de ln(C - Cext) en fonction du temps : pente = -Q / V
  const xs = fen.map(x => x.ta);
  const ys = fen.map(x => Math.log(x.C - C_EXT));
  const mx = xs.reduce((s, x) => s + x, 0) / xs.length;
  const my = ys.reduce((s, y) => s + y, 0) / ys.length;
  let num = 0;
  let den = 0;
  for (let i = 0; i < xs.length; i++) {
    num += (xs[i] - mx) * (ys[i] - my);
    den += (xs[i] - mx) ** 2;
  }
  const pente = num / den;
  est.dec = { Q: -pente * SALLE.volume, Qatt: debitAttendu(e.niveau), ta: e.ta };
}

function mesurerNuit(est, sim, e) {
  const h = sim.t;
  if (h >= NUIT_DEBUT && h < NUIT_FIN && e.N === 0 && e.niveau !== 'arret') {
    if (est.nuit.jour !== sim.jour) est.nuit = { somme: 0, n: 0, jour: sim.jour };
    est.nuit.somme += e.Cbrut - C_EXT;
    est.nuit.n += 1;
  } else if (h >= NUIT_FIN && est.nuit.jour === sim.jour && est.nuit.n > 0) {
    const ecart = est.nuit.somme / est.nuit.n;
    est.base = { ecart, ta: e.ta };
    // Recalibrage automatique du capteur de CO2
    const nouvelle = Math.abs(ecart) > SEUIL_DERIVE ? ecart : 0;
    if (Math.abs(nouvelle - est.correction) > 1) {
      // Les estimations faites avec l'ancien réglage sont fausses : on les oublie
      est.occ = null;
      est.dec = null;
      est.anomalieOcc = null;
    }
    est.correction = nouvelle;
    est.nuit.n = 0;
  }
}

function recent(preuve, ta) {
  return preuve && ta - preuve.ta < VALIDITE_PREUVE;
}

// Baisse de température près de la fenêtre : sur les 15 dernières minutes,
// ou par rapport à la température normale si la fenêtre reste ouverte longtemps
function chuteTemperature(est) {
  const e = est.echantillons;
  if (e.length < 2) return 0;
  const maintenant = e[e.length - 1];
  const avant = e.find(x => x.ta >= maintenant.ta - 15 / 60) || e[0];
  return Math.max(avant.T - maintenant.T, T_NORMALE - maintenant.T);
}

const fmt = q => `${Math.round(q)} m³/h`;

// Renvoie l'état des 4 causes : 'attente' | 'ok' | 'suspect' | 'detecte'
export function diagnostiquer(est) {
  const dernier = est.echantillons[est.echantillons.length - 1];
  const ta = dernier ? dernier.ta : 0;
  const occ = recent(est.occ, ta) ? est.occ : null;
  const dec = recent(est.dec, ta) ? est.dec : null;
  const rOcc = occ ? occ.Q / occ.Qatt : null;
  const rDec = dec ? dec.Q / dec.Qatt : null;
  const chute = chuteTemperature(est);

  const causes = {
    ventilation: { titre: 'Ventilation en panne', etat: 'attente', message: 'Pas encore assez de mesures.' },
    fenetre: { titre: 'Fenêtre ouverte', etat: 'ok', message: 'Température stable près de la fenêtre.' },
    derive: { titre: 'Capteur de CO₂ qui dérive', etat: 'attente', message: 'Vérification pendant la nuit (19 h 30 – 20 h 30).' },
    comptage: { titre: 'Comptage faux', etat: 'attente', message: 'Il faut une estimation en cours et une décroissance.' },
  };

  // Dérive du capteur de CO2 : mesure de nuit
  if (est.base) {
    const ecart = Math.round(est.base.ecart);
    if (Math.abs(ecart) > SEUIL_DERIVE) {
      causes.derive = { ...causes.derive, etat: 'detecte',
        message: `La nuit, le capteur indique ${C_EXT + ecart} ppm au lieu d'environ ${C_EXT}. Corrigé automatiquement de ${ecart} ppm.` };
    } else {
      causes.derive = { ...causes.derive, etat: 'ok', message: `La nuit, le CO₂ revient à ${C_EXT + ecart} ppm : capteur juste.` };
    }
  }

  // Fenêtre ouverte : chute de température, confirmée par un débit trop fort
  const debitFort = (rOcc !== null && rOcc > 1.4) || (rDec !== null && rDec > 1.4);
  if (chute >= 2 && debitFort) {
    causes.fenetre = { ...causes.fenetre, etat: 'detecte',
      message: `Température −${chute.toFixed(1)} °C près de la fenêtre et débit d'air trop fort.` };
  } else if (chute >= 2) {
    causes.fenetre = { ...causes.fenetre, etat: 'suspect',
      message: `Température −${chute.toFixed(1)} °C près de la fenêtre.` };
  }

  // Ventilation en panne : débit trop faible avec les deux méthodes
  if (rOcc !== null || rDec !== null) {
    const faibleOcc = rOcc !== null && rOcc < 0.6;
    const faibleDec = rDec !== null && rDec < 0.55;
    if (faibleOcc && faibleDec) {
      causes.ventilation = { ...causes.ventilation, etat: 'detecte',
        message: `Débit mesuré ${fmt(dec.Q)} au lieu de ${fmt(dec.Qatt)}, avec et sans le comptage.` };
    } else if (faibleOcc || faibleDec) {
      const p = faibleDec ? dec : occ;
      causes.ventilation = { ...causes.ventilation, etat: 'suspect',
        message: `Débit ${fmt(p.Q)} au lieu de ${fmt(p.Qatt)}, à confirmer par l'autre méthode.` };
    } else {
      causes.ventilation = { ...causes.ventilation, etat: 'ok', message: 'Le débit mesuré correspond à la commande.' };
    }
  }

  // Comptage faux : les deux méthodes ne donnent pas le même débit alors que la décroissance est normale.
  // La décroissance doit être postérieure au début de l'anomalie, sinon une panne de
  // ventilation apparue le matin ressemblerait à un comptage faux.
  if (rOcc !== null && rDec !== null) {
    const rapport = rOcc / rDec;
    const decNormale = rDec > RATIO_MIN && rDec < 1.4;
    const ecart = rapport > RATIO_MAX || rapport < RATIO_MIN;
    const decApresAnomalie = est.anomalieOcc !== null && dec.ta > est.anomalieOcc;
    if (decNormale && chute < 2 && ecart && decApresAnomalie) {
      causes.comptage = { ...causes.comptage, etat: 'detecte',
        message: `Avec le comptage : ${Math.round(rOcc * 100)} % du débit attendu ; sans le comptage : ${Math.round(rDec * 100)} %. Le comptage est faux.` };
    } else if (decNormale && chute < 2 && ecart) {
      causes.comptage = { ...causes.comptage, etat: 'suspect',
        message: 'Le débit calculé avec le comptage est anormal. Confirmation à la prochaine décroissance (salle vide).' };
    } else {
      causes.comptage = { ...causes.comptage, etat: 'ok', message: 'Les deux méthodes donnent le même débit.' };
    }
  }

  return causes;
}
