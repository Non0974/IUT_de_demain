// Appels au serveur CampusTwin. Si la session a expiré, on renvoie vers la page de connexion.

export class ErreurApi extends Error {
  constructor(message, code) {
    super(message);
    this.code = code;
  }
}

export function allerConnexion() {
  const ici = location.pathname + location.search + location.hash;
  location.href = `/suivi/connexion.html?retour=${encodeURIComponent(ici)}`;
}

export async function api(chemin, corps) {
  const options = corps === undefined
    ? { cache: 'no-store' }
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corps) };
  const r = await fetch(chemin, options);
  if (r.status === 401) {
    allerConnexion();
    throw new ErreurApi('Connexion nécessaire.', 401);
  }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new ErreurApi(d.erreur || `Erreur ${r.status}`, r.status);
  return d;
}
