import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../lib/payrollApi.js', async () => {
  const actual = await vi.importActual('../lib/payrollApi.js')
  const fn = () => vi.fn(() => Promise.resolve([]))
  return { ...actual, me: vi.fn(), dashboard: vi.fn(), employees: vi.fn(), employee: vi.fn(), run: vi.fn(), runs: vi.fn(() => Promise.resolve([])), runAction: vi.fn(() => Promise.resolve({})), calendars: vi.fn(() => Promise.resolve([])),
    departments: { list: fn(), save: vi.fn() }, locations: { list: fn(), save: vi.fn() }, funds: { list: fn(), save: vi.fn() }, payItems: { list: fn(), save: vi.fn(), remove: vi.fn() }, leaveTypes: { list: fn(), save: vi.fn() },
    saveEmployee: vi.fn(), loginUsers: vi.fn(() => Promise.resolve([])), saveTax: vi.fn(), saveBank: vi.fn(), timesheets: vi.fn(() => Promise.resolve([])), payslips: vi.fn(() => Promise.resolve([])), leaveRequests: vi.fn(() => Promise.resolve([])),
    myLeaveBalances: vi.fn(() => Promise.resolve([])), pendingApprovals: vi.fn(() => Promise.resolve({ timesheets: 0, leave: 0, total: 0 })), notifications: vi.fn(() => Promise.resolve({ unread: 0, items: [] })), markNotificationRead: vi.fn(() => Promise.resolve({})), markAllNotificationsRead: vi.fn(() => Promise.resolve({})), report: vi.fn(), reportCatalogue: vi.fn(() => Promise.resolve([{ key: 'payroll_summary', title: 'Payroll Summary' }])), departments_: null,
    runJournal: vi.fn(() => Promise.resolve({ posted: false, message: 'No journal yet' })), runIntegrity: vi.fn(() => Promise.resolve({ checked: false, reason: 'not sealed' })), payments: vi.fn(() => Promise.resolve([])) }
})
vi.mock('../../../core/hooks/useModuleVisibility.jsx', () => ({ useModuleVisibility: () => ({ isModuleVisible: () => true }) }))

import * as api from '../lib/payrollApi.js'
import { validTfn, validBsb, validAccount, employeeProblems } from '../lib/validators.js'
import { timesheetProblems } from '../pages/TimesheetsTab.jsx'
import { fmtAUD } from '../lib/format.js'
import PayrollPage from '../pages/PayrollPage.jsx'
import DashboardTab from '../pages/DashboardTab.jsx'
import EmployeesTab from '../pages/EmployeesTab.jsx'
import { RunDetail } from '../pages/PayRunsTab.jsx'
import ReportTable from '../components/ReportTable.jsx'
import { PayslipBody } from '../components/PayslipView.jsx'

const ADMIN = { role: 'payroll_admin', capabilities: ['view', 'employees_view', 'employees_manage', 'sensitive_view', 'tfn_reveal', 'config_manage', 'items_manage', 'run_create', 'run_approve', 'run_finalise', 'run_reverse', 'payments_manage', 'journal_view', 'reports_view', 'audit_view', 'stp_manage', 'timesheets_manage', 'timesheets_approve', 'leave_manage', 'leave_approve'], self_service: false, is_manager: false, is_payroll_staff: true }
const MANAGER = { ...ADMIN, role: 'payroll', capabilities: ADMIN.capabilities.filter(c => !['config_manage', 'items_manage', 'run_reverse', 'tfn_reveal', 'audit_view'].includes(c)) }
const EMPLOYEE = { role: 'employee', capabilities: [], self_service: true, is_manager: false, is_payroll_staff: false, approver: 'Jane Smith' }
const LINE_MANAGER = { ...EMPLOYEE, is_manager: true }
const wrap = ui => render(<MemoryRouter>{ui}</MemoryRouter>)
beforeEach(() => {
  vi.clearAllMocks()          // clears call history only: mockResolvedValue from an earlier test would otherwise leak, so restore the defaults that tests override
  api.pendingApprovals.mockImplementation(() => Promise.resolve({ timesheets: 0, leave: 0, total: 0 }))
  api.notifications.mockImplementation(() => Promise.resolve({ unread: 0, items: [] }))
})

