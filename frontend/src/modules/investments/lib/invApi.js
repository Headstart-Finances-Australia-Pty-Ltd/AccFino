// Assets, Investments & Wealth API client. Org-aware (sends X-Org-Id) via the platform HTTP client. No field is ever called user_id / username (platform AuthGuard reserves them).
import { http, errMsg } from '../../../core/lib/platformHttp.js'
export { errMsg }

const g = (url, params) => http.get(`/invest${url}`, { params }).then(r => r.data)
const p = (url, body, params) => http.post(`/invest${url}`, body ?? {}, { params }).then(r => r.data)
const u = (url, body, params) => http.put(`/invest${url}`, body ?? {}, { params }).then(r => r.data)
const d = (url, params) => http.delete(`/invest${url}`, { params }).then(r => r.data)
const blob = (url, params) => http.get(`/invest${url}`, { params, responseType: 'blob' }).then(r => r.data)
const clean = o => Object.fromEntries(Object.entries(o || {}).filter(([, v]) => v !== '' && v != null))

export const me = () => g('/me')
export const reference = () => g('/reference')
export const settings = { get: () => g('/settings'), save: b => u('/settings', b) }
export const accounts = { list: active_only => g('/accounts', { active_only }), save: (b, id) => (id ? u(`/accounts/${id}`, b) : p('/accounts', b)) }
export const securities = {
  list: params => g('/securities', clean(params)), save: (b, id) => (id ? u(`/securities/${id}`, b) : p('/securities', b)), detail: (id, as_at) => g(`/securities/${id}/detail`, clean({ as_at })),
  setPrice: (id, b) => p(`/securities/${id}/prices`, b), prices: id => g(`/securities/${id}/prices`), removePrice: id => d(`/prices/${id}`),
}
export const txns = { list: params => g('/transactions', clean(params)), save: (b, id) => (id ? u(`/transactions/${id}`, b) : p('/transactions', b)), void: (id, reason) => p(`/transactions/${id}/void`, { reason }), swap: b => p('/crypto/swap', b) }
export const portfolio = {
  holdings: params => g('/portfolio/holdings', clean(params)), disposals: params => g('/portfolio/disposals', clean(params)), income: params => g('/portfolio/income', clean(params)),
  performance: params => g('/portfolio/performance', clean(params)), allocation: params => g('/portfolio/allocation', clean(params)), history: months => g('/portfolio/history', { months }),
}
export const property = {
  list: as_at => g('/properties', clean({ as_at })), save: (b, id) => (id ? u(`/properties/${id}`, b) : p('/properties', b)), remove: id => d(`/properties/${id}`), detail: (id, params) => g(`/properties/${id}`, clean(params)),
  saveEntry: (pid, b, eid) => (eid ? u(`/properties/${pid}/entries/${eid}`, b) : p(`/properties/${pid}/entries`, b)), voidEntry: (pid, eid, reason) => p(`/properties/${pid}/entries/${eid}/void`, { reason }),
  entries: (pid, params) => g(`/properties/${pid}/entries`, clean(params)), sendSale: (pid, dry_run) => p(`/properties/${pid}/cgt/send`, {}, { dry_run }),
}
export const valuations = { add: b => p('/valuations', b), list: (type, id) => g(`/valuations/${type}/${id}`), remove: id => d(`/valuations/${id}`) }
export const otherAssets = { list: as_at => g('/other-assets', clean({ as_at })), save: (b, id) => (id ? u(`/other-assets/${id}`, b) : p('/other-assets', b)) }
export const liabilities = { list: as_at => g('/liabilities', clean({ as_at })), save: (b, id) => (id ? u(`/liabilities/${id}`, b) : p('/liabilities', b)) }
export const networth = { get: as_at => g('/networth', clean({ as_at })), history: months => g('/networth/history', { months }), snapshots: () => g('/networth/snapshots'), snapshot: as_at => p('/networth/snapshots', clean({ as_at })) }
export const documents = {
  list: (owner_type, owner_id) => g('/documents', { owner_type, owner_id }), remove: id => d(`/documents/${id}`), download: id => blob(`/documents/${id}/download`),
  bulkTemplate: () => blob('/documents/bulk/template'),
  bulkPreview: (manifest, files) => { const f = new FormData(); f.append('manifest', manifest); files.forEach(x => f.append('files', x)); return http.post('/invest/documents/bulk/preview', f).then(r => r.data) },
  bulkCommit: (manifest, files, mode = 'valid_only') => { const f = new FormData(); f.append('manifest', manifest); files.forEach(x => f.append('files', x)); f.append('mode', mode); return http.post('/invest/documents/bulk/commit', f).then(r => r.data) },
  upload: (owner_type, owner_id, title, file) => { const f = new FormData(); f.append('file', file); f.append('owner_type', owner_type); f.append('owner_id', owner_id); f.append('title', title || file.name); return http.post('/invest/documents', f).then(r => r.data) },
}
export const cgt = { preview: params => g('/cgt/preview', clean(params)), send: b => p('/cgt/send', b) }
export const ledger = { bankAccounts: () => g('/ledger/bank-accounts'), post: b => p('/ledger/post', b), unlink: id => p(`/ledger/unlink/${id}`), reconciliation: as_at => g('/ledger/reconciliation', clean({ as_at })) }
const upload = (url, file, extra = {}) => { const f = new FormData(); f.append('file', file); Object.entries(extra).forEach(([k, v]) => f.append(k, v)); return http.post(`/invest${url}`, f).then(r => r.data) }
export const imports = { catalogue: () => g('/import/catalogue'), template: key => blob(`/import/${key}/template`), preview: (key, file) => upload(`/import/${key}/preview`, file), commit: (key, file, mode = 'valid_only') => upload(`/import/${key}/commit`, file, { mode }) }
export const reports = { csv: (name, params) => blob(`/reports/${name}.csv`, clean(params)), pack: params => blob('/reports/pack.xlsx', clean(params)) }
export const audit = { list: (entity_type, entity_id) => g('/audit', clean({ entity_type, entity_id, limit: 50 })), verify: () => g('/audit/verify') }
