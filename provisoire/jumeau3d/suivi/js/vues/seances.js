// Séances d'un jour : émargement de chaque cours, et cours à venir.

import { api } from '../api.js';
import { afficher, ajouterJours, barre, dateLongue, echapper, etatSeance, etiquetteSource, heure, inscritsTexte, legendeBarre } from '../ui.js';

let filtre = '';

function ligne(s) {
  const lien = s.etat === 'à venir' ? '' : `#/seance/${encodeURIComponent(s.id)}`;
  const anomalies = s.anomalies ? `<span class="statut s-verifier" title="badges et passages qui ne collent pas">${s.anomalies}</span>` : '';
  const corrections = s.corrections ? `<span class="sous" title="statuts corrigés à la main">✎ ${s.corrections}</span>` : '';
  return `<tr class="${lien ? 'cliquable' : ''}" ${lien ? `data-lien="${lien}" tabindex="0"` : ''}
    data-texte="${echapper(`${s.salle} ${s.matiere} ${s.enseignant} ${s.groupes.join(' ')}`.toLowerCase())}">
    <td class="nowrap">${heure(s.debut)}–${heure(s.fin)}</td>
    <td class="nowrap"><b>${echapper(s.salle)}</b></td>
    <td>${echapper(s.matiere)} ${etiquetteSource(s.reel)}</td>
    <td>${echapper(s.groupes.join(' + '))}</td>
    <td>${echapper(s.enseignant)}</td>
    <td><div class="cellule-barre">${s.etat === 'à venir' ? `<span class="sous">${s.inscrits} inscrits</span>` : `${barre(s)}<span>${inscritsTexte(s)}</span>`}</div></td>
    <td>${anomalies} ${corrections}</td>
    <td>${etatSeance(s.etat)}</td>
  </tr>`;
}

export async function vueSeances(zone, ctx) {
  const jour = ctx.query.get('date') || ctx.info()?.date;
  const d = await api(`/api/seances?date=${encodeURIComponent(jour)}`);
  ctx.titre('Séances');

  // Squelette dessiné une fois : la barre d'outils garde la saisie pendant les rafraîchissements
  if (zone.dataset.vue !== `seances-${jour}`) {
    zone.dataset.vue = `seances-${jour}`;
    zone.innerHTML = `
      <div class="barre-outils">
        <a class="bouton" href="#/seances?date=${ajouterJours(jour, -1)}" aria-label="Jour précédent">◀</a>
        <input type="date" id="choix-date" value="${jour}" aria-label="Jour">
        <a class="bouton" href="#/seances?date=${ajouterJours(jour, 1)}" aria-label="Jour suivant">▶</a>
        <a class="bouton discret" href="#/seances">Aujourd'hui</a>
        <span class="espace"></span>
        <input type="search" id="filtre" placeholder="Salle, classe, enseignant…" aria-label="Filtrer les séances" value="${echapper(filtre)}">
      </div>
      <h2 class="titre-section">${dateLongue(jour)} <span class="sous" id="resume-jour"></span></h2>
      <div id="liste-seances"></div>`;
    zone.querySelector('#choix-date').addEventListener('change', e => { if (e.target.value) location.hash = `#/seances?date=${e.target.value}`; });
    zone.querySelector('#filtre').addEventListener('input', e => { filtre = e.target.value.trim().toLowerCase(); appliquerFiltre(zone); });
    zone.addEventListener('click', e => {
      const tr = e.target.closest('tr[data-lien]');
      if (tr) location.hash = tr.dataset.lien;
    });
    zone.addEventListener('keydown', e => {
      const tr = e.target.closest('tr[data-lien]');
      if (tr && e.key === 'Enter') location.hash = tr.dataset.lien;
    });
  }
  const finies = d.seances.filter(s => s.etat === 'terminée').length;
  const enCours = d.seances.filter(s => s.etat === 'en cours').length;
  zone.querySelector('#resume-jour').textContent = `${d.seances.length} séances · ${enCours} en cours · ${finies} terminées`;
  afficher(zone.querySelector('#liste-seances'), d.seances.length ? `
    <div class="tableau-conteneur"><table class="liste">
      <thead><tr><th>Horaire</th><th>Salle</th><th>Cours</th><th>Classe</th><th>Enseignant</th><th>Émargement</th><th>Anomalies</th><th>État</th></tr></thead>
      <tbody>${d.seances.map(ligne).join('')}</tbody>
    </table></div>${legendeBarre()}` : '<p class="vide">Aucune séance ce jour-là.</p>');
  appliquerFiltre(zone);
}
vueSeances.rafraichir = 10000;

function appliquerFiltre(zone) {
  zone.querySelectorAll('tr[data-texte]').forEach(tr => { tr.hidden = filtre && !filtre.split(/\s+/).every(m => tr.dataset.texte.includes(m)); });
}