describe('validators', () => {
  it('checks the TFN check digit', () => { expect(validTfn('123 456 782')).toBe(true); expect(validTfn('123456789')).toBe(false); expect(validTfn('12345')).toBe(false) })
  it('checks BSB and account length', () => { expect(validBsb('062-000')).toBe(true); expect(validBsb('12')).toBe(false); expect(validAccount('12345678')).toBe(true); expect(validAccount('12')).toBe(false) })
  it('collects employee problems', () => {
    expect(employeeProblems({ first_name: '', last_name: 'X', start_date: '2026-01-01', pay_basis: 'salary', annual_salary: 0, hours_per_week: '38', employment_type: 'full_time' })).toEqual(expect.arrayContaining(['First name is required', 'Annual salary must be greater than zero']))
    expect(employeeProblems({ first_name: 'A', last_name: 'B', start_date: '2026-01-01', pay_basis: 'salary', annual_salary: 90000, hours_per_week: '38', employment_type: 'casual' })).toContain('Casual employees are paid by the hour')
    expect(employeeProblems({ first_name: 'A', last_name: 'B', start_date: '2026-01-01', pay_basis: 'hourly', hourly_rate: 30, hours_per_week: '38', employment_type: 'casual' })).toEqual([])
  })
  it('flags timesheet problems', () => {
    const wk = '2026-09-07'
    expect(timesheetProblems([], wk)).toContain('Add at least one line')
    expect(timesheetProblems([{ work_date: '2026-09-07', pay_item_id: 1, hours: '25' }], wk)).toContain('Line 1: more than 24 hours')
    expect(timesheetProblems([{ work_date: '2026-09-20', pay_item_id: 1, hours: '8' }], wk)).toContain('Line 1: date is outside the week')
    expect(timesheetProblems([{ work_date: '2026-09-07', pay_item_id: '', hours: '0' }], wk)).toEqual(expect.arrayContaining(['Line 1: choose a pay category', 'Line 1: hours must be greater than zero']))
    expect(timesheetProblems([{ work_date: '2026-09-07', pay_item_id: 1, hours: '8' }], wk)).toEqual([])
  })
  it('formats money with brackets for negatives', () => { expect(fmtAUD(1234.5)).toBe('$1,234.50'); expect(fmtAUD(-5)).toBe('($5.00)'); expect(fmtAUD(null)).toBe('—') })
})

