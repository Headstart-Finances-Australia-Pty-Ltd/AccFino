export const num = v => { const n = Number(v); return Number.isFinite(n) ? n : 0 }
export const fmtAUD = v => {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const s = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD' }).format(Math.abs(n))
  return n < 0 ? `(${s})` : s
}
export const fmtDate = d => (d ? new Date(String(d).slice(0, 10) + 'T00:00:00').toLocaleDateString('en-AU', { day: '2-digit', month: 'short', year: 'numeric' }) : '—')
export const todayISO = () => new Date().toISOString().slice(0, 10)
export const label = s => (s || '').replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())
export const pctText = v => (v == null || v === '' ? 'n/a' : `${v}%`)
export const saveBlob = (name, data) => {
  const url = URL.createObjectURL(data instanceof Blob ? data : new Blob([data]))
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
}
export const monthStart = (d = new Date()) => new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10)
export const fyStartISO = (d = new Date()) => `${d.getMonth() >= 6 ? d.getFullYear() : d.getFullYear() - 1}-07-01`
// What each figure IS. The same words are used on every Planning screen so actual, forecast, budget, scenario and AI numbers are never confused.
export const BASIS = {
  ACTUAL: { text: 'Actual', cls: 'badge-success', hint: 'Posted in the ledger' },
  FORECAST: { text: 'Forecast', cls: 'badge-info', hint: 'A projection, not a record' },
  BUDGET: { text: 'Budget', cls: 'badge-warning', hint: 'A plan you approved' },
  SCENARIO: { text: 'Scenario', cls: 'badge-neutral', hint: 'Hypothetical: what-if only' },
  AI: { text: 'AI assistant', cls: 'badge-info', hint: 'Read-only answer assembled from reports' },
  RULE: { text: 'Rule result', cls: 'badge-neutral', hint: 'Produced by a named rule' },
}
export const basisKey = b => { const t = String(b || '').toUpperCase(); return t.startsWith('FORECAST') ? 'FORECAST' : t.startsWith('BUDGET') ? 'BUDGET' : t.startsWith('SCENARIO') ? 'SCENARIO' : t.startsWith('AI') ? 'AI' : t.startsWith('RULE') ? 'RULE' : 'ACTUAL' }
