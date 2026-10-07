import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../lib/payrollApi.js', async () => {
  const actual = await vi.importActual('../lib/payrollApi.js')
  const list = () => vi.fn(() => Promise.resolve([]))
  return { ...actual, importStatus: vi.fn(), importCatalogue: vi.fn(), importCsv: vi.fn(), downloadImportTemplate: vi.fn(() => Promise.resolve()),
    employees: vi.fn(() => Promise.resolve({ items: [] })), departments: { list: list(), save: vi.fn() }, locations: { list: list(), save: vi.fn() }, funds: { list: list(), save: vi.fn() },
    payItems: { list: list(), save: vi.fn(), remove: vi.fn() }, leaveTypes: { list: list(), save: vi.fn() }, calendars: vi.fn(() => Promise.resolve([])), runs: vi.fn(() => Promise.resolve([])),
    timesheets: vi.fn(() => Promise.resolve([])), leaveRequests: vi.fn(() => Promise.resolve([])), myLeaveBalances: vi.fn(() => Promise.resolve([])), loginUsers: vi.fn(() => Promise.resolve([])), settings: vi.fn() }
})
vi.mock('../../../core/hooks/useModuleVisibility.jsx', () => ({ useModuleVisibility: () => ({ isModuleVisible: () => true }) }))

import * as api from '../lib/payrollApi.js'
import { http } from '../../../core/lib/platformHttp.js'
import toast from 'react-hot-toast'
import { ImportButton, ImportCentre, ImportModal, resetImportStatus } from '../components/CsvImport.jsx'
import EmployeesTab from '../pages/EmployeesTab.jsx'
import TimesheetsTab from '../pages/TimesheetsTab.jsx'
import LeaveTab from '../pages/LeaveTab.jsx'
import PayRunsTab from '../pages/PayRunsTab.jsx'
import PayItemsTab from '../pages/PayItemsTab.jsx'
import SettingsTab from '../pages/SettingsTab.jsx'

const col = (name, required = false, help = '', example = '') => ({ name, required, help, example })
const CAT = [
  { entity: 'departments', title: 'Departments', order: 3, group: 'Settings', capability: 'config_manage', mode: 'upsert', allowed: true, description: 'Departments used for grouping.', notes: ['Matched on code.'], columns: [col('code', true, 'Short code', 'OPS'), col('name', true, 'Name', 'Operations')] },
  { entity: 'employees', title: 'Employees (personal & employment)', order: 8, group: 'Employees', capability: 'employees_manage', mode: 'upsert', allowed: true, description: 'Personal details and pay rate.', notes: [], columns: [col('employee_number', true, 'The number', 'B0001'), col('first_name', false, 'First name')] },
  { entity: 'employee_tax', title: 'Employee tax declarations', order: 9, group: 'Employees', capability: 'employees_manage', mode: 'upsert', allowed: true, description: 'TFN and residency.', notes: [], columns: [col('employee_number', true)] },
  { entity: 'timesheets', title: 'Timesheets', order: 14, group: 'Time & Leave', capability: 'timesheets_manage', mode: 'new_only', allowed: true, description: 'Weekly timesheets.', notes: [], columns: [col('employee_number', true)] },
  { entity: 'pay_items', title: 'Pay items', order: 7, group: 'Settings', capability: 'items_manage', mode: 'upsert', allowed: false, description: 'Earnings and deductions.', notes: [], columns: [col('code', true)] },
]
const OK = { entity: 'departments', title: 'Departments', dry_run: true, count: 2, valid: 2, invalid: 0, saved: 0, error: null, total: '0.00', warnings: ['Ignored column(s) not used by this import: colour'], items_truncated: 0,
  items: [{ row: 2, label: 'OPS Operations', detail: '', amount: null, errors: [], warnings: [], action: 'create' }, { row: 3, label: 'FIN Finance', detail: '', amount: null, errors: [], warnings: ['careful'], action: 'update' }] }
const BAD = { ...OK, valid: 1, invalid: 1, error: '1 of 2 record(s) have problems; nothing was imported. Fix the file and try again.', items: [{ row: 3, label: 'row 3', detail: '', amount: null, errors: ['Department needs a code (letters/digits, up to 20) and a name'], warnings: [], action: 'create' }, OK.items[0]] }
const file = name => new File(['a,b\n1,2\n'], name, { type: 'text/csv' })