describe('role-based navigation', () => {
  it('shows payroll staff the full tab set', async () => {
    api.me.mockResolvedValue(ADMIN); api.dashboard.mockResolvedValue(dash())
    wrap(<PayrollPage />)
    await waitFor(() => expect(screen.getByRole('tab', { name: /Payrun/ })).toBeInTheDocument())
    expect(screen.getByRole('tab', { name: /Time & Leave/ })).toBeInTheDocument()
    for (const n of [/Employees/, /Reports/, /Settings/]) expect(screen.getByRole('tab', { name: n })).toBeInTheDocument()
    // the six payroll areas moved inside Payrun: they are no longer top-level tabs
    for (const n of [/Timesheets/, /^🏖 Leave/, /Pay Runs/, /Payments/, /^💰 Super/, /PAYG/, /^🕵 Audit/, /^🧩 Pay Items/, /^📄 Payslips/]) expect(screen.queryByRole('tab', { name: n })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /My Pay/ })).not.toBeInTheDocument()
  })
  it('Payrun holds Pay Runs, Payslips, Payments, Super, Pay Items, PAYG and Audit as sub-tabs', async () => {
    api.me.mockResolvedValue(ADMIN); api.dashboard.mockResolvedValue(dash())
    render(<MemoryRouter initialEntries={['/payroll?tab=payrun']}><PayrollPage /></MemoryRouter>)
    const bar = await screen.findByRole('tablist', { name: /Payrun sections/ })
    expect(within(bar).getAllByRole('tab').map(t => t.textContent)).toEqual(['Pay Runs', 'Payslips', 'Payments', 'Super', 'Pay Items', 'PAYG', 'Audit'])
    expect(await screen.findByText('Pay runs')).toBeInTheDocument()          // Pay Runs is the default sub-tab
    fireEvent.click(within(bar).getByRole('tab', { name: 'Payslips' }))
    await waitFor(() => expect(within(bar).getByRole('tab', { name: 'Payslips' })).toHaveAttribute('aria-selected', 'true'))
  })
  it('Time & Leave holds Timesheets and Leave, and old addresses land on them', async () => {
    api.me.mockResolvedValue(ADMIN); api.dashboard.mockResolvedValue(dash())
    render(<MemoryRouter initialEntries={['/payroll?tab=leave']}><PayrollPage /></MemoryRouter>)
    const bar = await screen.findByRole('tablist', { name: /Time and leave sections/ })
    expect(within(bar).getAllByRole('tab').map(t => t.textContent)).toEqual(['Timesheets', 'Leave'])
    await waitFor(() => expect(within(bar).getByRole('tab', { name: 'Leave' })).toHaveAttribute('aria-selected', 'true'))
  })
  it('a line manager (an employee with direct reports) gets Timesheets and Leave as sub-tabs of Time & Leave', async () => {
    api.me.mockResolvedValue(LINE_MANAGER)
    render(<MemoryRouter initialEntries={['/payroll?tab=timeleave']}><PayrollPage /></MemoryRouter>)
    const bar = await screen.findByRole('tablist', { name: /Time and leave sections/ })
    expect(within(bar).getAllByRole('tab').map(t => t.textContent)).toEqual(['Timesheets', 'Leave'])
  })
  it('an ordinary employee has no Time & Leave tab (My Pay already holds their timesheets and leave) and an old link lands on My Pay', async () => {
    api.me.mockResolvedValue(EMPLOYEE)
    render(<MemoryRouter initialEntries={['/payroll?tab=timeleave']}><PayrollPage /></MemoryRouter>)
    await waitFor(() => expect(screen.getByRole('tab', { name: /My Pay/ })).toHaveAttribute('aria-selected', 'true'))
    expect(screen.queryByRole('tab', { name: /Time & Leave/ })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'My pay' })).toBeInTheDocument()
  })
  it('My Pay asks the server for the employee\'s own timesheets and leave only, and says who approves them', async () => {
    api.me.mockResolvedValue(EMPLOYEE)
    wrap(<PayrollPage />)
    await waitFor(() => expect(api.timesheets).toHaveBeenCalledWith(expect.objectContaining({ mine: true })))
    expect(api.leaveRequests).toHaveBeenCalledWith(expect.objectContaining({ mine: true }))
    expect(await screen.findAllByText('Jane Smith')).not.toHaveLength(0)
  })
  it('old tab addresses land on the matching Payrun sub-tab', async () => {
    api.me.mockResolvedValue(ADMIN); api.dashboard.mockResolvedValue(dash())
    api.report.mockResolvedValue({ title: 'PAYG', columns: [], rows: [], totals: {} }); api.rules = vi.fn(() => new Promise(() => {}))
    render(<MemoryRouter initialEntries={['/payroll?tab=payg']}><PayrollPage /></MemoryRouter>)
    const bar = await screen.findByRole('tablist', { name: /Payrun sections/ })
    await waitFor(() => expect(within(bar).getByRole('tab', { name: 'PAYG' })).toHaveAttribute('aria-selected', 'true'))
  })
  it('a payroll manager sees only the Payrun sub-tabs their role allows', async () => {
    api.me.mockResolvedValue(MANAGER); api.dashboard.mockResolvedValue(dash())
    render(<MemoryRouter initialEntries={['/payroll?tab=payrun']}><PayrollPage /></MemoryRouter>)
    const bar = await screen.findByRole('tablist', { name: /Payrun sections/ })
    expect(within(bar).getAllByRole('tab').map(t => t.textContent)).toEqual(['Pay Runs', 'Payslips', 'Payments', 'Super', 'PAYG'])
  })
  it('hides configuration, audit and reversal-only areas from a payroll manager', async () => {
    api.me.mockResolvedValue(MANAGER); api.dashboard.mockResolvedValue(dash())
    wrap(<PayrollPage />)
    await waitFor(() => expect(screen.getByRole('tab', { name: /Payrun/ })).toBeInTheDocument())
    for (const n of [/Settings/, /Audit/, /Pay Items/]) expect(screen.queryByRole('tab', { name: n })).not.toBeInTheDocument()
  })
  it('gives an employee only self-service tabs', async () => {
    api.me.mockResolvedValue(EMPLOYEE)
    wrap(<PayrollPage />)
    await waitFor(() => expect(screen.getByRole('tab', { name: /My Pay/ })).toBeInTheDocument())
    for (const n of [/Dashboard/, /Employees/, /Payrun/, /Payslips/, /Reports/, /Settings/, /Payments/]) expect(screen.queryByRole('tab', { name: n })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /Time & Leave/ })).not.toBeInTheDocument()       // no duplicate of My Pay
  })
  it('shows a pending-approvals badge on Time & Leave and unread count on the bell', async () => {
    api.me.mockResolvedValue(LINE_MANAGER); api.pendingApprovals.mockResolvedValue({ timesheets: 2, leave: 1, total: 3 })
    api.notifications.mockResolvedValue({ unread: 2, items: [{ id: 1, kind: 'timesheet_submitted', title: 'Timesheet to approve: Cass Hourly', body: 'Week of 2026-09-07', tab: 'timeleave', sub: 'timesheets', is_read: false, created_at: '2026-10-05T01:00:00' }] })
    wrap(<PayrollPage />)
    expect(await screen.findByTestId('pending-approvals-badge')).toHaveTextContent('3')
    expect(screen.getByTestId('bell-unread')).toHaveTextContent('2')
    fireEvent.click(screen.getByRole('button', { name: /Notifications/ }))
    fireEvent.click(await screen.findByText('Timesheet to approve: Cass Hourly'))
    await waitFor(() => expect(api.markNotificationRead).toHaveBeenCalledWith(1))
    expect(await screen.findByRole('tablist', { name: /Time and leave sections/ })).toBeInTheDocument()      // the bell opens the screen the item is about
  })
  it('shows no badge when nothing waits for the person', async () => {
    api.me.mockResolvedValue(ADMIN); api.dashboard.mockResolvedValue(dash())
    wrap(<PayrollPage />)
    await waitFor(() => expect(screen.getByRole('tab', { name: /Time & Leave/ })).toBeInTheDocument())
    expect(screen.queryByTestId('pending-approvals-badge')).not.toBeInTheDocument()
  })
  it('hides Approve and Reject unless the server says the person may decide that row', async () => {
    api.me.mockResolvedValue(ADMIN); api.dashboard.mockResolvedValue(dash())
    const row = (id, can) => ({ id, employee_id: id, employee: `Emp ${id}`, employee_number: `E${id}`, week_start: '2026-09-07', week_end: '2026-09-13', status: 'submitted', totals: { ordinary: '8', overtime: '0', leave: '0', total: '8' }, can_decide: can })
    api.timesheets.mockResolvedValue([row(1, true), row(2, false)])
    render(<MemoryRouter initialEntries={['/payroll?tab=timeleave&sub=timesheets']}><PayrollPage /></MemoryRouter>)
    await screen.findByText('Emp 1')
    expect(screen.getAllByRole('button', { name: 'Approve' })).toHaveLength(1)           // only the row Emp 1 (e.g. not the caller's own sheet)
    expect(screen.getAllByRole('button', { name: 'Reject' })).toHaveLength(1)
  })
  it('tells someone with no employee record why My Pay is empty', async () => {
    api.me.mockResolvedValue({ ...ADMIN, self_service: false }); api.dashboard.mockResolvedValue(dash())
    render(<MemoryRouter initialEntries={['/payroll?tab=mypay']}><PayrollPage /></MemoryRouter>)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/not linked to an employee record/))      // the loading spinner is also role=status: wait for the message, do not assert on the first status found
  })
  it('shows an error state with retry when the access check fails', async () => {
    api.me.mockRejectedValue({ response: { data: { detail: 'You do not have access to Payroll in this organisation' } } })
    wrap(<PayrollPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('do not have access to Payroll')
    expect(screen.getByRole('button', { name: /Try again/ })).toBeInTheDocument()
  })
})

