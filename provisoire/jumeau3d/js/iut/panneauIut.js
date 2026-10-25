// Panneaux de la vue directeur : "qui est où", recherche, détail d'une salle avec l'émargement.
// Ils affichent un état qui vient soit de la simulation du navigateur, soit du serveur
// (même forme dans les deux cas, voir etatLocal() dans simulationIut.js).

import { SALLES } from './batiment.js';
import { COURS, JOURS, heureTexte } from './edt.js';

const SALLE_PAR_ID = Object.fromEntries(SALLES.map(s => [s.id, s]));
const CLASSE = { 'présent': 'present', retard: 'retard', absent: 'absent', attendu: 'attendu', 'à vérifier': 'verifier' };

function echapper(texte) {
  return String(texte).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function pluriel(n, mot) {
  return `${n} ${mot}${n > 1 ? 's' : ''}`;
}

function etatAir(C) {
  if (C >= 1200) return { classe: 'mauvais', texte: 'mauvais' };
  if (C >= 800) return { classe: 'moyen', texte: 'moyen' };
  return { classe: 'bon', texte: 'bon' };
}

function correspond(c, q) {
  const texte = `${c.salle} ${c.matiere} ${c.enseignant} ${c.groupes.join(' ')}`.toLowerCase();
  return q.split(/\s+/).every(mot => texte.includes(mot));
}

export function creerPanneauIut({ surSelection, surJour, surEtage, surMode, surVitesse, surPause }) {
  const $ = id => document.getElementById(id);

  // Boutons du bas
  JOURS.forEach((j, i) => {
    const b = document.createElement('button');
    b.textContent = j.split(' ')[0];
    b.dataset.jour = i;
    b.addEventListener('click', () => surJour(i));
    $('jours').appendChild(b);
  });
  document.querySelectorAll('[data-etage]').forEach(b => b.addEventListener('click', () => {
    surEtage(b.dataset.etage === 'tous' ? 'tous' : Number(b.dataset.etage));
  }));
  document.querySelectorAll('[data-mode]').forEach(b => b.addEventListener('click', () => surMode(b.dataset.mode)));
  $('vitesse-iut').addEventListener('change', e => surVitesse(Number(e.target.value)));
  $('pause-iut').addEventListener('click', () => surPause());
  // pointerdown et pas click : le tableau est redessiné souvent, un clic pourrait tomber entre deux
  $('tableau').addEventListener('pointerdown', e => {
    const ligne = e.target.closest('tr[data-salle]');
    if (ligne) surSelection(ligne.dataset.salle);
  });

  let recherche = '';
  $('recherche').addEventListener('input', e => { recherche = e.target.value.trim().toLowerCase(); });

  // Salles à surligner dans la 3D selon la recherche
  function surlignees(etat) {
    if (!recherche) return new Set();
    return new Set(COURS.filter(c => c.salle && c.jour === etat.jour && c.debut - 10 / 60 <= etat.t && etat.t <= c.fin && correspond(c, recherche)).map(c => c.salle)
      .concat(SALLES.filter(s => s.id.toLowerCase().includes(recherche)).map(s => s.id)));
  }

  function resumeRecherche(etat) {
    if (!recherche) return '';
    const duJour = COURS.filter(c => c.jour === etat.jour && correspond(c, recherche)).sort((a, b) => a.debut - b.debut);
    if (!duJour.length) return 'Rien aujourd\'hui pour cette recherche.';
    const maintenant = duJour.filter(c => c.debut - 10 / 60 <= etat.t && etat.t <= c.fin);
    const suivant = duJour.find(c => c.debut > etat.t);
    const lignes = maintenant.map(c => `Maintenant : ${c.groupes.join(' + ')} en ${c.salle || 'projet tutoré (sans salle)'} (${c.matiere}, ${c.enseignant})`);
    if (suivant) lignes.push(`Ensuite : ${heureTexte(suivant.debut)}, ${suivant.matiere} (${suivant.groupes.join(' + ')}) en ${suivant.salle || 'projet tutoré, sans salle'}`);
    if (!lignes.length) lignes.push('Plus rien aujourd\'hui.');
    return lignes.map(echapper).join('<br>');
  }

  function tableau(etat) {
    const lignes = [];
    const libres = [];
    for (const s of SALLES) {
      const e = etat.salles[s.id];
      if (!e || !e.cours.length) { libres.push(s.id); continue; }
      const c = e.cours;
      const co2 = e.co2 ?? 420;
      const air = etatAir(co2);
      const alerte = e.alertes.some(a => a.niveau === 'detecte');
      lignes.push(`<tr data-salle="${s.id}" class="${alerte ? 'alerte' : ''}">
        <td><b>${s.id}</b>${s.equipee ? ' ●' : ''}</td>
        <td>${c.map(x => `${echapper(x.matiere)}<br><small>${echapper(x.groupes.join(' + '))}</small>`).join('<br>')}</td>
        <td>${echapper(c.map(x => x.enseignant).join(', '))}</td>
        <td>${c.reduce((n, x) => n + x.badges, 0)} / ${c.reduce((n, x) => n + x.emargement.length, 0)}</td>
        <td>${e.personnes}</td>
        <td><span class="air ${air.classe}">${Math.round(co2)}</span></td>
      </tr>`);
    }
    $('tableau').querySelector('tbody').innerHTML = lignes.join('');
    $('libres').textContent = libres.length ? `Salles libres : ${libres.join(', ')}` : 'Aucune salle libre.';
  }

  function detail(etat, id) {
    if (!id || !etat.salles[id]) {
      $('titre-salle').textContent = 'Cliquer sur une salle';
      $('lien-jumeau').hidden = true;
      $('detail').innerHTML = '<p class="sous">Le détail de la salle, le cours en cours, l\'émargement et l\'air apparaissent ici.</p>';
      return;
    }
    const s = SALLE_PAR_ID[id];
    const e = etat.salles[id];
    const co2 = e.co2 ?? 420;
    const air = etatAir(co2);
    $('titre-salle').textContent = `${s.id} — ${s.libelle}`;
    const h = [];
    h.push(`<div class="sous">${s.places} places, ${s.etage === 1 ? '1er' : `${s.etage}e`} étage. ${s.equipee
      ? 'Capteurs à la porte : comptage exact.'
      : 'Pas de capteurs à la porte : comptage par le Wi-Fi (±2 personnes).'}</div>`);
    if (!e.cours.length) {
      const suivant = COURS.filter(c => c.salle === id && c.jour === etat.jour && c.debut > etat.t).sort((a, b) => a.debut - b.debut)[0];
      h.push(`<p>Salle libre.${suivant ? ` Prochain cours à ${heureTexte(suivant.debut)} : ${echapper(suivant.matiere)} (${echapper(suivant.groupes.join(' + '))}).` : ''}</p>`);
    }
    for (const c of e.cours) {
      const compte = k => c.emargement.filter(x => x.statut === k).length;
      const verifier = compte('à vérifier');
      h.push(`<div class="cours-carte">
        <div class="carte-titre">${echapper(c.matiere)} <span class="etiquette-source ${c.reel ? 'reel' : 'simule'}">${c.reel ? 'EDT réel' : 'simulé'}</span></div>
        <div>${echapper(c.groupes.join(' + '))}</div>
        <div class="sous">${heureTexte(c.debut)} – ${heureTexte(c.fin)}, ${echapper(c.enseignant)}</div>
        <div class="ligne"><span>Émargement</span><b>${c.badges} / ${c.emargement.length} badgés</b></div>
        <div class="sous">${compte('présent')} à l'heure, ${compte('retard')} en retard, ${pluriel(compte('absent'), 'absent')}, ${pluriel(compte('attendu'), 'attendu')}${verifier ? `, ${verifier} à vérifier` : ''}</div>
        <div class="puces">${c.emargement.map(x => `<span class="puce ${CLASSE[x.statut] || ''}" title="${echapper(`${x.id} : ${x.statut}`)}">${echapper(x.id.split('-').pop())}</span>`).join('')}</div>
      </div>`);
    }
    h.push(`<h3>Personnes dans la salle</h3>
      <div class="ligne"><span>${e.source === 'porte' ? 'Comptées à la porte' : 'Estimées par le Wi-Fi'}</span><b>${e.personnes}</b></div>`);
    if (e.reel != null) h.push(`<div class="sous">Simulation : il y en a réellement ${e.reel}.</div>`);
    h.push(`<h3>Air</h3>
      <div class="ligne"><span>CO₂</span><b class="air ${air.classe}">${Math.round(co2)} ppm (${air.texte})</b></div>`);
    if (e.airParPersonne != null) {
      h.push(`<div class="ligne"><span>Air neuf par personne (simulé)</span><b>${Math.round(e.airParPersonne)} m³/h</b></div>`);
    }
    if (e.air && e.air.q_decroissance != null) {
      h.push(`<div class="ligne"><span>Débit d'air mesuré (décroissance)</span><b>${e.air.q_decroissance} m³/h</b></div>`);
    }
    if (e.air && e.air.calibration) h.push(`<div class="sous">Recalage de la salle en cours (${e.air.calibration} départs).</div>`);
    if (e.alertes.length) h.push(`<h3>Alertes</h3>${e.alertes.map(a => `<div class="alerte-em ${a.niveau}">${echapper(a.texte)}</div>`).join('')}`);
    $('lien-jumeau').hidden = !s.equipee;
    const html = h.join('');
    if ($('detail').innerHTML !== html) $('detail').innerHTML = html;
  }

  function mettreAJour(etat, vue) {
    $('horloge-iut').textContent = `${etat.titre} — ${heureTexte(etat.t)}`;
    let personnes = 0;
    let occupees = 0;
    let alertes = 0;
    for (const s of SALLES) {
      const e = etat.salles[s.id];
      if (!e) continue;
      personnes += e.personnes;
      if (e.cours.length) occupees += 1;
      alertes += e.alertes.filter(a => a.niveau === 'detecte').length;
    }
    $('resume').innerHTML = `<div><b>${occupees}</b> / ${SALLES.length} salles occupées</div><div><b>${personnes}</b> personnes</div><div class="${alertes ? 'rouge' : ''}"><b>${alertes}</b> alerte${alertes > 1 ? 's' : ''}</div>`;
    $('resultat-recherche').innerHTML = resumeRecherche(etat);
    tableau(etat);
    detail(etat, vue.selection);
    document.querySelectorAll('#jours button').forEach(b => b.classList.toggle('actif', Number(b.dataset.jour) === etat.jour));
    document.querySelectorAll('[data-etage]').forEach(b => b.classList.toggle('actif', String(vue.etage) === b.dataset.etage));
    document.querySelectorAll('[data-mode]').forEach(b => b.classList.toggle('actif', vue.mode === b.dataset.mode));
    document.querySelectorAll('#tableau tr[data-salle]').forEach(tr => tr.classList.toggle('choisie', tr.dataset.salle === vue.selection));
    $('pause-iut').textContent = vue.enPause ? 'Reprendre' : 'Pause';
  }

  return { mettreAJour, surlignees };
}
