// Taxation & Compliance API client. Org-aware (sends X-Org-Id) via the platform HTTP client. No field is ever called user_id / username (platform AuthGuard reserves them).
import { http, errMsg } from '../../../core/lib/platformHttp.js'
export { errMsg }

const g = (url, params) => http.get(`/tax${url}`, { params }).then(r => r.data)
const p = (url, body, params) => http.post(`/tax${url}`, body ?? {}, { params }).then(r => r.data)
const u = (url, body, params) => http.put(`/tax${url}`, body ?? {}, { params }).then(r => r.data)
const d = (url, params) => http.delete(`/tax${url}`, { params }).then(r => r.data)
const blob = (url, params) => http.get(`/tax${url}`, { params, responseType: 'blob' }).then(r => r.data)

export const me = () => g('/me')
export const dashboard = () => g('/dashboard')
export const health = () => g('/health')
export const reference = fy => g('/reference', { fy })

export const profile = () => g('/profile')
export const saveProfile = b => u('/profile', b)
export const rules = fy => g('/rules', { fy })
export const setOverride = b => u('/rules/override', b)
export const clearOverride = (fy, path) => d('/rules/override', { fy, path })
export const registrations = () => g('/registrations')
export const saveRegistration = (b, id) => (id ? u(`/registrations/${id}`, b) : p('/registrations', b))
export const deleteRegistration = id => d(`/registrations/${id}`)

export const obligations = params => g('/obligations', params)
export const generateObligations = fy => p('/obligations/generate', { fy })
export const addObligation = b => p('/obligations', b)
export const updateObligation = (id, b) => u(`/obligations/${id}`, b)
export const deleteObligation = id => d(`/obligations/${id}`)

export const bas = {
  list: params => g('/bas', params), create: b => p('/bas', b), get: id => g(`/bas/${id}`),
  calculate: id => p(`/bas/${id}/calculate`), prepare: id => p(`/bas/${id}/prepare`), approve: (id, b) => p(`/bas/${id}/approve`, b), back: (id, b) => p(`/bas/${id}/return`, b),
  lodged: (id, b) => p(`/bas/${id}/lodged`, b), paid: (id, b) => p(`/bas/${id}/paid`, b), void: (id, b) => p(`/bas/${id}/void`, b),
  override: (id, b) => u(`/bas/${id}/override`, b), removeOverride: (id, label) => d(`/bas/${id}/override/${encodeURIComponent(label)}`),
}
export const returns = {
  list: params => g('/returns', params), create: b => p('/returns', b), get: id => g(`/returns/${id}`), inputs: (id, b) => u(`/returns/${id}/inputs`, b),
  calculate: id => p(`/returns/${id}/calculate`), prepare: id => p(`/returns/${id}/prepare`), approve: (id, b) => p(`/returns/${id}/approve`, b), back: (id, b) => p(`/returns/${id}/return`, b),
  lodged: (id, b) => p(`/returns/${id}/lodged`, b), assessment: (id, b) => p(`/returns/${id}/assessment`, b), paid: (id, b) => p(`/returns/${id}/paid`, b),
  void: (id, b) => p(`/returns/${id}/void`, b), amend: (id, b) => p(`/returns/${id}/amend`, b),
}
export const adjustments = {
  list: fy => g('/adjustments', { fy }), save: (fy, b, id) => (id ? u(`/adjustments/${id}`, b, { fy }) : p('/adjustments', b, { fy })), remove: (fy, id) => d(`/adjustments/${id}`, { fy }),
  review: (id, b) => p(`/adjustments/${id}/review`, b), generateDepreciation: fy => p('/adjustments/generate-depreciation', { fy }),
}
export const assetsReview = fy => g('/assets/review', { fy })