const dash = (o = {}) => ({ financial_year: '2026-27', employees: { active: 3, by_type: { full_time: 2, casual: 1 }, requiring_attention: 1, attention: [{ employee_id: 9, employee_number: 'E0009', name: 'Dana Gap', issues: [{ code: 'no_bank', severity: 'error', message: 'No bank account: net pay cannot be paid' }] }] },
  ytd: { gross: '120000.00', payg: '30000.00', super: '14400.00', net: '90000.00', employer_cost: '135000.00' }, next_pay_run: { calendar: 'Fortnightly', period_start: '2026-09-21', period_end: '2026-10-04', pay_date: '2026-10-09', run_status: 'not_started' },
  periods: [], last_run: { run_no: 'PR-0001', pay_date: '2026-09-25', employee_count: 3, total_gross: '12000.00', total_net: '9000.00' }, pending: { timesheets_to_approve: 2, leave_to_approve: 1, runs_in_progress: 0, runs_awaiting_payment: 1, super_overdue: 1, super_unpaid: 3 },
  alerts: [{ level: 'danger', code: 'super_overdue', message: '1 super contribution(s) are past their Payday Super due date' }], reminders: [{ date: '2026-10-28', days: 23, message: 'Quarterly BAS' }], trend: [], upcoming_pay_dates: [{ calendar: 'Fortnightly', pay_date: '2026-10-09', days: 4 }], recent_runs: [], ...o })

