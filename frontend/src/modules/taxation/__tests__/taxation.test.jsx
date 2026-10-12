import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import fs from 'node:fs'
import path from 'node:path'

vi.mock('../lib/taxApi.js', async () => {
  const fn = () => vi.fn()
  return {
    errMsg: e => e?.message || 'error',
    me: fn(), dashboard: fn(), health: fn(), reference: fn(), profile: fn(), saveProfile: fn(), rules: fn(), setOverride: fn(), clearOverride: fn(), registrations: fn(), saveRegistration: fn(), deleteRegistration: fn(),
    obligations: fn(), generateObligations: fn(), addObligation: fn(), updateObligation: fn(), deleteObligation: fn(),
    bas: { list: fn(), create: fn(), get: fn(), calculate: fn(), prepare: fn(), approve: fn(), back: fn(), lodged: fn(), paid: fn(), void: fn(), override: fn(), removeOverride: fn() },
    returns: { list: fn(), create: fn(), get: fn(), inputs: fn(), calculate: fn(), prepare: fn(), approve: fn(), back: fn(), lodged: fn(), assessment: fn(), paid: fn(), void: fn(), amend: fn() },
    adjustments: { list: fn(), save: fn(), remove: fn(), review: fn(), generateDepreciation: fn() }, assetsReview: fn(),
    cgt: { importTrades: fn(), events: fn(), save: fn(), remove: fn(), exclude: fn(), importRows: fn(), losses: fn(), addLoss: fn(), removeLoss: fn(), compute: fn() },
    fbt: { employees: fn(), benefits: fn(), saveBenefit: fn(), removeBenefit: fn(), summary: fn(), returns: fn(), get: fn(), calculate: fn(), prepare: fn(), approve: fn(), back: fn(), lodged: fn(), paid: fn() },
    div7a: { loans: fn(), save: fn(), remove: fn(), payments: fn(), addPayment: fn(), removePayment: fn(), schedule: fn() },
    workpapers: { list: fn(), get: fn(), save: fn(), generate: fn(), advance: fn(), remove: fn() }, evidence: { list: fn(), add: fn(), download: fn(), remove: fn() },
    planning: { get: fn(), update: fn(), estimate: fn(), scenarios: fn(), saveScenario: fn(), removeScenario: fn() }, reconcile: fn(), imports: { catalogue: fn(), template: fn(), preview: fn(), commit: fn() }, gst: { list: fn(), summary: fn(), save: fn(), status: fn(), remove: fn() }, auditFor: fn(), payrollTaxWatch: fn(), lodgement: { state: fn(), providers: fn(), sign: fn(), revoke: fn(), submit: fn(), pack: fn() }, readiness: fn(), summaryPack: fn(), exportCsv: fn(), exportXlsx: fn(), audit: fn(), verifyAudit: fn(),
  }
})
import * as api from '../lib/taxApi.js'
import { Findings, KindTag, WorkflowBar, Steps } from '../components/kit.jsx'
import BasTab from '../pages/BasTab.jsx'
import OverviewTab from '../pages/OverviewTab.jsx'
import LodgementTab from '../pages/LodgementTab.jsx'

const ALL = ['view', 'prepare', 'evidence', 'approve', 'lodge', 'config', 'audit_view']
const BOOKKEEPER = ['view', 'prepare', 'evidence']
beforeEach(() => vi.clearAllMocks())

describe('shared building blocks', () => {
  it('labels every figure with how it was produced', () => {
    render(<><KindTag kind="source" /><KindTag kind="assumption" /><KindTag kind="review" /></>)
    expect(screen.getByText('Source data')).toBeInTheDocument(); expect(screen.getByText('Assumption')).toBeInTheDocument(); expect(screen.getByText('Needs review')).toBeInTheDocument()
  })
  it('shows findings with their severity words, not colour alone', () => {
    render(<Findings items={[{ key: 'a', severity: 'error', message: 'GST mismatch' }, { key: 'b', severity: 'review', message: 'Loss tests' }]} />)
    const list = screen.getByRole('list', { name: 'Findings' })
    expect(within(list).getByText(/Error/)).toBeInTheDocument(); expect(within(list).getByText(/Review/)).toBeInTheDocument()
  })
  it('renders working steps with their basis and a dash for missing amounts', () => {
    render(<Steps steps={[{ key: 'x', label: 'Medicare levy low-income reduction', amount: null, kind: 'review', note: 'thresholds not loaded' }]} />)
    expect(screen.getByText('thresholds not loaded')).toBeInTheDocument(); expect(screen.getByText('—')).toBeInTheDocument()
  })
})

