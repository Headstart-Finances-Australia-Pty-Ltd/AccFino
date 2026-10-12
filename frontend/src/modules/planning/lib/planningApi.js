// Planning & Intelligence API client (organisation-scoped routes under /planning). Org-aware via the platform HTTP client.
// No field is ever called user_id / username (the platform AuthGuard reserves them). Every call here is answered by a route in backend/accfino/modules/planning/api.
import { http, errMsg } from '../../../core/lib/platformHttp.js'
export { errMsg }

const g = (url, params) => http.get(`/planning${url}`, { params }).then(r => r.data)
const p = (url, body, params) => http.post(`/planning${url}`, body ?? {}, { params }).then(r => r.data)
const u = (url, body) => http.put(`/planning${url}`, body ?? {}).then(r => r.data)
const d = url => http.delete(`/planning${url}`).then(r => r.data)
const blob = (url, params) => http.get(`/planning${url}`, { params, responseType: 'blob' }).then(r => r.data)

export const me = () => g('/me')
export const overview = () => g('/overview')
export const settings = { get: () => g('/settings'), save: b => u('/settings', b) }
export const drilldown = (account_id, from, to) => g('/drilldown', { account_id, from, to })

export const forecast = {
  get: (params) => g('/forecast', params), save: b => p('/forecast/snapshots', b), snapshots: () => g('/forecast/snapshots'), snapshot: id => g(`/forecast/snapshots/${id}`),
  vsActual: id => g(`/forecast/snapshots/${id}/vs-actual`),
}
export const budgets = {
  list: (include_archived = false) => g('/budgets', { include_archived }), create: b => p('/budgets', b), get: id => g(`/budgets/${id}`), saveLines: (id, lines) => u(`/budgets/${id}/lines`, { lines }),
  importCsv: (id, csv, apply = true, strict = true) => p(`/budgets/${id}/import`, { csv, apply, strict }), exportCsv: id => blob(`/budgets/${id}/export`), copy: (id, name) => p(`/budgets/${id}/copy`, { name }),
  submit: id => p(`/budgets/${id}/submit`), approve: id => p(`/budgets/${id}/approve`), reject: (id, note) => p(`/budgets/${id}/reject`, { note }), archive: id => p(`/budgets/${id}/archive`),
  remove: id => d(`/budgets/${id}`), vsActual: (id, from, to) => g(`/budgets/${id}/vs-actual`, { from, to }),
}
export const scenarios = {
  templates: () => g('/scenarios/templates'), list: (include_archived = false) => g('/scenarios', { include_archived }), create: b => p('/scenarios', b), update: (id, b) => u(`/scenarios/${id}`, b),
  duplicate: (id, name) => p(`/scenarios/${id}/duplicate`, { name }), archive: id => p(`/scenarios/${id}/archive`), run: (id, b) => p(`/scenarios/${id}/run`, b), runs: id => g(`/scenarios/${id}/runs`),
  runGet: (id, rid) => g(`/scenarios/${id}/runs/${rid}`), compare: b => p('/scenarios/compare', b), sensitivity: id => g(`/scenarios/${id}/sensitivity`),
}
export const reports = {
  get: (kind, params) => g(`/reports/${kind}`, params), snapshot: (kind, b) => p(`/reports/${kind}/snapshot`, b), snapshots: kind => g('/reports/snapshots', { kind }), snapshotGet: id => g(`/reports/snapshots/${id}`),
  exportFile: (kind, params) => blob(`/reports/${kind}/export`, params),
}
export const insights = { get: params => g('/insights', params), saveConfig: b => u('/insights/config', b) }
export const assistant = { ask: question => p('/assistant/ask', { question }), suggestions: () => g('/assistant/suggestions'), history: () => g('/assistant/history') }
export const risk = {
  alerts: params => g('/risk/alerts', params), preview: () => g('/risk/preview'), scan: () => p('/risk/scan'), review: (id, status, note) => p(`/risk/alerts/${id}/review`, { status, note }),
  config: () => g('/risk/config'), saveConfig: thresholds => u('/risk/config', { thresholds }),
}
