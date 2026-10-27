// Export d'une semaine CELCAT pour outils/celcat.py.
//
// 1. Ouvrir son emploi du temps sur https://celcat-calendar.cyu.fr (connecté), vue Semaine.
// 2. F12 > Console, coller ce fichier, Entrée. Le navigateur télécharge celcat_AAAA-MM-JJ.json.
// 3. python outils/celcat.py celcat_AAAA-MM-JJ.json --lundi AAAA-MM-JJ
//
// Avec un compte étudiant, CELCAT ne donne que son propre emploi du temps (testé).
// Avec un compte qui voit les salles (direction, scolarité), mettre TOUTES_LES_SALLES à true : le script
// cherche les salles « SAR » et exporte chacune (pas testé : nos comptes étudiants n'y ont pas accès).

(async () => {
  const TOUTES_LES_SALLES = false;
  const page = new URL(location.href);
  const jour = page.searchParams.get('dt') || new Date().toISOString().slice(0, 10);
  const lundi = new Date(jour);
  lundi.setDate(lundi.getDate() - ((lundi.getDay() + 6) % 7));
  const debut = lundi.toISOString().slice(0, 10);
  const fin = new Date(lundi.getTime() + 6 * 86400000).toISOString().slice(0, 10);

  async function semaine(type, id) {
    const corps = new URLSearchParams([['start', debut], ['end', fin], ['resType', type], ['calView', 'agendaWeek'],
      ['federationIds[]', id], ['colourScheme', '3']]);
    const r = await fetch('/Home/GetCalendarData', { method: 'POST', body: corps,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest' } });
    return r.json();
  }

  let evenements = [];
  if (TOUTES_LES_SALLES) {
    const r = await fetch('/Home/ReadResourceListItems?myResources=false&searchTerm=SAR&pageSize=200&pageNumber=1&resType=102',
      { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    const salles = (await r.json()).results || [];
    for (const s of salles) evenements = evenements.concat(await semaine('102', s.id));
    console.log(`${salles.length} salles exportées`);
  } else {
    evenements = await semaine(page.searchParams.get('et') === 'room' ? '102' : '104', page.searchParams.get('fid0'));
  }
  // On ne garde que ce dont celcat.py a besoin
  const garde = evenements.map(e => ({ start: e.start, end: e.end, allDay: e.allDay, eventCategory: e.eventCategory,
    sites: e.sites, modules: e.modules, description: e.description }));
  const lien = document.createElement('a');
  lien.href = URL.createObjectURL(new Blob([JSON.stringify(garde)], { type: 'application/json' }));
  lien.download = `celcat_${debut}.json`;
  lien.click();
  console.log(`${garde.length} cours exportés, semaine du ${debut}`);
})();
