// Practice & Client Services API client. Staff routes live under /practice (organisation-scoped); client-portal routes under /portal (authorised per client).
// No field is ever called user_id / username (the platform AuthGuard reserves them): staff are addressed as staff_id.
// Every call here is answered by a route in backend/accfino/modules/practice/api (checked by the contract test).
import { http, errMsg } from '../../../core/lib/platformHttp.js'
export { errMsg }

const g = (url, params) => http.get(`/practice${url}`, { params }).then(r => r.data)
const p = (url, body, params) => http.post(`/practice${url}`, body ?? {}, { params }).then(r => r.data)
const u = (url, body) => http.put(`/practice${url}`, body ?? {}).then(r => r.data)
const d = url => http.delete(`/practice${url}`).then(r => r.data)
const blob = (url, params) => http.get(`/practice${url}`, { params, responseType: 'blob' }).then(r => r.data)
const form = (url, fd) => http.post(`/practice${url}`, fd).then(r => r.data)

export const me = () => g('/me')
export const workspace = { create: b => p('/workspace', b), profile: () => g('/profile'), saveProfile: b => u('/profile', b), saveSettings: b => u('/settings', b) }
export const members = { list: () => g('/members'), add: (staff_id, role) => p('/members', { staff_id, role }), change: (id, b) => u(`/members/${id}`, b), remove: id => d(`/members/${id}`) }
export const teams = { list: () => g('/teams'), create: (name, staff_ids) => p('/teams', { name, staff_ids }), setMembers: (id, staff_ids) => u(`/teams/${id}/members`, { staff_ids }), remove: id => d(`/teams/${id}`) }
export const audit = (limit = 100, prefix = '') => g('/audit', { limit, prefix })
export const dashboard = { summary: () => g('/dashboard'), workload: () => g('/dashboard/workload'), drill: (metric, page = 1, size = 25) => g(`/dashboard/${metric}`, { page, size }) }

export const clients = {
  search: params => g('/clients', params), create: (b, allow_duplicate = false) => p('/clients', b, { allow_duplicate }), get: id => g(`/clients/${id}`), update: (id, b) => u(`/clients/${id}`, b),
  setStatus: (id, status, reason) => p(`/clients/${id}/status`, { status, reason }), assign: b => p('/clients/assign', b), exportCsv: () => blob('/clients/export'),
  importCsv: (file, apply, strict = true) => { const fd = new FormData(); fd.append('file', file); fd.append('apply', apply); fd.append('strict', strict); return form('/clients/import', fd) },
  duplicates: status => g('/clients/duplicates', { status }), scanDuplicates: () => p('/clients/duplicates/scan'), reviewDuplicate: (id, decision, note) => p(`/clients/duplicates/${id}`, { decision, note }),
  setIdentifier: (id, b) => p(`/clients/${id}/identifiers`, b), reveal: (id, kind) => p(`/clients/${id}/identifiers/${kind}/reveal`), addNote: (id, body, kind) => p(`/clients/${id}/notes`, { body, kind }),
  consents: id => g(`/clients/${id}/consents`), recordConsent: (id, key, granted) => p(`/clients/${id}/consents`, { key, granted }), structure: id => g(`/clients/${id}/structure`),
  createEntity: (id, b) => p(`/clients/${id}/entities`, b), linkEntity: (id, eid, b) => p(`/clients/${id}/entities/${eid}/link`, b), unlinkEntity: (id, eid) => p(`/clients/${id}/entities/${eid}/unlink`),
  contacts: id => g(`/clients/${id}/contacts`), addContact: (id, b) => p(`/clients/${id}/contacts`, b),
}
export const entities = { update: (id, b) => u(`/entities/${id}`, b), setIdentifier: (id, b) => p(`/entities/${id}/identifiers`, b) }
export const relations = { add: b => p('/relations', b), end: id => p(`/relations/${id}/end`) }
export const contactLinks = { authority: (id, b) => u(`/contact-links/${id}`, b), primary: id => p(`/contact-links/${id}/primary`) }

