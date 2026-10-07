// Payroll API client. Org-aware (sends X-Org-Id) via the platform HTTP client. NB: payroll never sends a field called user_id - the platform
// treats that name as "the signed-in caller" (the employee <-> login link is login_user_id).
import { http, errMsg } from '../../../core/lib/platformHttp.js'
export { errMsg }

const g = (url, params) => http.get(`/payroll${url}`, { params }).then(r => r.data)
const p = (url, body) => http.post(`/payroll${url}`, body ?? {}).then(r => r.data)
const u = (url, body) => http.put(`/payroll${url}`, body ?? {}).then(r => r.data)
const d = url => http.delete(`/payroll${url}`).then(r => r.data)
const text = (url, params) => http.get(`/payroll${url}`, { params, responseType: 'text', transformResponse: x => x }).then(r => r.data)

export const me = () => g('/me')
export const dashboard = () => g('/dashboard')
export const rules = () => g('/rules')
export const settings = () => g('/settings')
export const saveSettings = b => u('/settings', b)
export const ledgerAccounts = () => g('/ledger-accounts')

export const calendars = () => g('/calendars')
export const saveCalendar = (b, id) => (id ? u(`/calendars/${id}`, b) : p('/calendars', b))
export const calendarPeriods = (id, params) => g(`/calendars/${id}/periods`, params)

const crud = name => ({ list: () => g(`/${name}`), save: (b, id) => (id ? u(`/${name}/${id}`, b) : p(`/${name}`, b)) })
export const departments = crud('departments')
export const locations = crud('locations')
export const funds = crud('super-funds')
export const payItems = { ...crud('pay-items'), remove: id => d(`/pay-items/${id}`) }
export const leaveTypes = crud('leave-types')

export const employees = params => g('/employees', params)
export const employee = id => g(`/employees/${id}`)
export const loginUsers = () => g('/employees/login-users')
export const saveEmployee = (b, id) => (id ? u(`/employees/${id}`, b) : p('/employees', b))
export const terminateEmployee = (id, b) => p(`/employees/${id}/terminate`, b)
export const terminationSuggestion = id => g(`/employees/${id}/termination-suggestion`)
export const saveTax = (id, b) => u(`/employees/${id}/tax`, b)
export const revealTfn = id => p(`/employees/${id}/tax/reveal-tfn`)
export const saveSuper = (id, funds) => u(`/employees/${id}/super`, { funds })
export const saveBank = (id, accounts) => u(`/employees/${id}/bank`, { accounts })
export const assignItem = (id, b) => p(`/employees/${id}/items`, b)
export const removeItem = (id, aid) => d(`/employees/${id}/items/${aid}`)
export const employeeLeave = id => g(`/employees/${id}/leave`)
export const employeeLeaveHistory = id => g(`/employees/${id}/leave/history`)
export const adjustLeave = (id, b) => p(`/employees/${id}/leave/adjust`, b)

export const leaveRequests = params => g('/leave/requests', params)
export const requestLeave = b => p('/leave/requests', b)
export const decideLeave = (id, approve, note) => p(`/leave/requests/${id}/${approve ? 'approve' : 'reject'}`, { note })
export const cancelLeave = id => p(`/leave/requests/${id}/cancel`)
export const myLeaveBalances = () => g('/leave/my-balances')

export const timesheets = params => g('/timesheets', params)
export const timesheet = id => g(`/timesheets/${id}`)
export const saveTimesheet = (b, id) => (id ? u(`/timesheets/${id}`, b) : p('/timesheets', b))
export const timesheetAction = (id, action, body) => p(`/timesheets/${id}/${action}`, body)
export const deleteTimesheet = id => d(`/timesheets/${id}`)

export const runs = params => g('/runs', params)
export const run = id => g(`/runs/${id}`)
export const createRun = b => p('/runs', b)
export const runAction = (id, action, body) => p(`/runs/${id}/${action}`, body)
export const includeEmployee = (id, eid) => p(`/runs/${id}/employees/${eid}/include`)
export const excludeEmployee = (id, eid, reason) => p(`/runs/${id}/employees/${eid}/exclude`, { reason })
export const addRunInput = (id, b) => p(`/runs/${id}/inputs`, b)
export const removeRunInput = (id, iid) => d(`/runs/${id}/inputs/${iid}`)
export const runJournal = id => g(`/runs/${id}/journal`)
export const runIntegrity = id => g(`/runs/${id}/integrity`)

export const payslips = params => g('/payslips', params)
export const payslip = id => g(`/payslips/${id}`)
export const payslipHtml = id => text(`/payslips/${id}/html`)

export const payments = params => g('/payments', params)
export const preparePayment = (runId, b) => p(`/runs/${runId}/payments`, b)
export const payment = id => g(`/payments/${id}`)
export const abaFile = id => text(`/payments/${id}/aba`)
export const paymentAction = (id, action, body) => p(`/payments/${id}/${action}`, body)
export const paymentItemStatus = (id, itemId, body) => p(`/payments/${id}/items/${itemId}/status`, body)

export const superList = params => g('/super', params)
export const superMarkPaid = (ids, reference) => p('/super/mark-paid', { ids, reference })

export const stpList = () => g('/stp')
export const stpEvent = id => g(`/stp/${id}`)
export const stpPrepare = runId => p(`/runs/${runId}/stp`)
export const stpMockSubmit = id => p(`/stp/${id}/mock-submit`)
export const stpFinalisation = fy => g('/stp/finalisation', { fy })
export const stpFinalise = (fy, employee_ids) => p('/stp/finalise', { fy, employee_ids })
export const stpPaymentSummary = (employee_id, fy) => g('/stp/payment-summary', { employee_id, fy })

export const reportCatalogue = () => g('/reports')
export const report = (key, params) => g(`/reports/${key}`, params)
export const reportCsv = (key, params) => text(`/reports/${key}`, { ...params, format: 'csv' })
export const audit = params => g('/audit', params)

// Bulk CSV import (Check file = dry run, nothing saved; Import = all-or-nothing). Fields are named file / dry_run only (never user_id: see the note at the top).
export const importStatus = () => g('/imports/status')
export const importCatalogue = () => g('/imports')
export const importCsv = (entity, file, dryRun = true) => {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('dry_run', dryRun ? 'true' : 'false')
  return http.post(`/payroll/imports/${entity}`, fd, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
}
export const downloadImportTemplate = async entity => {
  const r = await http.get(`/payroll/imports/${entity}/template`, { responseType: 'blob' })
  const a = document.createElement('a'); a.href = URL.createObjectURL(r.data); a.download = `payroll-${entity}-template.csv`; a.click()
}

// Approvals: what is waiting for me to decide, and my notifications (the bell).
export const pendingApprovals = () => g('/approvals/pending')
export const notifications = () => g('/notifications')
export const markNotificationRead = id => p(`/notifications/${id}/read`)
export const markAllNotificationsRead = () => p('/notifications/read-all')
