// Liste des classes : taux de présence, absences et retards sur la semaine.

import { api } from '../api.js';
import { afficher, barreTaux, echapper, navigationPeriode, periodeDe } from '../ui.js';

let voirSimules = false;

export async function vueClasses(zone, ctx) {
  const periode = periodeDe(ctx);
  const d = await api(`/api/classes?du=${periode.du}&au=${periode.au}`);
  ctx.titre(ctx.utilisateur.role === 'enseignant' ? 'Mes classes' : 'Classes');

  if (zone.dataset.vue !== `classes-${periode.du}`) {
    zone.dataset.vue = `classes-${periode.du}`;
    zone.innerHTML = `
      <div class="barre-outils">
        ${navigationPeriode('#/classes', periode)}
        <span class="espace"></span>
        <label class="case-a-cocher"><input type="checkbox" id="voir-simules" ${voirSimules ? 'checked' : ''}> Afficher les groupes simulés</label>
      </div>
      <div id="liste-classes"></div>`;
    zone.querySelector('#voir-simules').addEventListener('change', e => { voirSimules = e.target.checked; ctx.redessiner(); });
    zone.addEventListener('click', e => {
      const tr = e.target.closest('tr[data-lien]');
      if (tr) location.hash = tr.dataset.lien;
    });
    zone.addEventListener('keydown', e => {
      const tr = e.target.closest('tr[data-lien]');
      if (tr && e.key === 'Enter') location.hash = tr.dataset.lien;
    });
  }

  const classes = d.classes.filter(c => voirSimules || c.reel);
  const cachees = d.classes.length - classes.length;
  afficher(zone.querySelector('#liste-classes'), classes.length ? `
    <div class="tableau-conteneur"><table class="liste">
      <thead><tr><th>Classe</th><th class="nombre">Étudiants</th><th class="nombre">Séances</th><th>Taux de présence</th>
        <th class="nombre">Absences</th><th class="nombre">Retards</th><th class="nombre">Justifiées</th><th class="nombre">À vérifier</th></tr></thead>
      <tbody>${classes.map(c => `<tr class="cliquable" tabindex="0" data-lien="#/classe/${encodeURIComponent(c.cle)}?du=${periode.du}&au=${periode.au}">
        <td><b>${echapper(c.nom)}</b> ${c.reel ? '' : '<span class="etiquette-simule">(simulée)</span>'}</td>
        <td class="nombre">${c.etudiants}</td><td class="nombre">${c.seances}</td><td>${barreTaux(c.taux)}</td>
        <td class="nombre">${c.absents}</td><td class="nombre">${c.retards}</td><td class="nombre">${c.justifies}</td><td class="nombre">${c.a_verifier}</td>
      </tr>`).join('')}</tbody>
    </table></div>
    ${cachees ? `<p class="sous">${cachees} groupes simulés cachés.</p>` : ''}`
    : '<p class="vide">Aucune séance sur cette période.</p>');
}
vueClasses.rafraichir = 15000;
