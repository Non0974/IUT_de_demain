// Jumeau prédictif : ce qui va se passer dans les 2 prochaines heures, ce que le jumeau décide pour la
// ventilation, et les changements de salle qu'il propose.

import { api } from '../api.js';
import { afficher, echapper, heure, pourcent, tuile } from '../ui.js';

const VITESSES = { arret: 'Arrêt', petite: 'Petite vitesse', grande: 'Grande vitesse' };

// ---------- courbes (SVG) ----------

function echelles(h0, h1, cMax, largeur, hauteur, marge) {
  const yMax = Math.max(1400, Math.ceil((cMax + 150) / 200) * 200);
  return {
    x: h => marge.g + ((h - h0) / (h1 - h0)) * (largeur - marge.g - marge.d),
    y: c => marge.h + (1 - (Math.min(c, yMax) - 400) / (yMax - 400)) * (hauteur - marge.h - marge.b),
    yMax,
  };
}

function chemin(points, x, y) {
  return points.map((p, i) => `${i ? 'L' : 'M'}${x(p.heure).toFixed(1)},${y(p.co2).toFixed(1)}`).join('');
}

// Grande courbe de la salle de l'automate : mesuré (trait plein), prévu (pointillés), plan de ventilation
function grandeCourbe(passe, prevu, plan, maintenant) {
  const L = 760;
  const H = 250;
  const marge = { g: 44, d: 12, h: 12, b: 58 };
  const h0 = Math.max(passe.length ? passe[0].heure : maintenant - 2, maintenant - 4);
  const h1 = maintenant + 2;
  const vus = passe.filter(p => p.heure >= h0);
  const cMax = Math.max(...vus.map(p => p.co2), ...prevu.map(p => p.co2), 0);
  const { x, y, yMax } = echelles(h0, h1, cMax, L, H, marge);
  const graduations = [];
  for (let c = 400; c <= yMax; c += 200) {
    graduations.push(`<line x1="${marge.g}" x2="${L - marge.d}" y1="${y(c)}" y2="${y(c)}" class="grille-svg"/>
      <text x="${marge.g - 6}" y="${y(c) + 4}" class="axe-svg" text-anchor="end">${c}</text>`);
  }
  const heures = [];
  for (let h = Math.ceil(h0); h <= h1; h++) {
    heures.push(`<text x="${x(h)}" y="${H - marge.b + 16}" class="axe-svg" text-anchor="middle">${h}h</text>`);
  }
  const seuils = [[800, 'seuil-svg'], [1200, 'seuil-svg fort']].map(([c, cl]) =>
    `<line x1="${marge.g}" x2="${L - marge.d}" y1="${y(c)}" y2="${y(c)}" class="${cl}"/>
     <text x="${L - marge.d - 4}" y="${y(c) - 4}" class="axe-svg" text-anchor="end">${c} ppm</text>`).join('');
  const bandeY = H - marge.b + 26;
  const bande = plan.map(s => `<rect x="${x(Math.max(s.debut, h0))}" y="${bandeY}" width="${Math.max(1, x(Math.min(s.fin, h1)) - x(Math.max(s.debut, h0)) - 2)}"
      height="14" rx="3" class="vitesse-${s.niveau}"><title>${heure(s.debut)}–${heure(s.fin)} : ${VITESSES[s.niveau]}</title></rect>`).join('');
  const donnees = JSON.stringify([...vus.map(p => ({ h: p.heure, c: p.co2, t: 'mesuré' })), ...prevu.map(p => ({ h: p.heure, c: p.co2, t: 'prévu' }))]);
  return `<svg class="courbe-co2" viewBox="0 0 ${L} ${H}" role="img" aria-label="CO2 mesuré et prévu, et vitesse de ventilation prévue"
      data-points='${echapper(donnees)}' data-h0="${h0}" data-h1="${h1}" data-marge="${marge.g},${marge.d}" data-largeur="${L}">
    ${graduations.join('')}${seuils}${heures.join('')}
    <line x1="${x(maintenant)}" x2="${x(maintenant)}" y1="${marge.h}" y2="${H - marge.b}" class="maintenant-svg"/>
    <text x="${x(maintenant) + 4}" y="${marge.h + 10}" class="axe-svg">maintenant</text>
    <path d="${chemin(vus, x, y)}" class="ligne-mesure"/>
    <path d="${chemin(prevu, x, y)}" class="ligne-prevue"/>
    <text x="${marge.g}" y="${bandeY + 11}" class="axe-svg" text-anchor="end" dx="-6">ventil.</text>
    ${bande}
    <line class="curseur-svg" y1="${marge.h}" y2="${H - marge.b}" x1="-10" x2="-10"/>
  </svg>`;
}

