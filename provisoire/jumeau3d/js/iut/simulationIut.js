// Simulation de tout le bâtiment : qui entre dans quelle salle, les badges, le Wi-Fi et le CO2.
// Ce que le système "sait" :
//  - dans la salle équipée (SAR 200), le nombre exact de personnes (capteurs de la porte) ;
//  - ailleurs, une estimation par le Wi-Fi (environ ±2 personnes, comme sur les données ROBOD) ;
//  - partout, les badges (émargement) et le CO2.

import { SALLES } from './batiment.js';
import { COURS, GROUPES, JOURS } from './edt.js';

const G = 0.018;                // m3/h de CO2 par personne
const C_EXT = 420;              // ppm
const APPAREILS_PAR_PERSONNE = 1.1;   // coefficient appris pendant le recalage de chaque salle
export const HEURE_DEBUT = 7.5;
export const HEURE_FIN = 20;

function generateur(graine) {
  let s = graine;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}

function nomEtudiant(cle, i) {
  const groupe = GROUPES[cle] ? cle : cle.replace('S', 'G');
  return `${groupe}-${String(i + 1).padStart(2, '0')}`;
}

// Débit d'air de la salle (valeurs inventées pour la démo)
function debit(salle, t, occupee) {
  const infiltration = 0.2 * salle.volume;
  if (salle.ventilation === 'meca') return infiltration + (t >= 7.5 && t <= 19.5 ? 25 * salle.places : 0);
  if (salle.ventilation === 'faible') return infiltration + 8 * salle.places;
  return infiltration + (occupee ? 12 * salle.places : 3 * salle.places);   // fenêtre ouverte de temps en temps
}

// Tire au sort, pour chaque cours du jour, qui vient, à quelle heure, avec combien d'appareils
function preparerJour(sim) {
  const alea = generateur(1000 + sim.jour * 37 + sim.semaine * 101);
  sim.participations = {};
  for (const c of COURS.filter(c => c.jour === sim.jour)) {
    const personnes = [];
    for (const cle of c.cles) {
      const effectif = GROUPES[cle] ? GROUPES[cle].effectif : c.effectif;
      for (let i = 0; i < effectif; i++) {
        const retard = alea() < 0.06;
        personnes.push({
          id: nomEtudiant(cle, i),
          etudiant: true,
          absent: alea() < 0.08,
          arrivee: c.debut + (retard ? 10 + 15 * alea() : -8 + 12 * alea()) / 60,
          depart: c.fin + (3 * alea()) / 60,
          badge: alea() > 0.03,
          appareils: alea() < 0.15 ? 0 : alea() < 0.7 ? 1 : 2,
        });
      }
    }
    personnes.push({ id: c.enseignant, etudiant: false, absent: false, arrivee: c.debut - 5 / 60, depart: c.fin + 5 / 60, badge: false, appareils: 1 });
    sim.participations[c.id] = personnes;
  }
}

export function creerSimIut() {
  const sim = { semaine: 0, jour: 0, t: HEURE_DEBUT, salles: {}, participations: {} };
  for (const s of SALLES) {
    sim.salles[s.id] = { C: C_EXT + 20, wifiLisse: 0, N_reel: 0, N_affiche: 0, badges: 0, cours: [], ecartMinutes: 0 };
  }
  preparerJour(sim);
  return sim;
}

export function coursActifs(salleId, jour, t) {
  return COURS.filter(c => c.salle === salleId && c.jour === jour && t >= c.debut - 10 / 60 && t <= c.fin + 5 / 60);
}

// Statut d'émargement d'un étudiant pour un cours, à l'heure t
export function statut(p, c, t) {
  const arrive = !p.absent && t >= p.arrivee;
  if (!arrive) return t < c.debut + 10 / 60 ? 'attendu' : 'absent';
  if (!p.badge) return 'non badgé';
  return p.arrivee > c.debut + 10 / 60 ? 'retard' : 'présent';
}