const ADMIN = { role: 'payroll_admin', capabilities: ['view', 'employees_view', 'employees_manage', 'sensitive_view', 'config_manage', 'items_manage', 'run_create', 'run_approve', 'timesheets_manage', 'timesheets_approve', 'leave_manage', 'leave_approve'], self_service: false, is_manager: false, is_payroll_staff: true }
const READONLY = { role: 'accountant', capabilities: ['view', 'employees_view', 'sensitive_view', 'reports_view'], self_service: false, is_manager: false, is_payroll_staff: true }
const wrap = ui => render(<MemoryRouter>{ui}</MemoryRouter>)

beforeEach(() => {
  vi.clearAllMocks(); resetImportStatus()
  api.importStatus.mockResolvedValue({ enabled: true }); api.importCatalogue.mockResolvedValue({ items: CAT }); api.importCsv.mockResolvedValue(OK)
})

describe('import window', () => {
  it('check file, then import: nothing is imported until the check is clean', async () => {
    const onDone = vi.fn()
    api.importCsv.mockResolvedValueOnce(OK).mockResolvedValueOnce({ ...OK, dry_run: false, saved: 2 })
    wrap(<ImportButton entities={['departments']} onDone={onDone} />)
    fireEvent.click(await screen.findByTestId('import-departments'))
    expect(await screen.findByText('Departments used for grouping.')).toBeInTheDocument()
    expect(screen.getByText('Matched on code.')).toBeInTheDocument()
    expect(screen.getByText(/Existing records are updated/)).toBeInTheDocument()
    const check = screen.getByRole('button', { name: /Check file/ }), imp = screen.getByRole('button', { name: /^Import$/ })
    expect(check).toBeDisabled(); expect(imp).toBeDisabled()
    fireEvent.change(screen.getByLabelText('CSV file'), { target: { files: [file('d.csv')] } })
    expect(check).not.toBeDisabled(); expect(imp).toBeDisabled()
    fireEvent.click(check)
    await waitFor(() => expect(api.importCsv).toHaveBeenCalledWith('departments', expect.any(File), true))
    expect(await screen.findByText(/Checked: all 2 record\(s\) are valid/)).toBeInTheDocument()
    expect(screen.getByText(/Ignored column\(s\)/)).toBeInTheDocument()
    expect(screen.getByText(/careful/)).toBeInTheDocument()
    expect(onDone).not.toHaveBeenCalled()
    fireEvent.click(await screen.findByRole('button', { name: /Import 2 record\(s\)/ }))
    await waitFor(() => expect(api.importCsv).toHaveBeenLastCalledWith('departments', expect.any(File), false))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(toast.success).toHaveBeenCalledWith('2 record(s) imported')
  })

  it('shows every problem with its row number and keeps Import disabled', async () => {
    api.importCsv.mockResolvedValue(BAD)
    wrap(<ImportModal entities={['departments']} onClose={() => {}} />)
    fireEvent.change(await screen.findByLabelText('CSV file'), { target: { files: [file('d.csv')] } })
    fireEvent.click(screen.getByRole('button', { name: /Check file/ }))
    const result = await screen.findByTestId('csv-import-result')
    expect(within(result).getByText(/nothing was imported/)).toBeInTheDocument()
    expect(within(result).getByText('Department needs a code (letters/digits, up to 20) and a name')).toBeInTheDocument()
    expect(within(result).getAllByRole('row')[1]).toHaveTextContent('3')                          // problems are listed first
    expect(screen.getByRole('button', { name: /^Import$/ })).toBeDisabled()
  })

  it('changing the file clears an earlier check, so a stale check can never be imported', async () => {
    wrap(<ImportModal entities={['departments']} onClose={() => {}} />)
    const input = await screen.findByLabelText('CSV file')
    fireEvent.change(input, { target: { files: [file('a.csv')] } }); fireEvent.click(screen.getByRole('button', { name: /Check file/ }))
    await screen.findByTestId('csv-import-result')
    fireEvent.change(input, { target: { files: [file('b.csv')] } })
    expect(screen.queryByTestId('csv-import-result')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Import$/ })).toBeDisabled()
  })

  it('shows the columns and downloads the template', async () => {
    wrap(<ImportModal entities={['departments']} onClose={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Show columns' }))
    expect(screen.getByText('Short code')).toBeInTheDocument(); expect(screen.getByText(/e\.g\. OPS/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Download template' }))
    expect(api.downloadImportTemplate).toHaveBeenCalledWith('departments')
  })

  it('lets you choose between related imports and describes each', async () => {
    wrap(<ImportModal entities={['employees', 'employee_tax']} onClose={() => {}} />)
    const pick = await screen.findByLabelText('What are you importing')
    expect(screen.getByText('Personal details and pay rate.')).toBeInTheDocument()
    fireEvent.change(pick, { target: { value: 'employee_tax' } })
    expect(screen.getByText('TFN and residency.')).toBeInTheDocument()
    expect(screen.getByText(/Existing records are updated/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('CSV file'), { target: { files: [file('t.csv')] } }); fireEvent.click(screen.getByRole('button', { name: /Check file/ }))
    await waitFor(() => expect(api.importCsv).toHaveBeenCalledWith('employee_tax', expect.any(File), true))
  })

  it('says transactions are loaded once, never duplicated', async () => {
    wrap(<ImportModal entities={['timesheets']} onClose={() => {}} />)
    expect(await screen.findByText(/loading the same rows twice is refused, never duplicated/)).toBeInTheDocument()
  })

  it('a role that may not import it cannot pick a file or check', async () => {
    wrap(<ImportModal entities={['pay_items']} onClose={() => {}} />)
    expect(await screen.findByText(/Your role cannot import this/)).toBeInTheDocument()
    expect(screen.getByLabelText('CSV file')).toBeDisabled(); expect(screen.getByRole('button', { name: /Check file/ })).toBeDisabled()
  })

  it('a server error while checking is reported, not swallowed', async () => {
    api.importCsv.mockRejectedValue({ response: { data: { detail: 'Bulk data import has been switched off by your platform administrator' } } })
    wrap(<ImportModal entities={['departments']} onClose={() => {}} />)
    fireEvent.change(await screen.findByLabelText('CSV file'), { target: { files: [file('d.csv')] } }); fireEvent.click(screen.getByRole('button', { name: /Check file/ }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('switched off')))
    expect(screen.queryByTestId('csv-import-result')).not.toBeInTheDocument()
  })

  it('a failed real import reports the failure and does not call onDone', async () => {
    const onDone = vi.fn()
    api.importCsv.mockResolvedValueOnce(OK).mockResolvedValueOnce({ ...BAD, dry_run: false })
    wrap(<ImportModal entities={['departments']} onClose={() => {}} onDone={onDone} />)
    fireEvent.change(await screen.findByLabelText('CSV file'), { target: { files: [file('d.csv')] } }); fireEvent.click(screen.getByRole('button', { name: /Check file/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Import 2 record\(s\)/ }))
    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect(onDone).not.toHaveBeenCalled()
  })
})

describe('the switch', () => {
  it('hides the button when bulk import is switched off', async () => {
    api.importStatus.mockResolvedValue({ enabled: false })
    wrap(<ImportButton entities={['departments']} />)
    await waitFor(() => expect(api.importStatus).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByTestId('import-departments')).not.toBeInTheDocument())
  })
  it('shows the button if the status cannot be read (the server still refuses an upload when it is off)', async () => {
    api.importStatus.mockRejectedValue(new Error('network'))
    wrap(<ImportButton entities={['departments']} />)
    expect(await screen.findByTestId('import-departments')).toBeInTheDocument()
  })
  it('the import centre explains when it is off', async () => {
    api.importStatus.mockResolvedValue({ enabled: false })
    wrap(<ImportCentre />)
    expect(await screen.findByText(/switched off by your platform administrator/)).toBeInTheDocument()
  })
})

describe('import centre (Settings > Bulk import)', () => {
  it('lists every import in load order with a button and a template', async () => {
    wrap(<ImportCentre />)
    const table = await screen.findByTestId('import-centre')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map(r => within(r).getAllByRole('cell')[0].textContent)).toEqual(['03', '07', '08', '09', '14'].sort((a, b) => a - b))
    expect(screen.getByText(/Load in the numbered order/)).toBeInTheDocument()
    expect(screen.getByTestId('centre-import-pay_items')).toBeDisabled()                      // this role cannot import pay items
    expect(screen.getByTestId('centre-import-employees')).not.toBeDisabled()
    fireEvent.click(within(rows[0]).getByRole('button', { name: 'Template' }))
    expect(api.downloadImportTemplate).toHaveBeenCalledWith('departments')
    fireEvent.click(screen.getByTestId('centre-import-employees'))
    expect(await screen.findByText('Personal details and pay rate.')).toBeInTheDocument()
  })
})

describe('where the buttons are, and who sees them', () => {
  it('Employees: payroll staff who manage employees get the employee imports; read-only roles do not', async () => {
    const { unmount } = wrap(<EmployeesTab me={ADMIN} />)
    expect(await screen.findByTestId('import-employees')).toBeInTheDocument()
    unmount()
    wrap(<EmployeesTab me={READONLY} />)
    await screen.findByText('Employees')
    await waitFor(() => expect(api.employees).toHaveBeenCalled())
    expect(screen.queryByTestId('import-employees')).not.toBeInTheDocument()
  })
  it('Timesheets and Leave: only for people who manage them, never inside My Pay', async () => {
    const t = wrap(<TimesheetsTab me={ADMIN} />)
    expect(await screen.findByTestId('import-timesheets')).toBeInTheDocument(); t.unmount()
    const t2 = wrap(<TimesheetsTab me={{ ...ADMIN, capabilities: [], self_service: true }} mine />)
    await screen.findByText('Timesheets'); expect(screen.queryByTestId('import-timesheets')).not.toBeInTheDocument(); t2.unmount()
    const l = wrap(<LeaveTab me={ADMIN} />)
    expect(await screen.findByTestId('import-leave_requests')).toBeInTheDocument(); l.unmount()
    wrap(<LeaveTab me={{ ...ADMIN, capabilities: [], self_service: true }} mine />)
    await screen.findByText('Leave'); expect(screen.queryByTestId('import-leave_requests')).not.toBeInTheDocument()
  })
  it('Pay runs: pay run and input imports for those who can create runs', async () => {
    const t = wrap(<PayRunsTab me={ADMIN} onNav={() => {}} />)
    expect(await screen.findByTestId('import-pay_runs')).toBeInTheDocument(); t.unmount()
    wrap(<PayRunsTab me={READONLY} onNav={() => {}} />)
    await screen.findByText('Pay runs'); expect(screen.queryByTestId('import-pay_runs')).not.toBeInTheDocument()
  })
  it('Pay items: administrators only', async () => {
    const t = wrap(<PayItemsTab me={ADMIN} />)
    expect(await screen.findByTestId('import-pay_items')).toBeInTheDocument(); t.unmount()
    wrap(<PayItemsTab me={{ ...ADMIN, capabilities: ['view', 'employees_manage', 'run_create'] }} />)
    await screen.findByText('Pay items'); expect(screen.queryByTestId('import-pay_items')).not.toBeInTheDocument()
  })
  it('Settings: calendars, leave types, super funds, departments, locations and the Bulk import tab', async () => {
    api.settings.mockResolvedValue({ employer_name: 'X', abn: '', default_frequency: 'fortnightly', standard_hours_per_week: '38', employee_prefix: 'E', run_prefix: 'PR', payslip_config: {}, payment_config: {}, accounting_map: {}, stp_config: {}, controls: {} })
    wrap(<SettingsTab me={ADMIN} />)
    expect(screen.getByRole('button', { name: 'Bulk import' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Pay calendars' })); expect(await screen.findByTestId('import-calendars')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Leave policies' })); expect(await screen.findByTestId('import-leave_types')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Super funds' })); expect(await screen.findByTestId('import-super_funds')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Departments & locations' }))
    expect(await screen.findByTestId('import-departments')).toBeInTheDocument(); expect(screen.getByTestId('import-locations')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Bulk import' })); expect(await screen.findByTestId('import-centre')).toBeInTheDocument()
  })
})

describe('api client', () => {
  it('uploads multipart with only file and dry_run (never user_id)', async () => {
    const spy = vi.spyOn(http, 'post').mockResolvedValue({ data: OK })
    const actual = await vi.importActual('../lib/payrollApi.js')
    const f = file('d.csv')
    await actual.importCsv('departments', f, true)
    const [url, body, cfg] = spy.mock.calls[0]
    expect(url).toBe('/payroll/imports/departments'); expect(body.get('file')).toBe(f); expect(body.get('dry_run')).toBe('true'); expect([...body.keys()].sort()).toEqual(['dry_run', 'file'])
    expect(cfg.headers['Content-Type']).toBe('multipart/form-data')
    await actual.importCsv('departments', f, false)
    expect(spy.mock.calls[1][1].get('dry_run')).toBe('false')
    spy.mockRestore()
  })
})