// Petite courbe d'une salle : les 2 prochaines heures
function petiteCourbe(serie) {
  const L = 170;
  const H = 40;
  const h0 = serie[0].heure;
  const h1 = serie[serie.length - 1].heure;
  const cMax = Math.max(...serie.map(p => p.co2));
  const { x, y } = echelles(h0, h1, cMax, L, H, { g: 2, d: 2, h: 3, b: 3 });
  const seuil = y(1200);
  return `<svg viewBox="0 0 ${L} ${H}" class="petite-courbe" aria-hidden="true">
    ${seuil > 3 ? `<line x1="2" x2="${L - 2}" y1="${seuil}" y2="${seuil}" class="seuil-svg fort"/>` : ''}
    <path d="${chemin(serie, x, y)}" class="ligne-prevue pleine"/></svg>`;
}

function classePpm(c) {
  return c >= 1200 ? 'ppm-mauvais' : c >= 800 ? 'ppm-moyen' : 'ppm-bon';
}

// ---------- page ----------

export async function vueAnticipation(zone, ctx) {
  const [d, passe] = await Promise.all([api('/api/previsions'), api(`/api/historique?salle=${encodeURIComponent('SAR 200')}`)]);
  ctx.titre('Anticipation');
  const cmd = d.commande;
  const b = cmd.bilan;
  const auto = d.salles.find(s => s.salle === cmd.salle);

  if (!zone.dataset.ecoute) {
    zone.dataset.ecoute = '1';
    zone.addEventListener('click', async e => {
      const bouton = e.target.closest('[data-action]');
      if (!bouton) return;
      bouton.disabled = true;
      try {
        if (bouton.dataset.action === 'strategie') {
          await api('/api/commande', { strategie: bouton.dataset.valeur });
        } else {
          await api('/api/proposition', { action: bouton.dataset.action, cours: bouton.dataset.cours, salle: bouton.dataset.salle });
        }
      } finally {
        await ctx.redessiner();
      }
    });
    // Curseur sur la grande courbe : la valeur sous la souris
    zone.addEventListener('mousemove', e => {
      const svg = e.target.closest('svg.courbe-co2');
      const bulle = zone.querySelector('#bulle');
      if (!svg || !bulle) return;
      const r = svg.getBoundingClientRect();
      const [mg, md] = svg.dataset.marge.split(',').map(Number);
      const L = Number(svg.dataset.largeur);
      const xs = (e.clientX - r.left) * (L / r.width);
      const h0 = Number(svg.dataset.h0);
      const h1 = Number(svg.dataset.h1);
      const h = h0 + ((xs - mg) / (L - mg - md)) * (h1 - h0);
      const points = JSON.parse(svg.dataset.points);
      const p = points.reduce((a, q) => (Math.abs(q.h - h) < Math.abs(a.h - h) ? q : a), points[0]);
      if (!p) return;
      const curseur = svg.querySelector('.curseur-svg');
      const xp = mg + ((p.h - h0) / (h1 - h0)) * (L - mg - md);
      curseur.setAttribute('x1', xp);
      curseur.setAttribute('x2', xp);
      bulle.hidden = false;
      bulle.textContent = `${heure(p.h)} · ${Math.round(p.c)} ppm (${p.t})`;
      bulle.style.left = `${(xp / L) * r.width}px`;
    });
    zone.addEventListener('mouseleave', () => { const bulle = zone.querySelector('#bulle'); if (bulle) bulle.hidden = true; }, true);
  }

  const tuiles = [
    tuile(b && b.economie != null ? `−${pourcent(b.economie)}` : '—', 'énergie de ventilation', b ? `${b.energie_kwh.jumeau} kWh au lieu de ${b.energie_kwh.regle} (règle simple), aujourd'hui` : '', 'bon'),
    tuile(b ? `${b.minutes_au_dessus_1000.jumeau} min` : '—', 'au-dessus de 1000 ppm', b ? `contre ${b.minutes_au_dessus_1000.regle} min avec la règle simple` : ''),
    tuile(d.precision['30 min'].erreur_moyenne != null ? `± ${d.precision['30 min'].erreur_moyenne} ppm` : '—', 'erreur des prévisions à 30 min',
      d.precision['60 min'].erreur_moyenne != null ? `± ${d.precision['60 min'].erreur_moyenne} ppm à 1 h (${d.precision['60 min'].n} vérifications)` : 'en cours de mesure'),
    tuile(d.propositions.length, `proposition${d.propositions.length > 1 ? 's' : ''} de salle`, `${d.changements.length} changement${d.changements.length > 1 ? 's' : ''} accepté${d.changements.length > 1 ? 's' : ''} aujourd'hui`),
  ];

  const propositions = d.propositions.length ? d.propositions.map(p => `<div class="carte proposition">
      <div class="entete"><b>${echapper(p.matiere)}</b> <span class="sous">${echapper(p.groupes.join(' + '))} · ${echapper(p.enseignant)} · ${heure(p.debut)}–${heure(p.fin)} · ${p.personnes} personnes attendues</span></div>
      <div class="deplacement">
        <div><span class="sous">Salle prévue</span><b>${echapper(p.salle)}</b><span class="${classePpm(p.pic)}">${p.pic} ppm prévus</span></div>
        <span class="fleche" aria-hidden="true">→</span>
        <div><span class="sous">Salle proposée</span><b>${echapper(p.proposee)}</b><span class="${classePpm(p.pic_propose)}">${p.pic_propose} ppm prévus</span></div>
      </div>
      <div class="actions">
        <button type="button" class="bouton principal-bouton" data-action="accepter" data-cours="${echapper(p.cours)}" data-salle="${echapper(p.proposee)}">Accepter le changement</button>
        <button type="button" class="bouton" data-action="ignorer" data-cours="${echapper(p.cours)}">Ignorer</button>
      </div>
    </div>`).join('') : '<p class="vide">Aucune proposition : l\'air des prochains cours devrait rester correct.</p>';
  const changements = d.changements.length ? `<ul class="liste-simple">${d.changements.map(c =>
    `<li>${echapper(c.cours)} : ${echapper(c.salle_avant)} → <b>${echapper(c.salle_apres)}</b> <span class="sous">par ${echapper(c.auteur)}</span></li>`).join('')}</ul>` : '';

  const plan = cmd.plan.length ? cmd.plan : [];
  const prochain = plan.find(s => s.niveau !== cmd.niveau);
  const salles = d.salles.slice().sort((a, c) => (c.pic?.co2 || 0) - (a.pic?.co2 || 0)).map(s => `<tr>
      <td class="nowrap"><b>${echapper(s.salle)}</b></td>
      <td class="nombre"><span class="${classePpm(s.maintenant)}">${s.maintenant}</span></td>
      <td>${s.pic ? `<span class="${classePpm(s.pic.co2)}">${s.pic.co2} ppm</span> <span class="sous">vers ${heure(s.pic.heure)}</span>` : '—'}</td>
      <td>${s.au_dessus_1200 != null ? `<span class="ppm-mauvais">dès ${heure(s.au_dessus_1200)}</span>` : '<span class="sous">non</span>'}</td>
      <td>${petiteCourbe(s.serie)}</td>
      <td class="sous">${{ appris: 'débit mesuré', automate: 'piloté par le jumeau', 'a priori': 'débit supposé' }[s.source_debit]}</td>
    </tr>`).join('');

  afficher(zone, `
    <section class="section"><div class="grille tuiles">${tuiles.join('')}</div></section>
    <section class="section">
      <h2 class="titre-section">Propositions de changement de salle <span class="sous">le jumeau simule chaque cours dans les salles libres</span></h2>
      <div class="grille propositions">${propositions}</div>${changements}
    </section>
    <section class="section">
      <h2 class="titre-section">Ventilation de ${echapper(cmd.salle)} décidée par le jumeau</h2>
      <div class="carte">
        <div class="barre-outils">
          <span>Maintenant : <b>${VITESSES[cmd.niveau] || '—'}</b>${prochain ? ` · ${VITESSES[prochain.niveau].toLowerCase()} à ${heure(prochain.debut)}` : ''}</span>
          <span class="espace"></span>
          <span class="sous">Stratégie :</span>
          <button type="button" class="bouton petit ${cmd.strategie === 'predictive' ? 'principal-bouton' : ''}" data-action="strategie" data-valeur="predictive">Jumeau prédictif</button>
          <button type="button" class="bouton petit ${cmd.strategie === 'reactive' ? 'principal-bouton' : ''}" data-action="strategie" data-valeur="reactive">Règle simple</button>
        </div>
        <div class="conteneur-courbe">${grandeCourbe(passe.map(p => ({ heure: p.heure, co2: p.C })), auto ? auto.serie : [], plan, d.heure)}
          <div id="bulle" class="bulle" hidden></div></div>
        <div class="legende">
          <span><i class="trait-plein"></i>CO₂ mesuré</span><span><i class="trait-pointille"></i>CO₂ prévu</span>
          <span><i class="vitesse-arret"></i>Arrêt</span><span><i class="vitesse-petite"></i>Petite vitesse</span><span><i class="vitesse-grande"></i>Grande vitesse</span>
        </div>
        <p class="sous">Chaque minute, le jumeau essaie les vitesses possibles, simule les 90 minutes suivantes avec les cours prévus et garde la moins coûteuse (énergie + air). Il ventile avant l'arrivée des étudiants et garde la ventilation après chaque cours, le temps de mesurer la décroissance du CO₂.</p>
      </div>
    </section>
    <section class="section">
      <h2 class="titre-section">Prévision de chaque salle <span class="sous">2 prochaines heures · taux de présence appris : ${pourcent(d.taux_presence)}</span></h2>
      <div class="tableau-conteneur"><table class="liste">
        <thead><tr><th>Salle</th><th class="nombre">CO₂ maintenant</th><th>Pic prévu</th><th>Au-dessus de 1200 ppm</th><th>2 prochaines heures</th><th>Débit</th></tr></thead>
        <tbody>${salles}</tbody>
      </table></div>
      <p class="sous">Les prévisions en simulation sont très bonnes parce que le simulateur et le jumeau partagent la même physique : en vrai, l'erreur sera plus grande, et c'est elle que la tuile « erreur des prévisions » mesure.</p>
    </section>`);
}
vueAnticipation.rafraichir = 10000;
