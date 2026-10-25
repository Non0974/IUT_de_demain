// Panneaux d'information, boutons de pannes, émargement et courbe du CO2.

import { coursEnCours } from './simulation.js';
import { debitAttendu } from './estimateur.js';
import { heureCourte } from './emargement.js';

const MIN_LEGAL = 25; // m3/h d'air neuf par occupant (code du travail, R4222-6)

function heure(t) {
  const h = Math.floor(t);
  const m = Math.floor((t - h) * 60);
  return `${String(h).padStart(2, '0')} h ${String(m).padStart(2, '0')}`;
}

function couleurPpm(ppm) {
  if (ppm < 800) return 'var(--vert)';
  if (ppm < 1200) return 'var(--orange)';
  return 'var(--rouge)';
}

const PANNES = [
  ['ventilation', 'Ventilateur en panne'],
  ['fenetre', 'Ouvrir la fenêtre'],
  ['derive', 'Décaler le capteur de CO₂'],
  ['comptage', 'Fausser le comptage'],
];

const FRAUDES = [
  ['badgePrete', "Badger aussi la carte d'un absent"],
  ['sansBadge', 'Entrer sans badger'],
];

export function creerHud({ surPanne, surVitesse, surPause, surReinitialiser, surTelecharger }) {
  const $ = id => document.getElementById(id);

  // Boutons de pannes et de fraudes (une fraude par cours tant que le bouton est actif)
  for (const [zone, liste] of [['pannes', PANNES], ['fraudes', FRAUDES]]) {
    for (const [cle, texte] of liste) {
      const b = document.createElement('button');
      b.className = 'bouton-panne';
      b.dataset.panne = cle;
      b.textContent = texte;
      b.addEventListener('click', () => surPanne(cle));
      $(zone).appendChild(b);
    }
  }
  $('telecharger').addEventListener('click', () => surTelecharger());
  $('vitesse').addEventListener('change', e => surVitesse(Number(e.target.value)));
  $('pause').addEventListener('click', () => surPause());
  $('reinitialiser').addEventListener('click', () => surReinitialiser());

  // Courbe
  const canvas = $('courbe');
  const ctx = canvas.getContext('2d');

  function dessinerCourbe(historique, debutJour, finJour) {
    const w = canvas.width = canvas.clientWidth * devicePixelRatio;
    const h = canvas.height = canvas.clientHeight * devicePixelRatio;
    ctx.clearRect(0, 0, w, h);
    const x = t => ((t - debutJour) / (finJour - debutJour)) * w;
    const yC = c => h - ((Math.min(c, 2500) - 300) / 2200) * h;
    // Seuil 800 ppm
    ctx.strokeStyle = 'rgba(192,57,43,0.6)';
    ctx.setLineDash([6 * devicePixelRatio, 4 * devicePixelRatio]);
    ctx.beginPath();
    ctx.moveTo(0, yC(800));
    ctx.lineTo(w, yC(800));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(192,57,43,0.8)';
    ctx.font = `${11 * devicePixelRatio}px system-ui`;
    ctx.fillText('800 ppm', 4, yC(800) - 4);
    // Occupation (aire grise)
    ctx.fillStyle = 'rgba(80,90,110,0.18)';
    for (const p of historique) {
      const hh = (p.N / 50) * h;
      ctx.fillRect(x(p.t), h - hh, Math.max(1, w / 600), hh);
    }
    // CO2 mesuré
    ctx.strokeStyle = '#143c78';
    ctx.lineWidth = 2 * devicePixelRatio;
    ctx.beginPath();
    historique.forEach((p, i) => (i ? ctx.lineTo(x(p.t), yC(p.C)) : ctx.moveTo(x(p.t), yC(p.C))));
    ctx.stroke();
    // Heures
    ctx.fillStyle = '#5b6370';
    for (let t = Math.ceil(debutJour); t <= finJour; t += 2) {
      ctx.fillText(`${t} h`, x(t) + 2, h - 4);
    }
  }

  // Émargement
  const grille = $('em-grille');
  const cases = [];
  for (let i = 0; i < 30; i++) {
    const c = document.createElement('span');
    c.className = 'case';
    grille.appendChild(c);
    cases.push(c);
  }

  function afficherEmargement(bilan) {
    const zone = $('em-alertes');
    zone.innerHTML = '';
    if (!bilan.cours) {
      $('em-compte').textContent = '—';
      cases.forEach(c => { c.className = 'case'; c.title = ''; });
      const d = bilan.dernier;
      $('em-dernier').textContent = d
        ? `Dernier cours (${heureCourte(d.debut)} – ${heureCourte(d.fin)}) : ${d.presents} présents, ${d.aVerifier + d.sansBadge} anomalie${d.aVerifier + d.sansBadge > 1 ? 's' : ''}.`
        : 'Pas de cours en ce moment.';
      return;
    }
    $('em-libelle').textContent = bilan.libelle || 'Badges / passages';
    $('em-compte').textContent = `${bilan.badges} / ${bilan.passages}`;
    $('em-compte').style.color = bilan.alertes.some(a => a.niveau === 'detecte') ? 'var(--rouge)' : '';
    const libelles = { present: 'présent', verifier: 'à vérifier', absent: 'absent' };
    bilan.statuts.forEach((e, i) => {
      cases[i].className = `case ${e.statut}`;
      cases[i].title = `${e.nom} : ${libelles[e.statut]}`;
    });
    for (const a of bilan.alertes) {
      const div = document.createElement('div');
      div.className = `alerte-em ${a.niveau}`;
      div.textContent = a.texte;
      zone.appendChild(div);
    }
    $('em-dernier').textContent = bilan.alertes.length ? '' : (bilan.texteOk || 'Chaque badge correspond à un passage.');
  }

  function mettreAJour(sim, est, diag, bilan, historique, vitesse, enPause, debutJour, finJour) {
    // Avec le serveur, le cours vient de l'emploi du temps du serveur
    const cours = sim.coursServeur !== undefined ? sim.coursServeur : coursEnCours(sim.t);
    $('horloge').textContent = `${sim.titreJour || `Jour ${sim.jour}`} — ${heure(sim.t)}`;
    $('cours').textContent = cours
      ? `Cours de ${heure(cours[0])} à ${heure(cours[1])} (${cours[2]} étudiants prévus)`
      : 'Pas de cours en ce moment';

    $('personnes').textContent = sim.N_mesure;
    $('personnes-reel').textContent = sim.pannes.comptage && sim.N_reel !== sim.N_mesure ? `(réellement ${sim.N_reel})` : '';

    const Caff = sim.mesures.C - est.correction;
    $('co2').textContent = `${Math.round(Caff)} ppm`;
    $('co2').style.color = couleurPpm(Caff);
    $('correction').textContent = est.correction ? `capteur recalé de ${Math.round(est.correction)} ppm` : '';

    const niveaux = { arret: 'arrêt', petite: 'petite vitesse', grande: 'grande vitesse' };
    $('commande').textContent = `${niveaux[sim.niveau]} — ${Math.round(debitAttendu(sim.niveau))} m³/h attendus`;
    $('q-occ').textContent = est.occ ? `${Math.round(est.occ.Q)} m³/h` : '—';
    $('q-dec').textContent = est.dec ? `${Math.round(est.dec.Q)} m³/h` : '—';

    // Air neuf par personne
    const barre = $('barre-air');
    if (est.occ && sim.N_mesure > 0) {
      const parPers = est.occ.Q / sim.N_mesure;
      $('air-personne').textContent = `${Math.round(parPers)} m³/h par personne`;
      const pct = Math.min(100, (parPers / (MIN_LEGAL * 2)) * 100);
      barre.style.width = `${pct}%`;
      barre.style.background = parPers >= MIN_LEGAL ? 'var(--vert)' : 'var(--rouge)';
    } else {
      $('air-personne').textContent = 'salle vide';
      barre.style.width = '0%';
    }

    // Diagnostic
    const zone = $('diagnostic');
    zone.innerHTML = '';
    const libelles = { attente: 'en attente', ok: 'normal', suspect: 'à confirmer', detecte: 'détecté' };
    for (const cle of Object.keys(diag)) {
      const c = diag[cle];
      const carte = document.createElement('div');
      carte.className = `carte ${c.etat}`;
      carte.innerHTML = `<div class="carte-titre"><span class="pastille"></span>${c.titre}<span class="etat">${libelles[c.etat]}</span></div><div class="carte-texte"></div>`;
      carte.querySelector('.carte-texte').textContent = c.message;
      zone.appendChild(carte);
    }

    afficherEmargement(bilan);

    document.querySelectorAll('.bouton-panne').forEach(b => {
      b.classList.toggle('actif', sim.pannes[b.dataset.panne]);
    });
    $('pause').textContent = enPause ? 'Reprendre' : 'Pause';
    if (vitesse) $('vitesse').value = String(vitesse);

    dessinerCourbe(historique, debutJour, finJour);
  }

  return { mettreAJour };
}