export const documents = {
  list: params => g('/documents', params), get: id => g(`/documents/${id}`), update: (id, b) => u(`/documents/${id}`, b),
  upload: (client_id, file, extra = {}) => { const fd = new FormData(); fd.append('client_id', client_id); fd.append('file', file); Object.entries(extra).forEach(([k, v]) => v != null && fd.append(k, v)); return form('/documents', fd) },
  newVersion: (id, file, reason = '') => { const fd = new FormData(); fd.append('file', file); fd.append('reason', reason); return form(`/documents/${id}/versions`, fd) },
  archive: id => p(`/documents/${id}/archive`), restore: id => p(`/documents/${id}/restore`), hold: (id, hold, reason) => p(`/documents/${id}/hold`, { hold, reason }),
  remove: (id, reason) => p(`/documents/${id}/delete`, { reason }), preview: id => p(`/documents/${id}/preview`),
  // download = ask for a short-lived single-use ticket, then redeem it (the ticket never appears in a URL)
  download: async id => { const t = await p(`/documents/${id}/ticket`); return http.post('/practice/documents-download', { ticket: t.ticket }, { responseType: 'blob' }).then(r => ({ blob: r.data, name: t.file_name })) },
}
export const workpapers = {
  templates: () => g('/workpaper-templates'), createTemplate: b => p('/workpaper-templates', b), list: params => g('/workpapers', params), create: b => p('/workpapers', b), get: id => g(`/workpapers/${id}`),
  save: (id, b) => u(`/workpapers/${id}`, b), transition: (id, action, reason) => p(`/workpapers/${id}/transition`, { action, reason }), comment: (id, b) => p(`/workpapers/${id}/comments`, b),
  resolve: (id, cid) => p(`/workpapers/${id}/comments/${cid}/resolve`), attach: (id, document_id) => p(`/workpapers/${id}/documents`, { document_id }), detach: (id, did) => d(`/workpapers/${id}/documents/${did}`),
  addRef: (id, b) => p(`/workpapers/${id}/refs`, b), checkRefs: id => g(`/workpapers/${id}/refs/check`),
}

export const engagements = {
  templates: () => g('/engagement-templates'), createTemplate: b => p('/engagement-templates', b), rules: () => g('/deadline-rules'), createRule: b => p('/deadline-rules', b),
  list: params => g('/engagements', params), create: b => p('/engagements', b), get: id => g(`/engagements/${id}`), transition: (id, b) => p(`/engagements/${id}/transition`, b), renew: id => p(`/engagements/${id}/renew`),
  addDeadline: (id, b) => p(`/engagements/${id}/deadlines`, b), deadlines: params => g('/deadlines', params), verifyDeadline: (id, source) => p(`/deadlines/${id}/verify`, { source }),
  overrideDeadline: (id, new_due, reason) => p(`/deadlines/${id}/override`, { new_due, reason }), completeDeadline: id => p(`/deadlines/${id}/complete`), myWork: params => g('/my-work', params),
  jobTransition: (id, action, reason) => p(`/jobs/${id}/transition`, { action, reason }), assignJob: (id, b) => u(`/jobs/${id}/assignment`, b), points: id => g(`/jobs/${id}/review-points`),
  raisePoint: (id, finding, mandatory = true) => p(`/jobs/${id}/review-points`, { finding, mandatory }), respondPoint: (id, response) => p(`/review-points/${id}/respond`, { response }),
  resolvePoint: id => p(`/review-points/${id}/resolve`), taskAction: (id, action) => p(`/tasks/${id}/${action}`), tick: (id, done = true) => p(`/checklist/${id}`, { done }),
  createRecurrence: b => p('/recurrences', b), runRecurrences: () => p('/recurrences/run'),
}

