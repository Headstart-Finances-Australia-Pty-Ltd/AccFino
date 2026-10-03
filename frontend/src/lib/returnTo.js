// "Go back to where I came from" for set-up screens (e.g. Reconciliation > Open Banking > Settings > Open Banking > back to Reconciliation).
// The return address travels in the URL (?returnTo=/reconciliation?input=openbanking) so it survives a page reload and the pop-up round trip.
// Only addresses inside AccFino are accepted: it must start with a single "/" and may not name another site.
export const safeReturn = v => (typeof v === 'string' && v.startsWith('/') && !v.startsWith('//') && !v.includes('://') && !v.includes('\\') && v.length < 250 ? v : null)

export const withReturn = (path, returnTo) => (safeReturn(returnTo) ? `${path}${path.includes('?') ? '&' : '?'}returnTo=${encodeURIComponent(returnTo)}` : path)

// Add or replace one query parameter of a "/path?query" address.
export function withParam(address, key, value) {
  const [path, query = ''] = address.split('?')
  const q = new URLSearchParams(query); q.set(key, value)
  return `${path}?${q.toString()}`
}

// A short name for the place we will return to ("Reconciliation"), for the button and the message.
export function returnLabel(returnTo) {
  const p = (safeReturn(returnTo) || '').split('?')[0]
  return ({ '/reconciliation': 'Reconciliation', '/accounting': 'Accounting', '/': 'Home' }[p]) || 'where you were'
}

// The Reconciliation page opens on the Open Banking input when the address asks for it (the return trip from Settings).
export const inputModeFromSearch = search => (new URLSearchParams(search || '').get('input') === 'openbanking' ? 'openbanking' : 'csv')