describe('dashboard', () => {
  it('shows figures from the API, attention list, pending actions and alerts', async () => {
    api.dashboard.mockResolvedValue(dash())
    wrap(<DashboardTab onNav={() => {}} />)
    expect(await screen.findByText('$120,000.00')).toBeInTheDocument()
    expect(screen.getByText('$30,000.00')).toBeInTheDocument()
    expect(screen.getByText(/Dana Gap/)).toBeInTheDocument(); expect(screen.getByText(/No bank account/)).toBeInTheDocument()
    expect(screen.getByText(/past their Payday Super due date/)).toBeInTheDocument()
    expect(screen.getByText('Timesheets to approve').nextSibling).toHaveTextContent('2')
  })
  it('shows an empty state when there is no pay calendar', async () => {
    api.dashboard.mockResolvedValue(dash({ next_pay_run: null }))
    wrap(<DashboardTab onNav={() => {}} />)
    expect(await screen.findByText('No pay calendar yet')).toBeInTheDocument()
  })
  it('shows an error state if the dashboard cannot load', async () => {
    api.dashboard.mockRejectedValue({ response: { data: { detail: 'boom' } } })
    wrap(<DashboardTab onNav={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('boom')
  })
})

describe('employees', () => {
  it('lists employees without sensitive columns for a role that cannot see pay', async () => {
    api.employees.mockResolvedValue({ items: [{ id: 1, employee_number: 'E0001', name: 'Jane Smith', position: 'Analyst', department_id: null, employment_type: 'full_time', pay_frequency: 'fortnightly', status: 'active', pay_basis: 'salary' }], total: 1 })
    wrap(<EmployeesTab me={{ ...MANAGER, capabilities: ['view', 'employees_view'] }} />)
    expect(await screen.findByText('Jane Smith')).toBeInTheDocument()
    expect(screen.queryByText('Rate')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /New employee/ })).not.toBeInTheDocument()
  })
  it('validates a new employee before saving and does not call the API', async () => {
    api.employees.mockResolvedValue({ items: [], total: 0 })
    wrap(<EmployeesTab me={ADMIN} />)
    fireEvent.click(await screen.findByRole('button', { name: /New employee/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Create employee/ }))
    expect(await screen.findByText('First name is required')).toBeInTheDocument()
    expect(screen.getByText('Annual salary must be greater than zero')).toBeInTheDocument()
    expect(api.saveEmployee).not.toHaveBeenCalled()
  })
  it('creates an employee from valid input', async () => {
    api.employees.mockResolvedValue({ items: [], total: 0 })
    api.saveEmployee.mockResolvedValue({ id: 5, employee_number: 'E0005', name: 'New Person', status: 'active' })
    api.employee.mockResolvedValue({ id: 5, employee_number: 'E0005', name: 'New Person', first_name: 'New', last_name: 'Person', status: 'active', pay_basis: 'salary', start_date: '2026-09-01', readiness: [] })
    wrap(<EmployeesTab me={ADMIN} />)
    fireEvent.click(await screen.findByRole('button', { name: /New employee/ }))
    fireEvent.change(await screen.findByLabelText('First name'), { target: { value: 'New' } })
    fireEvent.change(screen.getByLabelText('Last name'), { target: { value: 'Person' } })
    fireEvent.click(screen.getByRole('button', { name: 'Employment & pay' }))
    fireEvent.change(await screen.findByLabelText('Annual salary'), { target: { value: '90000' } })
    fireEvent.click(screen.getByRole('button', { name: /Create employee/ }))
    await waitFor(() => expect(api.saveEmployee).toHaveBeenCalled())
    const [body, id] = api.saveEmployee.mock.calls[0]
    expect(id).toBeUndefined(); expect(body.first_name).toBe('New'); expect(body.annual_salary).toBe('90000'); expect(body.hourly_rate).toBeNull()
    expect(body).not.toHaveProperty('user_id')
  })
  it('refuses an invalid TFN in the tax section', async () => {
    api.employees.mockResolvedValue({ items: [{ id: 1, employee_number: 'E0001', name: 'Jane Smith', status: 'active', employment_type: 'full_time', pay_frequency: 'fortnightly', pay_basis: 'salary', annual_salary: '90000', hours_per_week: '38' }], total: 1 })
    api.employee.mockResolvedValue({ id: 1, employee_number: 'E0001', name: 'Jane Smith', first_name: 'Jane', last_name: 'Smith', status: 'active', pay_basis: 'salary', start_date: '2025-01-01', hours_per_week: '38', readiness: [], tax: { tfn_masked: '*** *** 782', tfn_status: 'provided', residency: 'resident', claims_tft: true }, super: [], bank: [], items: [] })
    wrap(<EmployeesTab me={ADMIN} />)
    fireEvent.click(await screen.findByText('Jane Smith'))
    fireEvent.click(await screen.findByRole('button', { name: 'Tax' }))
    fireEvent.change(await screen.findByLabelText('TFN'), { target: { value: '123456789' } })
    expect(await screen.findByText(/not a valid TFN/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Save tax details/ })).toBeDisabled()
    expect(screen.queryByText('123456782')).not.toBeInTheDocument()
  })
})

