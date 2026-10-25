// Salle SAR 200 en détail : boucle principale.
// Si la page est servie par le serveur CampusTwin, elle affiche ses données (capteurs réels ou
// simulation du serveur). Sinon, elle simule elle-même la salle dans le navigateur.

import { creerSimulation, pas, HEURE_DEBUT, HEURE_FIN } from './simulation.js';
import { creerEstimateur, ajouterMesure, diagnostiquer } from './estimateur.js';
import { creerEmargement, majEmargement, bilanEmargement, feuilleCsv } from './emargement.js';
import { creerScene } from './scene.js';
import { creerHud } from './hud.js';

const PAS = 5 / 3600;              // une mesure toutes les 5 s (simulées)
const MAX_PAS_PAR_IMAGE = 3000;
const SALLE = 'SAR 200';
const NOMS_JOURS = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'];

let sim;
let est;
let em;
let historique;
let vitesse = 300;                 // secondes simulées par seconde réelle
let enPause = false;
let reste = 0;

function initialiser() {
  sim = creerSimulation();
  est = creerEstimateur();
  em = creerEmargement();
  historique = [];
  reste = 0;
}
initialiser();

function telechargerFeuille() {
  const lien = document.createElement('a');
  lien.href = URL.createObjectURL(new Blob([feuilleCsv(em)], { type: 'text/csv;charset=utf-8' }));
  lien.download = `emargement_jour${em.journee.length ? em.jour : em.jour - 1}.csv`;
  lien.click();
  URL.revokeObjectURL(lien.href);
}

// ---------- données du serveur ----------

let serveur = null;                // { etat, historique, simulation }

function postJson(url, corps) {
  return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corps) });
}

async function essayerServeur() {
  try {
    const r = await fetch('/api/etat', { cache: 'no-store' });
    if (r.status === 401) {
      // Servie par le serveur CampusTwin, mais pas connecté : on passe par la page de connexion
      location.href = `/suivi/connexion.html?retour=${encodeURIComponent(location.pathname)}`;
      return null;
    }
    if (!r.ok) return null;           // 403 (enseignant) ou simple serveur web : simulation locale
    const d = await r.json();
    const s = { etat: d, historique: [], simulation: d.simulation };
    const flux = new EventSource('/api/flux');
    flux.onmessage = e => { s.etat = JSON.parse(e.data); };
    const lireHistorique = async () => {
      try {
        const h = await (await fetch(`/api/historique?salle=${encodeURIComponent(SALLE)}`)).json();
        s.historique = h.map(p => ({ t: p.heure, C: p.C, N: p.N }));
      } catch { /* on réessaiera */ }
    };
    lireHistorique();
    setInterval(lireHistorique, 15000);
    // Le temps est celui du serveur ; les pannes n'existent qu'avec le serveur en simulation
    document.getElementById('vitesse').closest('.groupe').hidden = true;
    document.getElementById('telecharger').hidden = true;
    if (!d.simulation) {
      document.getElementById('pannes').closest('.groupe').hidden = true;
      document.getElementById('fraudes').closest('.groupe').hidden = true;
    }
    document.querySelector('.panneau.gauche h2').textContent = d.simulation ? 'Salle SAR 200 (serveur, simulation)' : 'Salle SAR 200 (capteurs réels)';
    return s;
  } catch {
    return null;
  }
}

// Met les données du serveur sous la forme qu'attendent la 3D et les panneaux
function vueServeur(d, historiqueServeur) {
  const s = d.salles[SALLE];
  const diag = s.air.diagnostic;
  const detecte = cle => diag[cle] && diag[cle].etat === 'detecte';
  // En simulation, la 3D montre la vraie panne ; avec les vrais capteurs, ce que le diagnostic a trouvé
  const pannes = d.pannes || { ventilation: detecte('ventilation'), fenetre: detecte('fenetre'), derive: detecte('derive'), comptage: detecte('comptage') };
  const cours = s.cours[0];
  const etudiants = s.cours.flatMap(c => c.emargement);
  const alertesBadge = s.alertes.filter(a => /badge|carte|passage/i.test(a.texte));
  const vu = { 'présent': 'present', retard: 'present', 'à vérifier': 'verifier' };
  return {
    sim: {
      t: d.heure, jour: d.jour, titreJour: `${NOMS_JOURS[d.jour]} ${d.date}`,
      N_reel: s.personnes, N_mesure: s.personnes, niveau: s.niveau || 'arret', pannes,
      mesures: { C: s.co2_brut ?? 420, T_fenetre: s.temp ?? 20 },
      coursServeur: cours ? [cours.debut, cours.fin, etudiants.length] : null,
    },
    est: {
      correction: s.air.correction || 0,
      occ: s.air.q_occupation != null ? { Q: s.air.q_occupation } : null,
      dec: s.air.q_decroissance != null ? { Q: s.air.q_decroissance } : null,
    },
    diag,
    bilan: cours ? {
      cours: true,
      libelle: 'Badgés / inscrits',
      badges: s.cours.reduce((n, c) => n + c.badges, 0),
      passages: etudiants.length,
      alertes: alertesBadge,
      texteOk: 'Chaque badge correspond à un passage à la porte.',
      statuts: etudiants.map(e => ({ nom: e.id, statut: vu[e.statut] || 'absent' })),
    } : { cours: null, dernier: null },
    historique: historiqueServeur,
    scene: { badges: s.cours.reduce((n, c) => n + c.badges, 0), alertes: alertesBadge.length },
  };
}

