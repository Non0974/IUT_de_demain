// Tableau de bord : ce qui se passe maintenant dans l'IUT (ou dans les cours de l'enseignant).

import { api } from '../api.js';
import { afficher, echapper, etiquetteSource, heure, inscritsTexte, pourcent, ppm, tuile } from '../ui.js';

function ligneSeance(s) {
  const source = s.source === 'porte' ? 'porte' : 'Wi-Fi';
  return `<tr class="cliquable" tabindex="0" data-lien="#/seance/${encodeURIComponent(s.id)}">
    <td class="nowrap"><b>${echapper(s.salle)}</b></td>
    <td>${echapper(s.matiere)} ${etiquetteSource(s.reel)}</td>
    <td>${echapper(s.groupes.join(' + '))}</td>
    <td>${echapper(s.enseignant)}</td>
    <td class="nowrap">${heure(s.debut)}–${heure(s.fin)}</td>
    <td class="nombre">${inscritsTexte(s)}</td>
    <td class="nombre">${s.absents}</td>
    <td class="nombre">${s.personnes} <span class="sous">(${source})</span></td>
    <td class="nowrap">${ppm(s.co2)}</td>
  </tr>`;
}

function alerte(a) {
  const lien = a.seance ? `#/seance/${encodeURIComponent(a.seance)}` : a.etudiant ? `#/etudiant/${encodeURIComponent(a.etudiant)}`
    : a.ticket ? '#/tickets' : '#/';
  const quoi = a.salle ? echapper(a.salle) : a.etudiant ? echapper(a.nom || a.etudiant) : '';
  return `<a class="alerte ${a.niveau}" href="${lien}">${quoi ? `<b>${quoi}</b> : ` : ''}${echapper(a.texte)}</a>`;
}

export async function vueTableau(zone, ctx) {
  const d = await api('/api/tableau');
  const enseignant = ctx.utilisateur.role === 'enseignant';
  ctx.titre(enseignant ? 'Mes cours aujourd\'hui' : 'Tableau de bord');
  if (!zone.dataset.ecoute) {
    zone.dataset.ecoute = '1';
    zone.addEventListener('click', e => {
      const tr = e.target.closest('tr[data-lien]');
      if (tr) location.hash = tr.dataset.lien;
    });
    zone.addEventListener('keydown', e => {
      const tr = e.target.closest('tr[data-lien]');
      if (tr && e.key === 'Enter') location.hash = tr.dataset.lien;
    });
  }
  const c = d.chiffres;
  const tuiles = [
    tuile(c.seances_en_cours, 'séances en cours', `${c.seances_terminees} terminées sur ${c.seances_du_jour}`),
    tuile(c.presents_maintenant, 'présents', c.attendus_maintenant ? `${c.attendus_maintenant} pas encore arrivés` : '', 'bon'),
    tuile(c.absents_maintenant, `absent${c.absents_maintenant > 1 ? 's' : ''}`, '', c.absents_maintenant ? 'alerte' : ''),
    tuile(pourcent(c.taux_jour), 'de présence aujourd\'hui'),
    tuile(c.alertes, `alerte${c.alertes > 1 ? 's' : ''}`, '', c.alertes ? 'alerte' : ''),
  ];
  const enCours = d.en_cours.length
    ? `<div class="tableau-conteneur"><table class="liste">
      <thead><tr><th>Salle</th><th>Cours</th><th>Classe</th><th>Enseignant</th><th>Horaire</th>
        <th class="nombre">Présents</th><th class="nombre">Absents</th><th class="nombre">Dans la salle</th><th>CO₂</th></tr></thead>
      <tbody>${d.en_cours.map(ligneSeance).join('')}</tbody></table></div>`
    : '<p class="vide">Pas de cours en ce moment.</p>';
  const aVenir = d.a_venir.length
    ? `<div class="tableau-conteneur"><table class="liste"><thead><tr><th>Horaire</th><th>Salle</th><th>Cours</th><th>Classe</th></tr></thead><tbody>
      ${d.a_venir.map(s => `<tr><td class="nowrap">${heure(s.debut)}–${heure(s.fin)}</td><td class="nowrap">${echapper(s.salle)}</td>
        <td>${echapper(s.matiere)}<div class="sous">${echapper(s.enseignant)}</div></td><td>${echapper(s.groupes.join(' + '))}</td></tr>`).join('')}
      </tbody></table></div>`
    : '<p class="vide">Plus de cours prévu aujourd\'hui.</p>';
  const alertes = d.alertes.length ? `<div class="alertes">${d.alertes.map(alerte).join('')}</div>` : '<p class="vide">Pas d\'alerte.</p>';

  afficher(zone, `
    <section class="section"><div class="grille tuiles">${tuiles.join('')}</div></section>
    <section class="section">
      <h2 class="titre-section">En ce moment</h2>
      ${enCours}
    </section>
    <div class="deux-colonnes">
      <section class="section"><h2 class="titre-section">Cours à venir</h2>${aVenir}</section>
      <section class="section"><h2 class="titre-section">Alertes</h2>${alertes}</section>
    </div>`);
}
vueTableau.rafraichir = 5000;