const RUN = (status, o = {}) => ({ id: 1, run_no: 'PR-0001', name: 'Test run', run_type: 'regular', status, locked: ['finalised', 'paid'].includes(status), period_start: '2026-09-07', period_end: '2026-09-20', pay_date: '2026-09-25', rule_set: '2026-27',
  employee_count: 1, total_gross: '4000.00', total_taxable: '4000.00', total_payg: '918.00', total_study_loan: '0', total_deductions: '0', total_net: '3082.00', total_super: '480.00', total_employer_cost: '4480.00', error_count: 0, reversed_by_run_id: null,
  employees: [{ id: 11, employee_id: 1, employee_number: 'E0001', employee_name: 'Jane Smith', status: 'included', ordinary_hours: '76', overtime_hours: '0', leave_hours: '0', gross: '4000.00', payg: '918.00', study_loan: '0', pretax_deductions: '0', posttax_deductions: '0', sacrifice_super: '0', net: '3082.00', super_total: '480.00', taxable: '4000.00', tax_scale: '2', errors: [], warnings: [], lines: [] }], inputs: [], ...o })

describe('pay run workflow', () => {
  const open = async (status, me = ADMIN, o = {}) => { api.run.mockResolvedValue(RUN(status, o)); wrap(<RunDetail id={1} me={me} onBack={() => {}} onNav={() => {}} />); await screen.findByText(/PR-0001/) }
  it('draft: can calculate and cancel, cannot approve or finalise', async () => {
    await open('draft')
    expect(screen.getByRole('button', { name: 'Calculate' })).toBeInTheDocument(); expect(screen.getByRole('button', { name: /Cancel run/ })).toBeInTheDocument()
    for (const n of [/^Approve$/, /Finalise/, /Reverse/]) expect(screen.queryByRole('button', { name: n })).not.toBeInTheDocument()
  })
  it('review with errors: approve is disabled and the errors are visible', async () => {
    await open('review', ADMIN, { error_count: 1, employees: [{ ...RUN('review').employees[0], errors: [{ code: 'no_bank', message: 'No bank account: net pay cannot be paid' }] }] })
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
    fireEvent.click(screen.getByText('Jane Smith'))
    expect(await screen.findByText(/No bank account/)).toBeInTheDocument()
  })
  it('review without errors: approve calls the API', async () => {
    await open('review')
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(api.runAction).toHaveBeenCalledWith(1, 'approve'))
  })
  it('approved: finalise asks for confirmation, then locks', async () => {
    await open('approved')
    fireEvent.click(screen.getByRole('button', { name: /Finalise/ }))
    const dlg = await screen.findByText(/This creates payslips/)
    expect(dlg).toBeInTheDocument(); expect(api.runAction).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Finalise and lock' }))
    await waitFor(() => expect(api.runAction).toHaveBeenCalledWith(1, 'finalise'))
  })
  it('finalised: the run is locked - no edit actions, reversal needs a reason', async () => {
    await open('finalised')
    expect(screen.getByText(/Finalised and locked/)).toBeInTheDocument()
    for (const n of ['Calculate', 'Recalculate', 'Approve']) expect(screen.queryByRole('button', { name: n })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Exclude/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Reverse/ }))
    await screen.findByLabelText('Reason for reversal')
    const buttons = screen.getAllByRole('button', { name: 'Reverse' })
    const modalBtn = buttons[buttons.length - 1]
    expect(modalBtn).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Reason for reversal'), { target: { value: 'wrong rate' } })
    expect(modalBtn).not.toBeDisabled()
  })
  it('a payroll manager cannot reverse a finalised run', async () => {
    await open('finalised', MANAGER)
    expect(screen.queryByRole('button', { name: /Reverse/ })).not.toBeInTheDocument()
  })
  it('an accountant sees the run read-only', async () => {
    await open('review', { ...ADMIN, capabilities: ['view', 'employees_view', 'sensitive_view', 'reports_view', 'journal_view', 'audit_view'] })
    for (const n of ['Recalculate', 'Approve']) expect(screen.queryByRole('button', { name: n })).not.toBeInTheDocument()
  })
  it('a reversal run is shown as such and has no actions', async () => {
    await open('finalised', ADMIN, { run_type: 'reversal' })
    expect(screen.getByText(/reversal of another pay run/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Reverse/ })).not.toBeInTheDocument()
  })
})

