// Émargement vérifié : chaque étudiant badge sa carte (NFC) en entrant, et on compare
// chaque badge aux passages comptés à la porte (ToF + thermique + radar, sans caméra).
//  - un passage sans badge  : quelqu'un est entré sans badger ;
//  - un badge sans passage  : une carte a été badgée pour quelqu'un qui n'est pas entré (carte prêtée).
// Les étudiants sont pseudonymisés : le vrai système ne garde qu'une empreinte (hash) du numéro de carte.

import { EMPLOI_DU_TEMPS } from './simulation.js';

const INSCRITS = 30;
const AVANT = 6 / 60;          // fenêtre d'émargement : 6 min avant le cours...
const APRES_FIN = 4 / 60;      // ...jusqu'à la fin de la sortie
const TOLERANCE = 10 / 3600;   // un badge et un passage à moins de 10 s sont appariés

function generateur(graine) {
  // Générateur pseudo-aléatoire, pour que chaque cours soit reproductible
  let s = graine % 2147483647;
  if (s <= 0) s += 2147483646;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}

function melanger(liste, alea) {
  const l = [...liste];
  for (let i = l.length - 1; i > 0; i--) {
    const j = Math.floor(alea() * (i + 1));
    [l[i], l[j]] = [l[j], l[i]];
  }
  return l;
}

function indexCours(t) {
  return EMPLOI_DU_TEMPS.findIndex(([debut, fin]) => t >= debut - AVANT && t <= fin + APRES_FIN);
}

function nom(id) {
  return `Étudiant ${String(id).padStart(2, '0')}`;
}

export function heureCourte(t) {
  const h = Math.floor(t);
  const m = Math.round((t - h) * 60);
  return `${h} h ${String(m).padStart(2, '0')}`;
}

export function creerEmargement() {
  return {
    inscrits: Array.from({ length: INSCRITS }, (_, i) => ({ id: i + 1, nom: nom(i + 1) })),
    jour: 1,
    cours: null,       // cours en train d'être émargé
    journee: [],       // cours terminés du jour
    veille: [],        // cours de la veille (pour télécharger la feuille)
    evenements: 0,     // compteurs pour faire clignoter le lecteur dans la 3D
    alertes: 0,
  };
}

function ouvrir(em, sim, idx) {
  const [debut, fin, effectif] = EMPLOI_DU_TEMPS[idx];
  const alea = generateur(sim.jour * 100 + idx + 7);
  em.cours = {
    idx, debut, fin, effectif,
    prevus: melanger(em.inscrits.map(e => e.id), alea).slice(0, effectif), // ordre d'arrivée
    entres: 0,
    dernierN: sim.N_mesure,
    attenteBadges: [],     // { id, t }
    attentePassages: [],   // { t }
    presents: new Set(),   // badge + passage
    heureBadge: {},        // id -> heure du badge
    aVerifier: [],         // { ids, t } badges groupés pour un seul passage
    sansBadge: [],         // heures des passages sans badge
    fraudePret: false,
    fraudeSansBadge: false,
  };
}

function cloturer(em) {
  const c = em.cours;
  const suspects = new Set(c.aVerifier.flatMap(a => a.ids));
  em.journee.push({
    debut: c.debut,
    fin: c.fin,
    statuts: Object.fromEntries(em.inscrits.map(e => [e.id,
      suspects.has(e.id) ? 'à vérifier' : c.presents.has(e.id) ? 'présent' : 'absent'])),
    presents: c.presents.size,
    aVerifier: c.aVerifier.length,
    sansBadge: c.sansBadge.length,
  });
  em.cours = null;
}

// Apparie badges et passages ; ce qui reste seul plus de 10 s devient une anomalie
function apparier(em, t) {
  const c = em.cours;
  while (c.attenteBadges.length && c.attentePassages.length) {
    const b = c.attenteBadges.shift();
    c.attentePassages.shift();
    c.presents.add(b.id);
  }
  const perimes = c.attenteBadges.filter(b => t - b.t > TOLERANCE);
  if (perimes.length) {
    for (const b of perimes) {
      // Les badges passés juste avant ou après, sur un seul passage : une des cartes est prêtée
      const voisins = [...c.presents].filter(id => c.heureBadge[id] !== undefined && Math.abs(c.heureBadge[id] - b.t) <= TOLERANCE);
      c.aVerifier.push({ ids: [...voisins, b.id], t: b.t });
      em.alertes += 1;
    }
    c.attenteBadges = c.attenteBadges.filter(b => t - b.t <= TOLERANCE);
  }
  const passagesPerimes = c.attentePassages.filter(p => t - p.t > TOLERANCE);
  if (passagesPerimes.length) {
    for (const p of passagesPerimes) c.sansBadge.push(p.t);
    em.alertes += 1;
    c.attentePassages = c.attentePassages.filter(p => t - p.t <= TOLERANCE);
  }
}

