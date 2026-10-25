// Lit un fichier JSON de données (dans le navigateur avec fetch, dans Node pour les tests avec fs).
export async function chargerJson(url) {
  if (url.protocol === 'file:') {
    const fs = await import('fs');
    return JSON.parse(fs.readFileSync(url, 'utf8'));
  }
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Impossible de lire ${url} (${r.status})`);
  return r.json();
}
