export const num = v => { const n = Number(v); return Number.isFinite(n) ? n : 0 }
export const fmtAUD = v => {
  if (v == null || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const s = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD' }).format(Math.abs(n))
  return n < 0 ? `(${s})` : s
}
export const fmtHours = v => (v == null || v === '' ? '—' : num(v).toLocaleString('en-AU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
export const fmtDate = d => (d ? new Date(String(d).slice(0, 10) + 'T00:00:00').toLocaleDateString('en-AU', { day: '2-digit', month: 'short', year: 'numeric' }) : '—')
export const todayISO = () => new Date().toISOString().slice(0, 10)
export const label = s => (s || '').replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())
export const download = (name, text, type = 'text/plain') => {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
}
export const fyLabel = (d = new Date()) => { const y = d.getMonth() >= 6 ? d.getFullYear() : d.getFullYear() - 1; return `${y}-${String(y + 1).slice(2)}` }