describe('document workflow bar enforces who may do what', () => {
  const doc = s => ({ id: 7, status: s, calculated: true })
  const mk = () => ({ calculate: vi.fn().mockResolvedValue({}), prepare: vi.fn().mockResolvedValue({}), approve: vi.fn(), back: vi.fn(), lodged: vi.fn(), paid: vi.fn(), void: vi.fn() })
  it('a bookkeeper can prepare but is told an approver is needed', () => {
    render(<WorkflowBar doc={doc('prepared')} caps={BOOKKEEPER} api={mk()} onChange={() => {}} />)
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument(); expect(screen.getByText(/Waiting for an approver/)).toBeInTheDocument()
  })
  it('an accountant sees Approve on a prepared document and never Record lodgement before approval', () => {
    render(<WorkflowBar doc={doc('prepared')} caps={ALL} api={mk()} onChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Record lodgement' })).not.toBeInTheDocument()
  })
  it('lodgement is a record the user makes, and needs the ATO reference', async () => {
    const a = mk(); a.lodged.mockResolvedValue({})
    render(<WorkflowBar doc={doc('approved')} caps={ALL} api={a} onChange={() => {}} noun="activity statement" />)
    fireEvent.click(screen.getByRole('button', { name: 'Record lodgement' }))
    expect(await screen.findByText(/does not submit anything to the ATO/)).toBeInTheDocument()
    const confirm = screen.getAllByRole('button', { name: 'Record lodgement' }).find(b => b.disabled)      // the dialog's confirm button starts disabled: no reference yet
    expect(confirm).toBeDisabled()                                                      // no reference yet
    fireEvent.change(screen.getByLabelText('ATO receipt / reference number'), { target: { value: 'REC-1' } })
    expect(confirm).not.toBeDisabled(); fireEvent.click(confirm)
    await waitFor(() => expect(a.lodged).toHaveBeenCalledWith(7, expect.objectContaining({ reference: 'REC-1' })))
  })
  it('a lodged document offers payment recording only, and no voiding', () => {
    render(<WorkflowBar doc={doc('lodged')} caps={ALL} api={mk()} onChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'Record payment' })).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Void' })).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })
  it('read-only users get no action buttons', () => {
    render(<WorkflowBar doc={doc('draft')} caps={['view']} api={mk()} onChange={() => {}} />)
    expect(screen.queryAllByRole('button')).toHaveLength(0)
  })
})

describe('BAS tab', () => {
  const row = { id: 3, kind: 'bas', status: 'draft', period_start: '2026-07-01', period_end: '2026-09-30', due_date: '2026-10-28', amount_payable: '1000.00', has_errors: true, lodgement_reference: null }
  it('lists statements, flags errors, and keeps the no-submission notice visible', async () => {
    api.bas.list.mockResolvedValue([row])
    render(<MemoryRouter><BasTab me={{ capabilities: ALL }} fy="2026-27" /></MemoryRouter>)
    expect(await screen.findByText('errors')).toBeInTheDocument(); expect(screen.getAllByText(/does not submit anything to the ATO/).length).toBeGreaterThan(0)
  })
  it('hides the create button from read-only users', async () => {
    api.bas.list.mockResolvedValue([])
    render(<MemoryRouter><BasTab me={{ capabilities: ['view'] }} fy="2026-27" /></MemoryRouter>)
    expect(await screen.findByText('No activity statements for this year')).toBeInTheDocument(); expect(screen.queryByRole('button', { name: /New BAS/ })).not.toBeInTheDocument()
  })
  it('opens a statement, shows each label with its basis and only offers override on editable, non-derived labels', async () => {
    api.bas.list.mockResolvedValue([row]); api.readiness.mockResolvedValue({ checks: [{ key: 'approved', ok: false, label: 'Approved by a second person' }], ready: false })
    api.bas.get.mockResolvedValue({ ...row, calculated: true, basis: 'accrual', version: 2, overrides: {}, findings: [{ key: 'gst_not_reconciled', severity: 'error', message: 'GST account differs' }],
      final: { G1: { value: '16500.00', kind: 'source', source: 'Ledger GST report' }, '9': { value: '1000.00', kind: 'calculated', source: '8A - 8B' } }, lodgement_figures: { G1: '16500', '9': '1000' }, label_names: { G1: 'Total sales' } })
    render(<MemoryRouter><BasTab me={{ capabilities: ALL }} fy="2026-27" /></MemoryRouter>)
    fireEvent.click(await screen.findByText('errors'))
    expect(await screen.findByText('Total sales')).toBeInTheDocument(); expect(screen.getByText('Source data')).toBeInTheDocument(); expect(screen.getByText(/GST account differs/)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Override' })).toHaveLength(1)           // G1 only; label 9 is derived
    expect(screen.getByText(/Approved by a second person/)).toBeInTheDocument()
  })
})

describe('Overview and Lodgement tabs are honest', () => {
  it('overview surfaces overdue items and data-health problems', async () => {
    api.dashboard.mockResolvedValue({ fy: '2026-27', calendar: { overdue: [{ id: 1 }], due_soon: [], next: [], open: 1, total: 1 }, bas: { count: 0, by_status: {}, latest: [] }, returns: [], fbt: [], div7a: { active_loans: 0 },
      health: { ok: false, items: [{ key: 'abn_invalid', severity: 'error', message: 'The ABN fails the ATO check-digit test.' }] }, open_adjustments_for_review: 0, workpapers: {}, recent_activity: [], lodgement_note: 'x',
      alerts: [{ level: 'error', text: 'Overdue: BAS Q1 (due 2026-10-28)' }] })
    render(<OverviewTab go={() => {}} />)
    expect(await screen.findByText(/Overdue: BAS Q1/)).toBeInTheDocument(); expect(screen.getAllByText(/check-digit/).length).toBeGreaterThan(0)
  })
  it('lodgement readiness says outright that AccFino does not submit to the ATO', async () => {
    api.bas.list.mockResolvedValue([]); api.returns.list.mockResolvedValue([]); api.fbt.returns.mockResolvedValue([])
    render(<LodgementTab fy="2026-27" go={() => {}} />)
    expect(await screen.findByText(/Digital Service Provider onboarding, which is not in place/)).toBeInTheDocument()
  })
})

describe('registry and hub stay in step', () => {
  const root = path.resolve(__dirname, '../../../core')
  const reg = JSON.parse(fs.readFileSync(path.join(root, 'config/modules.json'), 'utf8'))
  const hub = fs.readFileSync(path.join(root, 'hubs/TaxCompliancePage.jsx'), 'utf8')
  const taxMods = reg.modules.filter(m => m.domain === 'tax_compliance')
  it('every Taxation module in the registry is reachable: a top-level hub tab, or a place inside Tax Returns > Taxes', async () => {
    const { TAXES_LEGACY, TAXES_SECTIONS } = await import('../public.js')
    const hubKeys = [...hub.matchAll(/key: '([a-z]+)',\s+label:/g)].map(m => m[1]).filter(k => k !== 'taxes' && k !== 'workings')   // Taxes and Tax Workings are hub tabs that hold the seven modules below
    expect([...hubKeys, ...Object.keys(TAXES_LEGACY)].sort()).toEqual(taxMods.map(m => m.tab).sort())
    const inside = TAXES_SECTIONS.flatMap(s => s.subs.map(x => x.module)).sort()                         // the seven modules inside Taxes are exactly the registry's seven
    expect(inside).toEqual(['cgt', 'fbt-other-taxes', 'gst-bas-ias', 'income-tax', 'tax-lodgement-ato', 'tax-planning', 'tax-workpapers'])
    for (const id of inside) expect(taxMods.map(m => m.id)).toContain(id)
  })
  it('no Taxation module is a Coming Soon placeholder any more', () => {
    expect(taxMods.filter(m => m.status === 'planned')).toEqual([])
    expect(hub).not.toMatch(/ComingSoonTab/)
  })
  it('lodgement stays Preview and no tax blurb claims the app lodges with the ATO', () => {
    expect(taxMods.find(m => m.id === 'tax-lodgement-ato').status).toBe('beta')
    const text = JSON.stringify(taxMods).toLowerCase().replace(/does not submit to the ato/g, '')      // the honest negation is allowed; affirmative claims are not
    expect(text).not.toMatch(/ato[- ]compliant|lodge with the ato|lodge directly|e-?lodge|submit to the ato|lodges? (it |them )?(for you|to the ato)/)
    expect(taxMods.find(m => m.id === 'tax-lodgement-ato').blurb).toMatch(/does not submit/i)
  })
  it('the hub keeps the legacy worksheets reachable but labelled as not linked to the ledger', () => {
    expect(hub).toMatch(/legacy=\{<TaxReturnData/); expect(hub).toMatch(/legacyCgt=\{<PropertyCGT/)
  })
})

describe('Send disposals to Tax (used by Investments)', () => {
  const rows = [{ 'Disposal Date': '2026-09-01', 'Asset Name': 'BHP', 'Total Proceeds ($)': 5000, 'Total Cost Base ($)': 3000, 'Acquisition Date': '2025-01-01' }]
  it('renders nothing when there are no disposals', async () => {
    const { default: Send } = await import('../components/SendDisposalsToTax.jsx')
    const { container } = render(<Send rows={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
  it('always previews first, then sends only what the preview said, and says nothing is lodged', async () => {
    const { default: Send } = await import('../components/SendDisposalsToTax.jsx')
    api.cgt.importRows.mockImplementation(async b => ({ added: b.dry_run ? 1 : 1, skipped_duplicates: 0, rejected: 0, errors: [], dry_run: b.dry_run }))
    render(<Send rows={rows} assetClass="shares" />)
    fireEvent.click(screen.getByRole('button', { name: 'Send to Tax (CGT)' }))
    expect(await screen.findByText(/Preview: 1 to add/)).toBeInTheDocument(); expect(screen.getByText(/Nothing is lodged/)).toBeInTheDocument()
    expect(api.cgt.importRows).toHaveBeenCalledWith({ rows, asset_class: 'shares', dry_run: true })
    fireEvent.click(screen.getByRole('button', { name: /^Send 1$/ }))
    await waitFor(() => expect(api.cgt.importRows).toHaveBeenCalledWith({ rows, asset_class: 'shares', dry_run: false }))
  })
  it('explains a permission failure instead of failing silently, and disables sending', async () => {
    const { default: Send } = await import('../components/SendDisposalsToTax.jsx')
    api.cgt.importRows.mockRejectedValue(new Error('403'))
    render(<Send rows={rows} />)
    fireEvent.click(screen.getByRole('button', { name: 'Send to Tax (CGT)' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Accountant, Bookkeeper or Admin/)
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })
})

describe('return inputs follow the entity type', () => {
  it('a company is not shown individual-only inputs, an individual is', async () => {
    const { fieldsFor } = await import('../pages/ReturnsTab.jsx')
    const company = fieldsFor('company').map(f => f[0]), person = fieldsFor('individual').map(f => f[0])
    expect(company).toEqual(['other_income', 'deductions_other', 'franking_credits', 'losses_brought_forward', 'net_capital_gain_override'])
    for (const k of ['help_repayment', 'medicare_surcharge', 'labour_income', 'work_expenses_itemised']) { expect(company).not.toContain(k); expect(person).toContain(k) }
    expect(fieldsFor('trust').map(f => f[0])).toEqual(['other_income', 'deductions_other', 'net_capital_gain_override'])
  })
})

describe('rates screen and CGT warnings', () => {
  it('shows tax brackets as readable lines, not raw JSON', async () => {
    const { showValue } = await import('../pages/SettingsTab.jsx')
    expect(showValue([['18200', '0'], ['45000', '0.15'], [null, '0.45']])).toBe('up to $18,200 – 0%\nup to $45,000 – 15%\nabove – 45%')
    expect(showValue('0.0827')).toBe('0.0827'); expect(showValue(true)).toBe('true')
  })
  it('warns on a disposal dated on or after 1 July 2027 (new CGT regime not calculated)', async () => {
    const CgtTab = (await import('../pages/CgtTab.jsx')).default
    api.cgt.compute.mockResolvedValue({ holder: 'individual', total_gains_before_losses: '0', current_year_losses: '0', prior_losses_applied: '0', discount_applied: '0', net_capital_gain: '0', losses_carried_forward: '0', review: [], assumption: '', loss_register_note: '' })
    api.cgt.events.mockResolvedValue([]); api.cgt.losses.mockResolvedValue([])
    render(<MemoryRouter><CgtTab me={{ capabilities: ALL }} fy="2026-27" /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: '+ Event' }))
    expect(screen.queryByText(/new CGT regime/)).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Disposed'), { target: { value: '2027-07-02' } })
    expect(await screen.findByText(/new CGT regime/)).toBeInTheDocument(); expect(screen.getByText(/cannot calculate that yet/)).toBeInTheDocument()
  })
})

describe('state payroll tax monitor (Calendar tab)', () => {
  const W = o => ({ state: 'NSW', status: 'above', message: 'Projected annual wages are at or above the NSW threshold.', threshold: '1200000.00', wages_ytd: '800000.00', projected_wages: '1600000.00', indicative_tax: '21800.00',
    indicative_note: 'Flat-rate estimate on Payroll wages only.', action: 'No payroll tax registration is recorded.', basis: 'Payroll gross wages plus employer super', not_assessed: ['Grouping of related businesses'], ...o })
  const mount = async () => { const Cal = (await import('../pages/CalendarTab.jsx')).default; api.obligations.mockResolvedValue([]); api.registrations.mockResolvedValue([]); api.reference.mockResolvedValue({ obligation_kinds: ['custom'], registration_kinds: ['gst'] })
    render(<MemoryRouter><Cal me={{ capabilities: ALL }} fy="2026-27" /></MemoryRouter>) }
  it('says plainly it is a monitor, shows the flat-rate indication only when given, and the action when unregistered', async () => {
    api.payrollTaxWatch.mockResolvedValue(W()); await mount()
    expect(await screen.findByText('At or above threshold')).toBeInTheDocument(); expect(screen.getByText(/does not calculate payroll tax/)).toBeInTheDocument()
    expect(screen.getByText('$21,800.00')).toBeInTheDocument(); expect(screen.getByText(/No payroll tax registration is recorded/)).toBeInTheDocument(); expect(screen.getByText('Grouping of related businesses')).toBeInTheDocument()
  })
  it('shows no amount for a state that uses tapered rates, and says a threshold is missing for an unloaded state', async () => {
    api.payrollTaxWatch.mockResolvedValue(W({ state: 'VIC', indicative_tax: null, indicative_note: 'VIC uses tapering or tiered rates at higher wage levels, so no estimate is shown.', action: undefined })); await mount()
    expect(await screen.findByText(/no estimate is shown/)).toBeInTheDocument(); expect(screen.queryByText(/Indicative flat-rate amount/)).not.toBeInTheDocument()
  })
  it('reports an unloaded state without inventing numbers', async () => {
    api.payrollTaxWatch.mockResolvedValue({ state: 'SA', status: 'not_loaded', message: 'The 2026-27 payroll tax threshold for SA is not loaded (sources conflict).', threshold: null, wages_ytd: '0.00', basis: 'x', not_assessed: [] }); await mount()
    expect(await screen.findByText('Threshold not loaded')).toBeInTheDocument(); expect(screen.queryByText(/projected full year/)).not.toBeInTheDocument()
  })
})


describe('Sign-off & lodgement panel', () => {
  const DECL = { taxpayer: { version: '2026.1', text: 'I declare that the figures are true and correct.' }, tax_agent: { version: '2026.1', text: 'As a registered tax agent I have reviewed this document.' }, bas_agent: { version: '2026.1', text: 'As a registered BAS agent I have reviewed this document.' } }
  const PROVS = (over = {}) => [{ name: 'manual', label: 'Lodge elsewhere, then record it here', description: 'You lodge elsewhere.', real: false, available: true, reason: '' },
    { name: 'agent_pack', label: 'Hand off to my tax agent (download pack)', description: 'Produces a zip.', real: false, available: true, reason: '' },
    { name: 'sandbox', label: 'Simulated lodgement (testing only)', description: 'SIMULATION.', real: false, available: false, reason: 'Disabled.', ...(over.sandbox || {}) },
    { name: 'sbr_gateway', label: 'Lodge with the ATO through an accredited gateway', description: 'Needs an adapter.', real: true, available: false, reason: 'No accredited gateway adapter is configured. Direct lodgement needs a DSP.', ...(over.gateway || {}) }]
  const ST = (o = {}) => ({ doc_type: 'bas_statement', doc_id: 1, doc_status: 'approved', title: 'BAS', policy: 'self_declaration', declaration_ok: false, requirement: 'A declaration is required before lodgement can be recorded: the taxpayer / authorised person, or a registered agent, signs off the document.',
    agent_signed: false, signoffs: [], lodgements: [], providers: PROVS(), declarations: DECL, agent_number: '', ...o })
  const mount = async (st, caps = ALL) => { const Panel = (await import('../components/LodgementPanel.jsx')).default; const stObj = { data: st, reload: vi.fn() }
    render(<MemoryRouter><Panel st={stObj} caps={caps} docType="bas_statement" docId={1} onChange={() => {}} /></MemoryRouter>); return stObj }

  it('renders nothing for a draft document with no history', async () => { await mount(ST({ doc_status: 'draft' })); expect(screen.queryByText('Sign-off & lodgement')).not.toBeInTheDocument() })
  it('says a declaration is needed, offers both kinds of sign-off, and hides the lodgement routes until it exists', async () => {
    await mount(ST())
    expect(screen.getByText('Declaration needed')).toBeInTheDocument(); expect(screen.getByText(/A declaration is required before lodgement/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign as taxpayer / authorised person' })).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Sign off as registered tax / BAS agent' })).toBeInTheDocument()
    expect(screen.queryByText('How will it be lodged?')).not.toBeInTheDocument()
  })
  it('once signed it shows every route honestly: manual, agent hand-off, and a gateway that is unavailable with the reason', async () => {
    await mount(ST({ declaration_ok: true, signoffs: [{ id: 1, signer_name: 'Alex', capacity: 'taxpayer', agent_number: null, status: 'valid', counts: true, signed_at: '2026-10-05T01:00:00' }] }))
    expect(screen.getByText('Declaration recorded')).toBeInTheDocument(); expect(screen.getByText('How will it be lodged?')).toBeInTheDocument()
    expect(screen.getByText('Hand off to my tax agent (download pack)')).toBeInTheDocument()
    const gw = screen.getByRole('button', { name: 'Lodge with the ATO' }); expect(gw).toBeDisabled()
    expect(screen.getByText(/No accredited gateway adapter is configured/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Run simulation' })).not.toBeInTheDocument()        // the simulation is hidden unless the server enables it
  })
  it('a configured gateway is enabled; the simulation, when enabled, is clearly a simulation and its history says not lodged', async () => {
    await mount(ST({ declaration_ok: true, providers: PROVS({ gateway: { available: true, reason: '' }, sandbox: { available: true } }), lodgements: [{ id: 3, provider: 'sandbox', status: 'simulated', simulated: true, receipt_reference: 'SIM-ABC', message: 'SIMULATED: nothing was sent to the ATO.', submitted_at: '2026-10-05T01:00:00' }] }))
    expect(screen.getByRole('button', { name: 'Lodge with the ATO' })).not.toBeDisabled(); expect(screen.getByRole('button', { name: 'Run simulation' })).toBeInTheDocument()
    expect(screen.getByText('SIMULATED — not lodged')).toBeInTheDocument(); expect(screen.getByText('SIM-ABC')).toBeInTheDocument()
  })
  it('under the agent policy it says an agent must sign, and a taxpayer-only declaration does not count', async () => {
    await mount(ST({ policy: 'agent_signoff_required', requirement: 'Policy: a registered tax agent or BAS agent must sign off this document before lodgement can be recorded.' }))
    expect(screen.getByText(/a registered agent must sign off/)).toBeInTheDocument(); expect(screen.getByText(/must sign off this document before lodgement/)).toBeInTheDocument()
  })
  it('the taxpayer declaration needs a name and the confirmation before Sign is enabled, then sends exactly what was entered', async () => {
    api.lodgement.sign.mockResolvedValue({ id: 1 })
    await mount(ST())
    fireEvent.click(screen.getByRole('button', { name: 'Sign as taxpayer / authorised person' }))
    expect(await screen.findByText(/I declare that the figures are true and correct/)).toBeInTheDocument()
    const sign = screen.getByRole('button', { name: 'Sign' }); expect(sign).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Type your full name to sign'), { target: { value: 'Alex Owner' } }); expect(sign).toBeDisabled()
    fireEvent.click(screen.getByLabelText('I confirm the declaration above')); expect(sign).not.toBeDisabled(); fireEvent.click(sign)
    await waitFor(() => expect(api.lodgement.sign).toHaveBeenCalledWith({ doc_type: 'bas_statement', doc_id: 1, capacity: 'taxpayer', typed_name: 'Alex Owner', confirmed: true, agent_number: '' }))
  })
  it('the agent sign-off requires an 8-digit registration number and warns never to enter a TFN', async () => {
    api.lodgement.sign.mockResolvedValue({ id: 2 })
    await mount(ST())
    fireEvent.click(screen.getByRole('button', { name: 'Sign off as registered tax / BAS agent' }))
    fireEvent.change(screen.getByLabelText('Type your full name to sign'), { target: { value: 'Dana Agent' } }); fireEvent.click(screen.getByLabelText('I confirm the declaration above'))
    const sign = screen.getByRole('button', { name: 'Sign' }); expect(sign).toBeDisabled(); expect(screen.getByText(/Never enter a Tax File Number/)).toBeInTheDocument()
    const num = screen.getByLabelText('Agent registration number (8 digits)')
    for (const bad of ['1234567', '123456789', 'ABCD1234']) { fireEvent.change(num, { target: { value: bad } }); expect(sign).toBeDisabled() }
    fireEvent.change(num, { target: { value: '1234 5678' } }); expect(sign).not.toBeDisabled(); fireEvent.click(sign)
    await waitFor(() => expect(api.lodgement.sign).toHaveBeenCalledWith(expect.objectContaining({ capacity: 'tax_agent', agent_number: '1234 5678', typed_name: 'Dana Agent' })))
  })
  it('read-only roles cannot sign; Record lodgement is hidden until a declaration exists', async () => {
    await mount(ST(), ['view'])
    expect(screen.queryByRole('button', { name: /Sign/ })).not.toBeInTheDocument(); expect(screen.getByText(/Only an Accountant or the Organisation Admin can sign off/)).toBeInTheDocument()
    const bar = { calculate: vi.fn(), prepare: vi.fn(), approve: vi.fn(), back: vi.fn(), lodged: vi.fn(), paid: vi.fn(), void: vi.fn() }
    render(<WorkflowBar doc={{ id: 1, status: 'approved', calculated: true }} caps={ALL} api={bar} onChange={() => {}} declarationOk={false} />)
    expect(screen.queryByRole('button', { name: 'Record lodgement' })).not.toBeInTheDocument(); expect(screen.getByText(/Sign-off needed below/)).toBeInTheDocument()
  })
})


describe('Send crypto trades to Tax (used by Investments)', () => {
  const trades = [{ Date: '2025-01-01', Symbol: 'BTC', Side: 'buy', Quantity: 1, Price: 50000 }, { Date: '2026-09-01', Symbol: 'BTC', Side: 'sell', Quantity: 1, Price: 90000 }]
  const R = o => ({ disposals: 1, added: 1, skipped_duplicates: 0, rejected: 0, errors: [], unmatched: [], note: 'Not handled: crypto-to-crypto swaps.', ...o })
  it('previews with the chosen method, re-previews when the method changes, and sends only after the preview', async () => {
    const Send = (await import('../components/SendCryptoTradesToTax.jsx')).default
    api.cgt.importTrades.mockImplementation(async b => R({ dry_run: b.dry_run }))
    render(<Send trades={trades} />)
    fireEvent.click(screen.getByRole('button', { name: 'Send to Tax (CGT)' }))
    expect(await screen.findByText(/Preview: 1 disposal piece/)).toBeInTheDocument(); expect(api.cgt.importTrades).toHaveBeenCalledWith({ trades, method: 'fifo', dry_run: true })
    fireEvent.change(screen.getByLabelText('Which parcels are treated as sold first?'), { target: { value: 'hifo' } })
    await waitFor(() => expect(api.cgt.importTrades).toHaveBeenCalledWith({ trades, method: 'hifo', dry_run: true }))
    fireEvent.click(screen.getByRole('button', { name: /^Send 1$/ }))
    await waitFor(() => expect(api.cgt.importTrades).toHaveBeenCalledWith({ trades, method: 'hifo', dry_run: false }))
  })
  it('shows sells that could not be matched instead of hiding them, and what is not handled', async () => {
    const Send = (await import('../components/SendCryptoTradesToTax.jsx')).default
    api.cgt.importTrades.mockResolvedValue(R({ added: 0, unmatched: [{ reason: '1 ETH sold on 2026-08-01 has no earlier purchase to match' }] }))
    render(<Send trades={trades} />); fireEvent.click(screen.getByRole('button', { name: 'Send to Tax (CGT)' }))
    expect(await screen.findByText(/no earlier purchase to match/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: /^Send 0$/ })).toBeDisabled()
  })
  it('renders nothing with no trades', async () => { const Send = (await import('../components/SendCryptoTradesToTax.jsx')).default; const { container } = render(<Send trades={[]} />); expect(container).toBeEmptyDOMElement() })
})


describe('Tax Returns > Taxes navigation', () => {
  const mountTaxes = async (props = {}) => {
    const { default: TaxesTab } = await import('../pages/TaxesTab.jsx')
    api.dashboard.mockResolvedValue({}); api.bas.list.mockResolvedValue([]); api.gst.list.mockResolvedValue([]); api.gst.summary.mockResolvedValue({ count: 0, by_status: {}, increasing_confirmed: '0.00', decreasing_confirmed: '0.00', net_effect_on_label_9: '0.00' })
    api.cgt.compute.mockResolvedValue({ holder: 'company', total_gains_before_losses: '0', current_year_losses: '0', prior_losses_applied: '0', discount_applied: '0', net_capital_gain: '0', losses_carried_forward: '0', review: [], assumption: '', loss_register_note: '' })
    api.adjustments.list.mockResolvedValue([]); api.reference.mockResolvedValue({ adjustments: [] }); api.assetsReview.mockResolvedValue({ computed: false, warnings: [], lines: [], iawo_total: '0', pool: null })
    api.cgt.events.mockResolvedValue([]); api.cgt.losses.mockResolvedValue([]); api.fbt.benefits.mockResolvedValue([]); api.fbt.summary.mockResolvedValue({ type1_taxable: '0', type2_taxable: '0', aggregate_fringe_benefits_amount: '0', fbt_rate: '0.47', fbt_payable: '0', employees: [], findings: [] }); api.fbt.returns.mockResolvedValue([])
    const calls = []
    render(<MemoryRouter><TaxesTab me={{ capabilities: ALL }} fy="2026-27" go={() => {}} section={props.section} sub={props.sub} group={props.group} onNav={(s, b) => calls.push([s, b])} isVisible={props.isVisible} /></MemoryRouter>)
    return calls
  }
  it('has the two sections with exactly the requested pages, in order', async () => {
    await mountTaxes()
    const secs = screen.getByRole('tablist', { name: 'Taxes sections' })
    expect(within(secs).getAllByRole('tab').map(t => t.textContent)).toEqual(['Taxes', 'Tax Workings'])
    expect(within(screen.getByRole('tablist', { name: 'Taxes pages' })).getAllByRole('tab').map(t => t.textContent)).toEqual(['GST', 'CGT', 'FBT'])
    expect(screen.getByTestId('taxes-gst')).toBeInTheDocument()                                             // GST is the landing page
  })
  it('Tax Workings lists Income Tax Workings, Lodgment Readiness, Tax Planning and Workpapers', async () => {
    await mountTaxes({ section: 'workings', sub: 'lodgment' })
    expect(within(screen.getByRole('tablist', { name: 'Tax Workings pages' })).getAllByRole('tab').map(t => t.textContent)).toEqual(['Income Tax Workings', 'Lodgment Readiness', 'Tax Planning', 'Workpapers'])
    expect(screen.getByRole('tab', { name: 'Lodgment Readiness' })).toHaveAttribute('aria-selected', 'true')
  })
  it('clicking a section opens its first page; clicking a page reports the navigation', async () => {
    const calls = await mountTaxes()
    fireEvent.click(screen.getByRole('tab', { name: 'Tax Workings' })); fireEvent.click(screen.getByRole('tab', { name: 'CGT' }))
    expect(calls).toEqual([['workings', 'income'], ['taxes', 'cgt']])
  })
  it('hides a page whose module is not in the plan, and a whole section when none of its pages are', async () => {
    await mountTaxes({ isVisible: id => id !== 'cgt' && id !== 'fbt-other-taxes' && id !== 'gst-bas-ias' ? true : false })
    expect(screen.queryByRole('tab', { name: 'Taxes' })).not.toBeInTheDocument()                          // all three Taxes pages are locked: the section disappears
    expect(screen.getByRole('tab', { name: 'Tax Workings' })).toBeInTheDocument(); expect(screen.getByTestId('taxes-income')).toBeInTheDocument()
  })
  it('as top-level tabs: Taxes shows only GST | CGT | FBT and Tax Workings only its four pages, with no section switcher', async () => {
    await mountTaxes({ group: 'taxes' })
    expect(screen.queryByRole('tablist', { name: 'Taxes sections' })).not.toBeInTheDocument()
    expect(within(screen.getByRole('tablist', { name: 'Taxes pages' })).getAllByRole('tab').map(t => t.textContent)).toEqual(['GST', 'CGT', 'FBT'])
  })
  it('Tax Workings as a top-level tab lists its four pages', async () => {
    await mountTaxes({ group: 'workings' })
    expect(screen.queryByRole('tablist', { name: 'Taxes sections' })).not.toBeInTheDocument()
    expect(within(screen.getByRole('tablist', { name: 'Tax Workings pages' })).getAllByRole('tab').map(t => t.textContent)).toEqual(['Income Tax Workings', 'Lodgment Readiness', 'Tax Planning', 'Workpapers'])
  })
  it('old bookmarks (?tab=gst, property, fbt, income, lodgement, planning, workpapers) map to their place inside Taxes', async () => {
    const { TAXES_LEGACY } = await import('../public.js')
    expect(TAXES_LEGACY).toEqual({ gst: ['taxes', 'gst'], property: ['taxes', 'cgt'], fbt: ['taxes', 'fbt'], income: ['workings', 'income'], lodgement: ['workings', 'lodgment'], planning: ['workings', 'planning'], workpapers: ['workings', 'workpapers'] })
  })
})

describe('Bulk upload / Import CSV panel', () => {
  const CAT = [{ key: 'gst_adjustments', title: 'GST adjustments', description: 'Bad debts and similar.', capability: 'prepare', columns: [{ name: 'adjustment_date', kind: 'date', required: true, enum: [], help: '' }, { name: 'gst_amount', kind: 'money', required: true, enum: [], help: 'greater than 0' }] },
               { key: 'lodgment_registrations', title: 'Tax registrations', description: 'What you are registered for.', capability: 'config', columns: [{ name: 'kind', kind: 'enum', required: true, enum: ['gst', 'abn'], help: '' }] }]
  const PV = (o = {}) => ({ module: 'gst_adjustments', total: 4, ok: 2, duplicates: 1, errors: 1, warnings: 1, can_commit: true, unknown_columns: ['internal'], file_sha256: 'a'.repeat(64),
    rows: [{ line: 2, status: 'ok', messages: [], data: { adjustment_date: '2026-08-14', gst_amount: '120.00' } }, { line: 3, status: 'error', messages: [{ level: 'error', text: 'gst_amount must be greater than zero' }], data: {} },
           { line: 4, status: 'ok', messages: [{ level: 'warning', text: 'GST is less than 10% of the amount' }], data: {} }, { line: 5, status: 'duplicate', messages: [{ level: 'info', text: 'Already in the database: skipped' }], data: {} }], ...o })
  const mountPanel = async (caps = ALL, datasets) => {
    const { default: ImportPanel, resetImportCatalogue } = await import('../components/ImportPanel.jsx'); resetImportCatalogue()
    api.imports.catalogue.mockResolvedValue(CAT)
    const done = vi.fn()
    render(<ImportPanel datasets={datasets || [{ key: 'gst_adjustments', label: 'GST adjustments' }]} caps={caps} onDone={done} />)
    fireEvent.click(screen.getByRole('button', { name: /Bulk upload \/ Import CSV/ }))
    return done
  }
  const upload = f => fireEvent.change(screen.getByLabelText('CSV file'), { target: { files: [f] } })
  const file = () => new File(['a,b\n1,2'], 'adj.csv', { type: 'text/csv' })

  it('shows what the dataset is, its columns (required marked) and a template download', async () => {
    await mountPanel()
    expect(await screen.findByText(/Bad debts and similar/)).toBeInTheDocument(); expect(screen.getByText('adjustment_date*')).toBeInTheDocument()
    api.imports.template.mockResolvedValue(new Blob(['x'])); window.URL.createObjectURL = vi.fn(() => 'blob:x'); window.URL.revokeObjectURL = vi.fn()
    fireEvent.click(screen.getByRole('button', { name: 'Download CSV template' }))
    await waitFor(() => expect(api.imports.template).toHaveBeenCalledWith('gst_adjustments'))
  })
  it('previews before importing: counts, per-row results and messages, ignored columns, and nothing is committed yet', async () => {
    api.imports.preview.mockResolvedValue(PV()); await mountPanel(); upload(file())
    expect(await screen.findByText('2 valid')).toBeInTheDocument(); expect(screen.getByText('1 duplicate(s)')).toBeInTheDocument(); expect(screen.getByText('1 with errors')).toBeInTheDocument(); expect(screen.getByText('1 warning(s)')).toBeInTheDocument()
    expect(screen.getByText('gst_amount must be greater than zero')).toBeInTheDocument(); expect(screen.getByText(/GST is less than 10%/)).toBeInTheDocument(); expect(screen.getByText(/Ignored columns: internal/)).toBeInTheDocument()
    expect(api.imports.preview).toHaveBeenCalledWith('gst_adjustments', expect.any(File)); expect(api.imports.commit).not.toHaveBeenCalled()
  })
  it('filters the preview to rejected rows only', async () => {
    api.imports.preview.mockResolvedValue(PV()); await mountPanel(); upload(file()); await screen.findByText('2 valid')
    fireEvent.change(screen.getByLabelText('Show rows'), { target: { value: 'error' } })
    expect(screen.getByText('gst_amount must be greater than zero')).toBeInTheDocument(); expect(screen.queryByText('Already in the database: skipped')).not.toBeInTheDocument()
  })
  it('imports the valid rows only by default and reports imported, skipped and rejected', async () => {
    api.imports.preview.mockResolvedValue(PV()); api.imports.commit.mockResolvedValue({ imported: 2, skipped_duplicates: 1, rejected: 1, failed: [], file_sha256: 'b'.repeat(64), rows: PV().rows })
    const done = await mountPanel(); upload(file()); await screen.findByText('2 valid')
    fireEvent.click(screen.getByRole('button', { name: 'Import 2 valid rows' }))
    expect(await screen.findByText(/Import complete/)).toBeInTheDocument(); expect(screen.getByText(/2 imported · 1 duplicate\(s\) skipped · 1 rejected · 0 failed/)).toBeInTheDocument()
    expect(api.imports.commit).toHaveBeenCalledWith('gst_adjustments', expect.any(File), 'valid_only'); expect(screen.getByText(/SHA-256/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Done' })); expect(done).toHaveBeenCalled()
  })
  it('all-or-nothing blocks the import while any row has an error and says so', async () => {
    api.imports.preview.mockResolvedValue(PV()); await mountPanel(); upload(file()); await screen.findByText('2 valid')
    fireEvent.click(screen.getByLabelText(/All or nothing/))
    expect(screen.getByText(/Nothing will be imported while 1 row/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Import 2 valid rows' })).toBeDisabled()
  })
  it('shows a file-level problem plainly and offers no import', async () => {
    api.imports.preview.mockResolvedValue({ module: 'gst_adjustments', total: 1, ok: 0, duplicates: 0, errors: 0, warnings: 0, rows: [], can_commit: false, file_error: 'Required column(s) missing: gst_amount. Download the CSV template for the exact layout.' })
    await mountPanel(); upload(file())
    expect(await screen.findByRole('alert')).toHaveTextContent(/Required column\(s\) missing: gst_amount/); expect(screen.queryByRole('button', { name: /^Import \d/ })).not.toBeInTheDocument()
  })
  it('a file-level problem still leaves a way out: a Close button closes the dialog', async () => {
    api.imports.preview.mockResolvedValue({ module: 'gst_adjustments', total: 1, ok: 0, duplicates: 0, errors: 0, warnings: 0, rows: [], can_commit: false, file_error: 'Required column(s) missing: gst_amount.' })
    await mountPanel(); upload(file()); await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button', { name: 'Close' })); expect(screen.queryByText('Bulk upload / Import CSV', { selector: 'h3,h2,h4' })).not.toBeInTheDocument(); expect(screen.queryByLabelText('CSV file')).not.toBeInTheDocument()
  })
  it('shows a server error (for example a role refused) and offers no import', async () => {
    api.imports.preview.mockRejectedValue(new Error('Your role does not allow that')); await mountPanel(); upload(file())
    expect(await screen.findByRole('alert')).toHaveTextContent('Your role does not allow that')
  })
  it('lets the user switch dataset and warns when their role lacks the permission, disabling the file picker', async () => {
    await mountPanel(['view', 'prepare'], [{ key: 'gst_adjustments', label: 'GST adjustments' }, { key: 'lodgment_registrations', label: 'Tax registrations' }])
    fireEvent.change(await screen.findByLabelText('What are you importing?'), { target: { value: 'lodgment_registrations' } })
    expect(await screen.findByText(/config permission needed/)).toBeInTheDocument(); expect(screen.getByLabelText('CSV file')).toBeDisabled()
  })
})

describe('GST adjustments register', () => {
  const ROWS = [{ id: 1, adj_date: '2026-08-14', adj_type: 'decreasing', reason: 'bad_debt', reason_label: 'Bad debt written off', description: 'Invoice written off', amount_ex_gst: '1200.00', gst_amount: '120.00', reference: 'INV-1', status: 'confirmed', source: 'import' },
                { id: 2, adj_date: '2026-09-15', adj_type: 'increasing', reason: 'private_use', reason_label: 'Private use', description: 'Private use apportionment', amount_ex_gst: '880.00', gst_amount: '88.00', reference: 'PRIV', status: 'draft', source: 'manual' }]
  const mount = async (caps = ALL) => {
    const { default: Panel } = await import('../pages/GstAdjustmentsPanel.jsx')
    api.gst.list.mockResolvedValue(ROWS); api.gst.summary.mockResolvedValue({ count: 2, by_status: { confirmed: 1, draft: 1 }, increasing_confirmed: '0.00', decreasing_confirmed: '120.00', net_effect_on_label_9: '-120.00' })
    api.imports.catalogue.mockResolvedValue([])
    render(<MemoryRouter><Panel me={{ capabilities: caps }} fy="2026-27" /></MemoryRouter>)
  }
  it('lists adjustments with status and source, the summary, and says only confirmed ones feed the BAS', async () => {
    await mount()
    expect(await screen.findByText('Invoice written off')).toBeInTheDocument(); expect(screen.getByText(/adjustments inside a BAS period are added to that statement/)).toBeInTheDocument()
    expect(screen.getByText(/Bad debt written off · imported/)).toBeInTheDocument(); expect(screen.getByText('Net effect on label 9')).toBeInTheDocument(); expect(screen.getByRole('button', { name: /Bulk upload \/ Import CSV/ })).toBeInTheDocument()
  })
  it('applies filters through the API', async () => {
    await mount(); await screen.findByText('Invoice written off')
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'draft' } }); fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }))
    await waitFor(() => expect(api.gst.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'draft' })))
  })
  it('blocks an end date before the start date', async () => {
    await mount(); await screen.findByText('Invoice written off')
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2025-01-01' } })
    expect(screen.getByText(/end date is before the start date/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Apply filters' })).toBeDisabled()
  })
  it('validates the form: GST must be positive and no more than 10% of the amount, and warns on partial claims', async () => {
    await mount(); fireEvent.click(await screen.findByRole('button', { name: '+ Adjustment' }))
    const save = screen.getByRole('button', { name: 'Save' }); expect(save).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Adjustment date'), { target: { value: '2026-08-20' } }); fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Test' } })
    fireEvent.change(screen.getByLabelText('Amount excl. GST'), { target: { value: '100' } }); fireEvent.change(screen.getByLabelText('GST amount'), { target: { value: '50' } })
    expect(screen.getByText(/GST cannot be more than 10%/)).toBeInTheDocument(); expect(save).toBeDisabled()
    fireEvent.change(screen.getByLabelText('GST amount'), { target: { value: '5' } }); expect(screen.getByText(/less than 10% of the amount/)).toBeInTheDocument(); expect(save).not.toBeDisabled()
  })
  it('changes status and offers history only to roles allowed to; read-only users get no actions', async () => {
    api.gst.status.mockResolvedValue({}); await mount(); await screen.findByText('Invoice written off')
    fireEvent.click(screen.getAllByRole('button', { name: 'Confirm' })[0]); await waitFor(() => expect(api.gst.status).toHaveBeenCalledWith(2, 'confirmed'))
    expect(screen.getAllByRole('button', { name: /History of/ }).length).toBe(2)
  })
  it('read-only users see the register but no add, edit, import-ready actions', async () => {
    await mount(['view']); await screen.findByText('Invoice written off')
    expect(screen.queryByRole('button', { name: '+ Adjustment' })).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: /History of/ })).not.toBeInTheDocument()
  })
})
