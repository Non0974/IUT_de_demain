// Une classe : une ligne par étudiant, une colonne par séance de la période.

import { api } from '../api.js';
import {
  STATUTS, afficher, barreTaux, caseStatut, dateCourte, echapper, heure, navigationPeriode, nomEtudiant,
  periodeDe, pourcent, tuile,
} from '../ui.js';

export async function vueClasse(zone, ctx) {
  const cle = ctx.params[0];
  const periode = periodeDe(ctx);
  const c = await api(`/api/classe?id=${encodeURIComponent(cle)}&du=${periode.du}&au=${periode.au}`);
  ctx.titre(c.nom);

  const tous = c.etudiants.reduce((t, e) => {
    for (const k of ['presents', 'retards', 'absents', 'justifies', 'a_verifier']) t[k] += e[k];
    return t;
  }, { presents: 0, retards: 0, absents: 0, justifies: 0, a_verifier: 0 });
  const decides = tous.presents + tous.retards + tous.absents + tous.justifies + tous.a_verifier;
  const taux = decides ? (tous.presents + tous.retards) / decides : null;

  const entetes = c.seances.map(s => `<th class="seance" scope="col" title="${echapper(`${s.matiere}, ${s.salle}, ${s.enseignant}`)}">
    ${dateCourte(s.date)} ${heure(s.debut)}, ${echapper(s.matiere)}</th>`).join('');
  const lignes = c.etudiants.map(e => `<tr>
    <th scope="row"><a href="#/etudiant/${encodeURIComponent(e.id)}?du=${periode.du}&au=${periode.au}">${nomEtudiant(e.id, e.nom)}</a></th>
    ${c.seances.map(s => {
      const x = e.cases[s.id];
      if (!x) return '<td class="case"></td>';
      const titre = `${e.id}, ${dateCourte(s.date)} ${heure(s.debut)} ${s.matiere} : ${STATUTS[x.statut]?.libelle || x.statut}${x.corrige ? ' (corrigé)' : ''}`;
      return `<td class="case">${caseStatut(x.statut, x.corrige, titre, `#/seance/${encodeURIComponent(s.id)}`)}</td>`;
    }).join('')}
    <td>${barreTaux(e.taux)}</td><td class="nombre">${e.absents}</td><td class="nombre">${e.retards}</td><td class="nombre">${e.justifies}</td>
  </tr>`).join('');

  afficher(zone, `
    <a class="retour" href="#/classes?du=${periode.du}&au=${periode.au}">← Classes</a>
    <div class="barre-outils">
      ${navigationPeriode(`#/classe/${encodeURIComponent(cle)}`, periode)}
      <span class="espace"></span>
      <a class="bouton" href="/api/export?classe=${encodeURIComponent(cle)}&du=${periode.du}&au=${periode.au}">Exporter en CSV</a>
    </div>
    <section class="section"><div class="grille tuiles">
      ${tuile(pourcent(taux), 'taux de présence')}
      ${tuile(c.etudiants.length, 'étudiants')}
      ${tuile(tous.absents, 'absences non justifiées', '', tous.absents ? 'alerte' : '')}
      ${tuile(tous.retards, 'retards')}
      ${tuile(tous.justifies, 'absences justifiées')}
    </div></section>
    ${c.seances.length ? `<section class="section">
      <h2 class="titre-section">Présence par séance</h2>
      <div class="tableau-conteneur"><table class="liste grille-classe">
        <thead><tr><th scope="col">Étudiant</th>${entetes}<th scope="col">Présence</th><th scope="col" class="nombre">Abs.</th><th scope="col" class="nombre">Ret.</th><th scope="col" class="nombre">Just.</th></tr></thead>
        <tbody>${lignes}</tbody>
      </table></div>
      <div class="legende">${Object.values(STATUTS).map(s => `<span><span class="case-statut s-${s.classe}" aria-hidden="true">${s.court}</span>${s.libelle}</span>`).join('')}
        <span><span class="case-statut s-present corrige" aria-hidden="true">P</span>Corrigé à la main</span></div>
    </section>` : '<p class="vide">Aucune séance de cette classe sur la période.</p>'}`);
}
vueClasse.rafraichir = 15000;