function badger(em, id, t) {
  const c = em.cours;
  c.heureBadge[id] = t;
  c.attenteBadges.push({ id, t });
  em.evenements += 1;
}

export function majEmargement(em, sim) {
  if (sim.jour !== em.jour) {
    if (em.cours) cloturer(em);
    em.veille = em.journee;
    em.journee = [];
    em.jour = sim.jour;
  }
  const idx = indexCours(sim.t);
  if (em.cours && em.cours.idx !== idx) cloturer(em);
  if (idx < 0) return;
  if (!em.cours) ouvrir(em, sim, idx);
  const c = em.cours;

  // Passages d'entrée vus par les capteurs de la porte (hausse du comptage)
  const hausse = sim.N_mesure - c.dernierN;
  for (let k = 0; k < hausse; k++) c.attentePassages.push({ t: sim.t });
  c.dernierN = sim.N_mesure;

  // Ce qui se passe vraiment à la porte (la simulation le sait, pas le système)
  while (c.entres < sim.N_reel && c.entres < c.prevus.length) {
    const id = c.prevus[c.entres];
    c.entres += 1;
    if (sim.pannes.sansBadge && !c.fraudeSansBadge) {
      c.fraudeSansBadge = true;            // il entre sans badger
      continue;
    }
    badger(em, id, sim.t);
    if (sim.pannes.badgePrete && !c.fraudePret) {
      // il badge aussi la carte d'un absent
      const absent = em.inscrits.find(e => !c.prevus.includes(e.id));
      if (absent) badger(em, absent.id, sim.t);
      c.fraudePret = true;
    }
  }

  apparier(em, sim.t);
}

// Ce que le système peut dire, pour les panneaux
export function bilanEmargement(em, diag) {
  const c = em.cours;
  if (!c) {
    const dernier = em.journee[em.journee.length - 1] || null;
    return { cours: null, dernier };
  }
  const alertes = [];
  if (c.sansBadge.length) {
    const n = c.sansBadge.length;
    const comptageFaux = diag && diag.comptage.etat === 'detecte';
    // Une fraude, c'est une ou deux personnes. Au-delà, c'est le comptage qui se trompe.
    const tropNombreux = n >= 3;
    if (comptageFaux) {
      alertes.push({ niveau: 'suspect', texte: `${n} passages de plus que de badges, mais le diagnostic CO₂ confirme que le comptage est faux : ce n'est pas une fraude.` });
    } else if (tropNombreux) {
      alertes.push({ niveau: 'suspect', texte: `${n} passages de plus que de badges : trop pour de la fraude, c'est sûrement le comptage qui se trompe. Le diagnostic CO₂ va le confirmer.` });
    } else {
      alertes.push({ niveau: 'detecte', texte: `${n} entrée${n > 1 ? 's' : ''} sans badge (${heureCourte(c.sansBadge[0])}). On ne sait pas qui : l'enseignant vérifie.` });
    }
  }
  for (const a of c.aVerifier) {
    alertes.push({
      niveau: 'detecte',
      texte: `${a.ids.map(nom).join(' et ')} : ${a.ids.length} badges pour un seul passage (${heureCourte(a.t)}). Une des cartes est prêtée.`,
    });
  }
  const suspects = new Set(c.aVerifier.flatMap(a => a.ids));
  return {
    cours: c,
    badges: c.presents.size + c.aVerifier.length,
    passages: c.presents.size + c.sansBadge.length,
    alertes,
    statuts: em.inscrits.map(e => ({
      ...e,
      statut: suspects.has(e.id) ? 'verifier' : c.presents.has(e.id) ? 'present' : 'absent',
    })),
  };
}

// Présence sur une demi-journée (ce que demande le CFA) : présent à tous les cours
function demiJournee(cours, id) {
  if (!cours.length) return '';
  const s = cours.map(c => c.statuts[id]);
  if (s.every(x => x === 'présent')) return 'présent';
  if (s.every(x => x === 'absent')) return 'absent';
  return s.includes('à vérifier') ? 'à vérifier' : 'partiel';
}

// Feuille d'émargement du jour au format CSV (séparateur ; pour Excel)
export function feuilleCsv(em) {
  const cours = em.journee.length ? em.journee : em.veille;
  const matin = cours.filter(c => c.fin <= 12.5);
  const apresMidi = cours.filter(c => c.fin > 12.5);
  const entete = ['Étudiant', ...cours.map(c => `${heureCourte(c.debut)} - ${heureCourte(c.fin)}`), 'Matin', 'Après-midi'];
  const lignes = em.inscrits.map(e => [e.nom, ...cours.map(c => c.statuts[e.id]),
    demiJournee(matin, e.id), demiJournee(apresMidi, e.id)]);
  lignes.push(['Entrées sans badge', ...cours.map(c => String(c.sansBadge)), '', '']);
  return '﻿' + [entete, ...lignes].map(l => l.join(';')).join('\r\n');
}