describe('reports and payslips', () => {
  it('renders totals and a reconciliation control, flagging a mismatch', () => {
    const rep = { title: 'X', note: '', columns: [{ key: 'name', label: 'Name', type: 'text' }, { key: 'gross', label: 'Gross', type: 'money' }], rows: [{ name: 'Jane', gross: '4000.00' }], totals: { gross: '4000.00' },
      control: [{ label: 'Gross = lines', report: '4000.00', source: '3999.00', difference: '1.00', reconciled: false, source_name: 'pay_run_lines' }] }
    render(<ReportTable rep={rep} />)
    expect(screen.getAllByText('$4,000.00').length).toBeGreaterThan(1)
    expect(screen.getByText(/DOES NOT RECONCILE/)).toBeInTheDocument()
  })
  it('shows an empty state for a report with no rows', () => {
    render(<ReportTable rep={{ title: 'X', columns: [{ key: 'a', label: 'A', type: 'text' }], rows: [], totals: {}, control: [] }} />)
    expect(screen.getByText('No data for these filters')).toBeInTheDocument()
  })
  it('renders a payslip with the right figures and a masked account', () => {
    const s = { payslip_no: 'PR-0001-E0001', employer: { name: 'Test Pty Ltd', abn: '51 824 753 556' }, employee: { name: 'Jane Smith', number: 'E0001', employment_type: 'full_time' }, pay_date: '2026-09-25', period_start: '2026-09-07', period_end: '2026-09-20', frequency: 'fortnightly',
      earnings: [{ name: 'Base salary', amount: '4000.00' }], deductions: [], reimbursements: [], totals: { gross: '4000.00', payg: '918.00', study_loan: '0', net: '3082.00' }, payment: [{ account_name: 'Jane', bsb: '062-000', account: '•••• 5432', amount: '3082.00' }],
      super: [{ fund: 'AustralianSuper', component: 'sg', amount: '480.00' }], ytd: { gross: '4000.00', tax: '918.00', super_total: '480.00' }, leave: [{ name: 'Annual leave', accrued: '5.85', taken: '0', balance: '5.85' }] }
    render(<PayslipBody s={s} />)
    expect(screen.getAllByText('$3,082.00').length).toBeGreaterThan(0); expect(screen.getAllByText('$918.00')).toHaveLength(2); expect(screen.getByText(/•••• 5432/)).toBeInTheDocument(); expect(screen.getAllByText('$480.00')).toHaveLength(2)
  })
})

describe('new pay run dialog', () => {
  it('lists periods around a chosen date so back-dated periods can be selected', async () => {
    api.calendars.mockResolvedValue([{ id: 7, name: 'Fortnightly', frequency: 'fortnightly', is_active: true }])
    api.calendarPeriods = vi.fn(() => Promise.resolve([{ period_start: '2026-09-21', period_end: '2026-10-04', pay_date: '2026-10-09' }]))
    api.runs.mockResolvedValue([])
    const { default: PayRunsTab } = await import('../pages/PayRunsTab.jsx')
    wrap(<PayRunsTab me={ADMIN} onNav={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: /New pay run/ }))
    fireEvent.change(await screen.findByLabelText('Pay calendar'), { target: { value: '7' } })
    fireEvent.change(await screen.findByLabelText('Show periods around'), { target: { value: '2026-10-05' } })
    await waitFor(() => expect(api.calendarPeriods).toHaveBeenLastCalledWith('7', expect.objectContaining({ around: '2026-10-05' })))
    fireEvent.change(await screen.findByLabelText('Pay period'), { target: { value: '0' } })
    expect(screen.getByRole('button', { name: /Create pay run/ })).not.toBeDisabled()
  })
})