export const cgt = {
  events: fy => g('/cgt/events', { fy }), save: (b, id) => (id ? u(`/cgt/events/${id}`, b) : p('/cgt/events', b)), remove: id => d(`/cgt/events/${id}`),
  importTrades: b => p('/cgt/import-trades', b), exclude: (id, excluded) => p(`/cgt/events/${id}/exclude`, { excluded }), importRows: b => p('/cgt/import', b), losses: () => g('/cgt/losses'), addLoss: b => p('/cgt/losses', b),
  removeLoss: id => d(`/cgt/losses/${id}`), compute: (fy, holder) => g('/cgt/compute', { fy, holder }),
}
export const fbt = {
  employees: () => g('/fbt/employees'), benefits: year => g('/fbt/benefits', { year }), saveBenefit: (year, b, id) => (id ? u(`/fbt/benefits/${id}`, b, { year }) : p('/fbt/benefits', b, { year })),
  removeBenefit: (year, id) => d(`/fbt/benefits/${id}`, { year }), summary: year => g('/fbt/summary', { year }), returns: () => g('/fbt/returns'), get: id => g(`/fbt/returns/${id}`),
  calculate: year => p('/fbt/returns/calculate', { year }), prepare: id => p(`/fbt/returns/${id}/prepare`), approve: (id, b) => p(`/fbt/returns/${id}/approve`, b),
  back: (id, b) => p(`/fbt/returns/${id}/return`, b), lodged: (id, b) => p(`/fbt/returns/${id}/lodged`, b), paid: (id, b) => p(`/fbt/returns/${id}/paid`, b),
}
export const div7a = {
  loans: () => g('/div7a/loans'), save: (b, id) => (id ? u(`/div7a/loans/${id}`, b) : p('/div7a/loans', b)), remove: id => d(`/div7a/loans/${id}`),
  payments: id => g(`/div7a/loans/${id}/payments`), addPayment: (id, b) => p(`/div7a/loans/${id}/payments`, b), removePayment: (id, pid) => d(`/div7a/loans/${id}/payments/${pid}`),
  schedule: (id, through_fy) => g(`/div7a/loans/${id}/schedule`, { through_fy }),
}
export const workpapers = {
  list: params => g('/workpapers', params), get: id => g(`/workpapers/${id}`), save: (b, id) => (id ? u(`/workpapers/${id}`, b) : p('/workpapers', b)), generate: b => p('/workpapers/generate', b),
  advance: (id, b) => p(`/workpapers/${id}/advance`, b), remove: id => d(`/workpapers/${id}`),
}
export const evidence = {
  list: params => g('/evidence', params),
  add: fields => { const f = new FormData(); Object.entries(fields).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') f.append(k, v) }); return http.post('/tax/evidence', f).then(r => r.data) },
  download: id => blob(`/evidence/${id}/file`), remove: id => d(`/evidence/${id}`),
}
export const planning = { get: id => g(`/planning/scenarios/${id}`), update: (id, b) => u(`/planning/scenarios/${id}`, b), estimate: b => p('/planning/estimate', b), scenarios: fy => g('/planning/scenarios', { fy }), saveScenario: b => p('/planning/scenarios', b), removeScenario: id => d(`/planning/scenarios/${id}`) }
export const lodgement = {
  state: (doc_type, doc_id) => g('/lodgement/state', { doc_type, doc_id }), providers: () => g('/lodgement/providers'),
  sign: b => p('/signoffs', b), revoke: (id, reason) => p(`/signoffs/${id}/revoke`, { reason }), submit: (doc_type, doc_id, provider) => p('/lodgement/submit', { doc_type, doc_id, provider }),
  pack: (doc_type, doc_id) => blob('/lodgement/pack', { doc_type, doc_id }),
}
// ---- bulk CSV import, GST adjustments register, per-record history --------------------------------------------------------------------------------------
const upload = (url, file, extra = {}) => { const f = new FormData(); f.append('file', file); Object.entries(extra).forEach(([k, v]) => f.append(k, v)); return http.post(`/tax${url}`, f).then(r => r.data) }
export const imports = {
  catalogue: () => g('/import/catalogue'), template: key => blob(`/import/${key}/template`),
  preview: (key, file) => upload(`/import/${key}/preview`, file), commit: (key, file, mode = 'valid_only') => upload(`/import/${key}/commit`, file, { mode }),
}
export const gst = {
  list: params => g('/gst/adjustments', params), summary: (date_from, date_to) => g('/gst/summary', { date_from, date_to }), save: (b, id) => (id ? u(`/gst/adjustments/${id}`, b) : p('/gst/adjustments', b)),
  status: (id, status) => p(`/gst/adjustments/${id}/status`, { status }), remove: id => d(`/gst/adjustments/${id}`),
}
export const auditFor = (entity_type, entity_id) => g('/audit', { entity_type, entity_id, limit: 50 })
export const payrollTaxWatch = fy => g('/payroll-tax/watch', { fy })
export const reconcile = (date_from, date_to) => g('/reconcile', { date_from, date_to })
export const readiness = (kind, doc_id) => g('/readiness', { kind, doc_id })
export const summaryPack = fy => g('/reports/summary', { fy })
export const exportCsv = params => blob('/reports/export', params)
export const exportXlsx = fy => blob('/reports/xlsx', { fy })
export const audit = params => g('/audit', params)
export const verifyAudit = () => g('/audit/verify')
