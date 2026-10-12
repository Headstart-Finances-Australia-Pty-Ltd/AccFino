export const num = v => { const n = Number(v); return Number.isFinite(n) ? n : 0 }
export const fmtAUD = v => {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const s = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD' }).format(Math.abs(n))
  return n < 0 ? `(${s})` : s
}
export const fmtDate = d => (d ? new Date(String(d).slice(0, 10) + 'T00:00:00').toLocaleDateString('en-AU', { day: '2-digit', month: 'short', year: 'numeric' }) : '—')
export const METHOD = { ato_online_services: 'ATO Online services', tax_agent: 'a registered tax agent', other: 'another method' }
export const todayISO = () => new Date().toISOString().slice(0, 10)
export const label = s => (s || '').replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())
export const fyOf = (d = new Date()) => { const y = d.getMonth() >= 6 ? d.getFullYear() : d.getFullYear() - 1; return `${y}-${String(y + 1).slice(2)}` }
export const fyOptions = (n = 4) => { const y = Number(fyOf().slice(0, 4)); return Array.from({ length: n }, (_, i) => { const s = y + 1 - i; return `${s}-${String(s + 1).slice(2)}` }) }
export const fbtOf = (d = new Date()) => `FBT${d.getMonth() >= 3 ? d.getFullYear() + 1 : d.getFullYear()}`
export const fbtOptions = (n = 3) => { const y = Number(fbtOf().slice(3)); return Array.from({ length: n }, (_, i) => `FBT${y + 1 - i}`) }
export const saveBlob = (name, data) => {
  const url = URL.createObjectURL(data instanceof Blob ? data : new Blob([data]))
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
}