export function pasIut(sim, dt) {
  sim.t += dt;
  if (sim.t >= HEURE_FIN) {
    sim.t = HEURE_DEBUT;
    sim.jour = (sim.jour + 1) % JOURS.length;
    if (sim.jour === 0) sim.semaine += 1;
    preparerJour(sim);
  }
  const t = sim.t;
  const alea = Math.random;
  for (const salle of SALLES) {
    const etat = sim.salles[salle.id];
    etat.cours = coursActifs(salle.id, sim.jour, t);
    let n = 0;
    let appareils = 0;
    let badges = 0;
    for (const c of etat.cours) {
      for (const p of sim.participations[c.id]) {
        const dedans = !p.absent && t >= p.arrivee && t < p.depart;
        if (dedans) {
          n += 1;
          for (let k = 0; k < p.appareils; k++) if (alea() < 0.92) appareils += 1;
        }
        if (p.etudiant && !p.absent && p.badge && t >= p.arrivee) badges += 1;
      }
    }
    if (alea() < 0.15) appareils += 1;   // un appareil qui traîne (ordinateur fixe, téléphone oublié)
    etat.N_reel = n;
    etat.badges = badges;
    etat.wifiLisse += (appareils / APPAREILS_PAR_PERSONNE - etat.wifiLisse) * 0.3;
    etat.N_affiche = salle.equipee ? n : Math.max(0, Math.round(etat.wifiLisse));
    // Écart Wi-Fi / badges : on ne le signale que s'il dure 10 min (le Wi-Fi est bruité)
    const ecart = etat.cours.length && etat.N_affiche - (badges + etat.cours.length) >= 6;
    etat.ecartMinutes = ecart ? etat.ecartMinutes + dt * 60 : 0;

    // Bilan de CO2 de la salle
    const Q = debit(salle, t, n > 0);
    etat.C += dt * ((n * G * 1e6) / salle.volume - (Q / salle.volume) * (etat.C - C_EXT));
    etat.Q = Q;
  }
}

// Alertes d'une salle pour le directeur
export function alertesSalle(salle, etat) {
  const alertes = [];
  if (etat.C >= 1200) alertes.push({ niveau: 'detecte', texte: `Air mauvais : ${Math.round(etat.C)} ppm de CO₂. Il faut aérer.` });
  else if (etat.C >= 800) alertes.push({ niveau: 'suspect', texte: `Air moyen : ${Math.round(etat.C)} ppm de CO₂.` });
  const enseignants = etat.cours.length;
  if (salle.equipee) {
    const sansBadge = etat.N_reel - enseignants - etat.badges;
    if (sansBadge > 0) alertes.push({ niveau: 'detecte', texte: `${sansBadge} personne${sansBadge > 1 ? 's' : ''} entrée${sansBadge > 1 ? 's' : ''} sans badger (comptage de la porte).` });
  } else if (etat.ecartMinutes >= 10) {
    alertes.push({ niveau: 'suspect', texte: `Le Wi-Fi voit ${etat.N_affiche} personnes pour ${etat.badges} badges : à vérifier.` });
  }
  return alertes;
}

// Saute à un jour et une heure : on repart du matin pour que le CO2 soit cohérent
export function allerA(sim, jour, t) {
  sim.jour = jour;
  sim.t = HEURE_DEBUT;
  for (const s of SALLES) sim.salles[s.id].C = C_EXT + 20;
  preparerJour(sim);
  while (sim.t < t) pasIut(sim, 1 / 60);
}

// État affiché par les panneaux et la 3D : même forme que celui envoyé par le serveur
export function etatLocal(sim) {
  const salles = {};
  for (const s of SALLES) {
    const e = sim.salles[s.id];
    salles[s.id] = {
      personnes: e.N_affiche,
      source: s.equipee ? 'porte' : 'wifi',
      co2: e.C,
      reel: e.N_reel,
      airParPersonne: e.N_reel ? e.Q / e.N_reel : null,
      alertes: alertesSalle(s, e),
      cours: e.cours.map(c => {
        // Le système ne sait pas qu'un étudiant non badgé est là : pour lui, il est absent
        const emargement = sim.participations[c.id].filter(p => p.etudiant)
          .map(p => ({ id: p.id, statut: statut(p, c, sim.t).replace('non badgé', 'absent') }));
        return { ...c, emargement, badges: emargement.filter(x => x.statut === 'présent' || x.statut === 'retard').length };
      }),
    };
  }
  return { jour: sim.jour, t: sim.t, titre: JOURS[sim.jour], source: 'locale', salles };
}
