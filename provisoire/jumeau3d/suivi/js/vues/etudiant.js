// Fiche d'un étudiant : ses séances de la période, son taux de présence, les modifications.

import { api } from '../api.js';
import { afficher, dateCourte, echapper, heure, heureBadge, navigationPeriode, periodeDe, pourcent, puce, tuile } from '../ui.js';

export async function vueEtudiant(zone, ctx) {
  const id = ctx.params[0];
  const periode = periodeDe(ctx);
  const e = await api(`/api/etudiant?id=${encodeURIComponent(id)}&du=${periode.du}&au=${periode.au}`);
  ctx.titre(e.nom || `Étudiant ${e.id}`);
  const enseignant = ctx.utilisateur.role === 'enseignant';

  afficher(zone, `
    <a class="retour" href="#/classe/${encodeURIComponent(e.groupe)}?du=${periode.du}&au=${periode.au}">← ${echapper(e.nom_groupe)}</a>
    <div class="fiche-entete">
      <div>
        <h2>${echapper(e.nom || e.id)}</h2>
        <div class="infos"><span>${echapper(e.id)}</span><span>${echapper(e.nom_groupe)}</span>
          ${enseignant ? '<span>seulement vos séances</span>' : ''}</div>
      </div>
    </div>
    <div class="barre-outils">${navigationPeriode(`#/etudiant/${encodeURIComponent(id)}`, periode)}</div>
    <section class="section"><div class="grille tuiles">
      ${tuile(pourcent(e.taux), 'taux de présence')}
      ${tuile(e.absents, 'absences non justifiées', '', e.absents >= 3 ? 'alerte' : '')}
      ${tuile(e.retards, 'retards', '', e.retards >= 3 ? 'alerte' : '')}
      ${tuile(e.justifies, 'absences justifiées')}
    </div></section>
    <section class="section">
      <h2 class="titre-section">Séances</h2>
      ${e.seances.length ? `<div class="tableau-conteneur"><table class="liste">
        <thead><tr><th>Jour</th><th>Horaire</th><th>Cours</th><th>Salle</th><th>Enseignant</th><th>Statut</th><th>Badge</th></tr></thead>
        <tbody>${e.seances.map(s => `<tr class="cliquable" tabindex="0" data-lien="#/seance/${encodeURIComponent(s.seance)}">
          <td class="nowrap">${dateCourte(s.date)}</td><td class="nowrap">${heure(s.debut)}–${heure(s.fin)}</td><td>${echapper(s.matiere)}</td>
          <td class="nowrap">${echapper(s.salle)}</td><td>${echapper(s.enseignant)}</td>
          <td>${puce(s.statut)}${s.corrige ? ' <span class="sous">(corrigé)</span>' : ''}</td><td>${heureBadge(s.badge)}</td>
        </tr>`).join('')}</tbody></table></div>` : '<p class="vide">Aucune séance sur cette période.</p>'}
    </section>
    ${e.corrections.length ? `<section class="section">
      <h2 class="titre-section">Modifications</h2>
      <div class="tableau-conteneur"><table class="liste"><thead><tr><th>Quand</th><th>Avant</th><th>Après</th><th>Motif</th><th>Par</th></tr></thead><tbody>
      ${e.corrections.map(c => `<tr><td>${heureBadge(c.t)}</td><td>${puce(c.avant)}</td><td>${puce(c.apres)}</td><td>${echapper(c.motif || '-')}</td><td>${echapper(c.auteur)}</td></tr>`).join('')}
      </tbody></table></div></section>` : ''}
    <p class="sous">Visible par la direction, la scolarité et les enseignants de la classe.</p>`);

  if (!zone.dataset.ecoute) {
    zone.dataset.ecoute = '1';
    zone.addEventListener('click', ev => {
      const tr = ev.target.closest('tr[data-lien]');
      if (tr && !ev.target.closest('a')) location.hash = tr.dataset.lien;
    });
    zone.addEventListener('keydown', ev => {
      const tr = ev.target.closest('tr[data-lien]');
      if (tr && ev.key === 'Enter') location.hash = tr.dataset.lien;
    });
  }
}
vueEtudiant.rafraichir = 15000;