export const portal = {
  invite: (client_id, contact_id, entity_ids) => p('/portal/invitations', { client_id, contact_id, entity_ids }), invites: client_id => g('/portal/invitations', { client_id }),
  resend: id => p(`/portal/invitations/${id}/resend`), revokeInvite: id => p(`/portal/invitations/${id}/revoke`), access: client_id => g(`/portal/access/${client_id}`), revokeAccess: id => p(`/portal/access/${id}/revoke`),
  requests: params => g('/portal/requests', params), createRequest: b => p('/portal/requests', b), reviewItem: (id, decision, note) => p(`/portal/request-items/${id}/review`, { decision, note }),
  cancelRequest: id => p(`/portal/requests/${id}/cancel`), messages: client_id => g(`/portal/messages/${client_id}`), post: (client_id, body, visibility) => p(`/portal/messages/${client_id}`, { body, visibility }),
  deliveries: client_id => g('/portal/deliveries', { client_id }), retryDeliveries: () => p('/portal/deliveries/retry'), activity: client_id => g(`/portal/activity/${client_id}`),
}

export const billing = {
  dashboard: params => g('/billing/dashboard', params), rates: () => g('/billing/rates'), setRate: b => p('/billing/rates', b),
  time: params => g('/billing/time', params), logTime: b => p('/billing/time', b), updateTime: (id, b) => u(`/billing/time/${id}`, b), deleteTime: id => d(`/billing/time/${id}`),
  submitTime: ids => p('/billing/time/submit', { ids }), approveTime: ids => p('/billing/time/approve', { ids }), rejectTime: (ids, reason) => p('/billing/time/reject', { ids, reason }),
  writeOff: (id, reason) => p(`/billing/time/${id}/write-off`, { reason }),
  invoices: params => g('/billing/invoices', params), generate: b => p('/billing/invoices', b), invoice: id => g(`/billing/invoices/${id}`), adjust: (id, b) => p(`/billing/invoices/${id}/adjustments`, b),
  issue: (id, issue_date) => p(`/billing/invoices/${id}/issue`, { issue_date }), void: (id, reason) => p(`/billing/invoices/${id}/void`, { reason }), creditNote: (id, amount, reason) => p(`/billing/invoices/${id}/credit-note`, { amount, reason }),
  share: (id, visible) => p(`/billing/invoices/${id}/share`, { visible }),
}

// ---- client side (portal login). Same HTTP client; routes carry the client id and the backend decides access on every call.
const pg = (url, params) => http.get(`/portal${url}`, { params }).then(r => r.data)
const pp = (url, body) => http.post(`/portal${url}`, body ?? {}).then(r => r.data)
export const clientPortal = {
  lookup: token => pp('/invitations/lookup', { token }), accept: b => pp('/invitations/accept', b), claim: token => pp('/invitations/claim', { token }), clients: () => pg('/clients'),
  dashboard: id => pg(`/clients/${id}/dashboard`), documents: id => pg(`/clients/${id}/documents`), requests: id => pg(`/clients/${id}/requests`), messages: id => pg(`/clients/${id}/messages`),
  invoices: id => pg(`/clients/${id}/invoices`), consents: id => pg(`/clients/${id}/consents`), notifications: id => pg(`/clients/${id}/notifications`),
  respondText: (id, item, text) => pp(`/clients/${id}/request-items/${item}/text`, { text }), postMessage: (id, body, request_id) => pp(`/clients/${id}/messages`, { body, request_id }),
  uploadFile: (id, item, file) => { const fd = new FormData(); fd.append('file', file); return http.post(`/portal/clients/${id}/request-items/${item}/file`, fd).then(r => r.data) },
  recordConsent: (id, key, granted) => pp(`/clients/${id}/consents`, { key, granted }), markRead: (id, nid) => pp(`/clients/${id}/notifications/${nid}/read`),
  download: async (id, doc) => { const t = await pp(`/clients/${id}/documents/${doc}/ticket`); return http.post(`/portal/clients/${id}/download`, { ticket: t.ticket }, { responseType: 'blob' }).then(r => ({ blob: r.data, name: t.file_name })) },
}