// ---------- 3D et panneaux ----------

const scene = creerScene(document.getElementById('vue3d'));
const hud = creerHud({
  surPanne: cle => {
    if (serveur) postJson('/api/simulation/panne', { salle: SALLE, panne: cle });
    else sim.pannes[cle] = !sim.pannes[cle];
  },
  surVitesse: v => { vitesse = v; },
  surPause: () => { enPause = !enPause; },
  surReinitialiser: () => { initialiser(); scene.vider(); },
  surTelecharger: telechargerFeuille,
});

serveur = await essayerServeur();

let derniereImage = performance.now();
let dernierHud = 0;
let texteLecteur = '';
let vue = null;

function boucle(maintenant) {
  const dtReel = Math.min(0.1, (maintenant - derniereImage) / 1000);
  derniereImage = maintenant;

  if (serveur) {
    if (!vue || maintenant - dernierHud > 200) vue = vueServeur(serveur.etat, serveur.historique);
    scene.rendre({
      N_reel: vue.sim.N_reel, N_mesure: vue.sim.N_mesure, Caffiche: vue.sim.mesures.C - vue.est.correction,
      niveau: vue.sim.niveau, pannes: vue.sim.pannes, badges: vue.scene.badges, alertesBadge: vue.scene.alertes,
      texteLecteur: vue.bilan.cours ? `Badgés : ${vue.bilan.badges} / ${vue.bilan.passages}` : '',
    }, dtReel);
    if (maintenant - dernierHud > 200) {
      hud.mettreAJour(vue.sim, vue.est, vue.diag, vue.bilan, vue.historique, null, false, HEURE_DEBUT, HEURE_FIN);
      dernierHud = maintenant;
    }
    requestAnimationFrame(boucle);
    return;
  }

  if (!enPause) {
    reste += (dtReel * vitesse) / 3600;
    let n = 0;
    while (reste >= PAS && n < MAX_PAS_PAR_IMAGE) {
      const jourAvant = sim.jour;
      pas(sim, PAS);
      ajouterMesure(est, sim);
      majEmargement(em, sim);
      if (sim.jour !== jourAvant) historique = [];
      if (historique.length === 0 || sim.t - historique[historique.length - 1].t > 1 / 60) {
        historique.push({ t: sim.t, C: sim.mesures.C - est.correction, N: sim.N_mesure });
      }
      reste -= PAS;
      n += 1;
    }
    if (n === MAX_PAS_PAR_IMAGE) reste = 0;
  }

  scene.rendre({
    N_reel: sim.N_reel,
    N_mesure: sim.N_mesure,
    Caffiche: sim.mesures.C - est.correction,
    niveau: sim.niveau,
    pannes: sim.pannes,
    badges: em.evenements,
    alertesBadge: em.alertes,
    texteLecteur,
  }, dtReel);

  if (maintenant - dernierHud > 200) {
    const diag = diagnostiquer(est);
    const bilan = bilanEmargement(em, diag);
    texteLecteur = bilan.cours ? `Badges : ${bilan.badges} / passages : ${bilan.passages}` : '';
    hud.mettreAJour(sim, est, diag, bilan, historique, vitesse, enPause, HEURE_DEBUT, HEURE_FIN);
    dernierHud = maintenant;
  }
  requestAnimationFrame(boucle);
}
requestAnimationFrame(boucle);
