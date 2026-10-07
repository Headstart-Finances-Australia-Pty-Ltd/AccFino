// CSV utilities
export function parseCSVText(text) {
  const result = []
  const lines = text.split('\n').map(l => l.endsWith('\r') ? l.slice(0,-1) : l)
  for (const line of lines) {
    if (!line.trim()) continue
    const cols = []; let cur = ''; let inQ = false
    for (let i = 0; i < line.length; i++) {
      const ch = line[i]
      if (ch === '"') { if (inQ && line[i+1] === '"') { cur += '"'; i++ } else inQ = !inQ }
      else if (ch === ',' && !inQ) { cols.push(cur); cur = '' }
      else cur += ch
    }
    cols.push(cur); result.push(cols.map(v => v.trim()))
  }
  return result
}

export function toCSV(rows, headers) {
  const q = v => '"' + String(v || '').split('"').join('""') + '"'
  return [headers.join(','), ...rows.map(r => headers.map(h => q(r[h] || '')).join(','))].join('\n')
}

export function downloadCSV(filename, csvText) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([csvText], { type: 'text/csv' }))
  a.download = filename; a.click()
}
