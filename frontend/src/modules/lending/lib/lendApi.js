// Smart Lending, Credit & Treasury API client (persistent, organisation-scoped routes under /lending). Org-aware via the platform HTTP client.
// No field is ever called user_id / username (the platform AuthGuard reserves them). The older stateless analyser keeps its own client (lendingApi.js).
import { http, errMsg } from '../../../core/lib/platformHttp.js'
export { errMsg }

const g = (url, params) => http.get(`/lending${url}`, { params }).then(r => r.data)
const p = (url, body, params) => http.post(`/lending${url}`, body ?? {}, { params }).then(r => r.data)
const u = (url, body, params) => http.put(`/lending${url}`, body ?? {}, { params }).then(r => r.data)
const d = (url, params) => http.delete(`/lending${url}`, { params }).then(r => r.data)
const form = (url, fd) => http.post(`/lending${url}`, fd).then(r => r.data)
const blob = (url, params) => http.get(`/lending${url}`, { params, responseType: 'blob' }).then(r => r.data)

export const me = () => g('/me')
export const reference = () => g('/reference')
export const dashboard = () => g('/dashboard')
export const settings = { get: () => g('/settings'), save: b => u('/settings', b) }

export const applicants = {
  list: (q = '') => g('/applicants', { q }), create: b => p('/applicants', b), get: id => g(`/applicants/${id}`), saveProfile: (id, b) => u(`/applicants/${id}/profile`, b),
  addCommitment: (id, b) => p(`/applicants/${id}/commitments`, b), updateCommitment: (id, kid, b) => u(`/applicants/${id}/commitments/${kid}`, b), removeCommitment: (id, kid) => d(`/applicants/${id}/commitments/${kid}`),
}
export const bankAccounts = () => g('/bank-accounts')
export const ledgerAccounts = () => g('/ledger-accounts')
export const analyses = {
  list: cid => g(`/applicants/${cid}/analyses`), get: (id, lines = false) => g(`/analyses/${id}`, { lines }), lines: (id, flagged = false) => g(`/analyses/${id}/lines`, { flagged }),
  upload: (cid, files, fields = {}) => { const fd = new FormData(); files.forEach(f => fd.append('files', f)); Object.entries(fields).forEach(([k, v]) => { if (v !== '' && v != null) fd.append(k, v) }); return form(`/applicants/${cid}/analyses/upload`, fd) },
  fromBooks: (cid, b) => p(`/applicants/${cid}/analyses/books`, b), reanalyse: (id, b) => p(`/analyses/${id}/reanalyse`, b), override: (id, lid, b) => p(`/analyses/${id}/lines/${lid}/override`, b), suggestions: id => g(`/analyses/${id}/commitment-suggestions`),
}
export const applications = {
  list: (params) => g('/applications', params), create: b => p('/applications', b), get: id => g(`/applications/${id}`), update: (id, b) => u(`/applications/${id}`, b), assess: (id, notes = '') => p(`/applications/${id}/assess`, { notes }),
  status: (id, status, reason = '') => p(`/applications/${id}/status`, { status, reason }), decide: (id, decision, reason) => p(`/applications/${id}/decision`, { decision, reason }), requestDoc: (id, b) => p(`/applications/${id}/documents`, b),
  uploadDoc: (id, key, file) => { const fd = new FormData(); fd.append('file', file); return form(`/applications/${id}/documents/${key}`, fd) }, downloadDoc: (id, key) => blob(`/applications/${id}/documents/${key}/download`), removeDoc: (id, key) => d(`/applications/${id}/documents/${key}`),
  settle: (id, b) => p(`/applications/${id}/settle`, b),
}
export const loans = {
  list: params => g('/loans', params), create: b => p('/loans', b), get: id => g(`/loans/${id}`), schedule: id => g(`/loans/${id}/schedule`), repay: (id, b, post = false) => p(`/loans/${id}/repayments`, b, { post }),
  postRepayment: (id, rid) => p(`/loans/${id}/repayments/${rid}/post`), voidRepayment: (id, rid, reason) => p(`/loans/${id}/repayments/${rid}/void`, { reason }), rateChange: (id, b) => p(`/loans/${id}/rate-changes`, b),
  refinance: (id, b) => p(`/loans/${id}/refinance`, b), setStatus: (id, status, reason) => p(`/loans/${id}/status`, { status, reason }),
}
export const collections = {
  register: params => g('/collections', params), caseFor: id => g(`/collections/${id}`), activity: (id, b) => p(`/collections/${id}/activities`, b), arrange: (id, b) => p(`/collections/${id}/arrangements`, b),
  closeArrangement: (id, rid, status, notes = '') => p(`/collections/${id}/arrangements/${rid}/close`, { status, notes }), hardship: (id, b) => p(`/collections/${id}/hardship`, b), hardshipAction: (id, hid, b) => p(`/collections/${id}/hardship/${hid}`, b),
}
export const treasury = {
  position: (horizon = 90) => g('/treasury/position', { horizon }), facilities: () => g('/treasury/facilities'), saveFacility: (b, id) => (id ? u(`/treasury/facilities/${id}`, b) : p('/treasury/facilities', b)),
  items: params => g('/treasury/forecast-items', params), saveItem: (b, id) => (id ? u(`/treasury/forecast-items/${id}`, b) : p('/treasury/forecast-items', b)),
}
