import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }))
vi.mock('recharts', () => { const Box = ({ children }) => <div data-testid="chart">{children}</div>; return { ResponsiveContainer: Box, LineChart: Box, Line: () => null, CartesianGrid: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null, Legend: () => null } })
vi.mock('../lib/lendApi.js', () => {
  const fn = vi.fn
  return {
    errMsg: e => e?.message || 'Error', me: fn(), reference: fn(), dashboard: fn(), bankAccounts: fn(), ledgerAccounts: fn(), settings: { get: fn(), save: fn() },
    applicants: { list: fn(), create: fn(), get: fn(), saveProfile: fn(), addCommitment: fn(), updateCommitment: fn(), removeCommitment: fn() },
    analyses: { list: fn(), get: fn(), lines: fn(), upload: fn(), fromBooks: fn(), reanalyse: fn(), override: fn(), suggestions: fn() },
    applications: { list: fn(), create: fn(), get: fn(), update: fn(), assess: fn(), status: fn(), decide: fn(), requestDoc: fn(), uploadDoc: fn(), downloadDoc: fn(), removeDoc: fn(), settle: fn() },
    loans: { list: fn(), create: fn(), get: fn(), schedule: fn(), repay: fn(), postRepayment: fn(), voidRepayment: fn(), rateChange: fn(), refinance: fn(), setStatus: fn() },
    collections: { register: fn(), caseFor: fn(), activity: fn(), arrange: fn(), closeArrangement: fn(), hardship: fn(), hardshipAction: fn() },
    treasury: { position: fn(), facilities: fn(), saveFacility: fn(), items: fn(), saveItem: fn() },
  }
})
import * as L from '../lib/lendApi.js'
import AssessmentPanel from '../components/assessment.jsx'
import ApplicantsTab, { AnalysisView } from '../pages/ApplicantsTab.jsx'
import OriginationTab from '../pages/OriginationTab.jsx'
import CreditTab from '../pages/CreditTab.jsx'
import LoansTab from '../pages/LoansTab.jsx'
import CollectionsTab from '../pages/CollectionsTab.jsx'
import TreasuryTab from '../pages/TreasuryTab.jsx'
import Overview from '../pages/Overview.jsx'

const ALL = ['view', 'edit', 'upload', 'assess', 'approve', 'override', 'settle', 'collect', 'configure', 'delete']
const BOOKKEEPER = ['view', 'edit', 'upload', 'assess', 'collect']
const ME = { capabilities: ALL }
const W = ui => render(<MemoryRouter>{ui}</MemoryRouter>)
const REF = { households: ['single_no_children', 'couple_no_children'], employment: ['paye_full_time'], commitment_kinds: ['car_loan', 'credit_card'], loan_types: ['term_loan', 'home_loan'], frequencies: ['weekly', 'monthly'], categories: ['Income', 'Rent', 'Gambling'], collection_kinds: ['call', 'promise_to_pay', 'note'], facility_types: ['line_of_credit'],
  factors: [{ key: 'serviceability', label: 'Can afford the repayment', max: 30 }, { key: 'security', label: 'Security', max: 70 }], grades: [{ min: 80, grade: 'A', band: 'Very low risk' }, { min: 65, grade: 'B', band: 'Low risk' }, { min: 50, grade: 'C', band: 'Moderate risk' }, { min: 35, grade: 'D', band: 'High risk' }, { min: 0, grade: 'E', band: 'Very high risk' }] }
const ASSESSMENT = (o = {}) => ({ id: 1, version: 1, score: 72, grade: 'B', outcome: 'approve', stale: false, override: null, result: { band: 'Low risk', recommendation: { outcome: 'approve', reasons: ['Grade B (Low risk) with $1,400.00 a month left after the loan.'], conditions: [], supportable_rounded: 250000, supportable_amount: 251000, requested: 200000, limited_by: 'serviceability' },
  cash_flow: { income_monthly: 6500, expenses_monthly: 3420, existing_commitments_monthly: 640, surplus_before: 3080, new_repayment_actual: 1264, new_repayment_assessed: 1682, assessment_rate: 0.095, surplus_after_actual: 1816, surplus_after_assessed: 1398, surplus_after_assessed_pct_of_income: 21.5 },
  factors: [{ key: 'serviceability', label: 'Can afford the repayment', points: 30, max: 30, detail: 'After the new repayment ... $1,398.00 a month left' }, { key: 'security', label: 'Security', points: 10, max: 70, detail: 'The loan is 50% of the security value.' }], adjustments: [], flags: [{ severity: 'high', text: 'Gambling is 8.0% of income' }], missing_info: ['Photo identification has not been received'], key_factors: { strengths: [{ label: 'Can afford the repayment', detail: 'x' }], concerns: [{ label: 'Security', detail: 'y' }] }, declared_commitments_added: 300 }, ...o })

beforeEach(() => { vi.clearAllMocks(); window.confirm = vi.fn(() => true); L.reference.mockResolvedValue(REF) })

describe('Assessment panel', () => {
  it('shows score, grade, recommendation, cash flow before and after, every factor and the flags and what is missing', () => {
    render(<AssessmentPanel a={ASSESSMENT()} />)
    expect(screen.getByText('72')).toBeInTheDocument(); expect(screen.getAllByText(/Grade B/).length).toBeGreaterThan(0); expect(screen.getByText('Recommend approval')).toBeInTheDocument()
    expect(screen.getByLabelText('Cash flow with the loan')).toHaveTextContent('$1,398.00'); expect(screen.getByLabelText('Score factors')).toHaveTextContent('Can afford the repayment'); expect(screen.getByLabelText('Score factors')).toHaveTextContent('30 / 30')
    expect(screen.getByText(/Gambling is 8.0% of income/)).toBeInTheDocument(); expect(screen.getByText(/Missing: Photo identification/)).toBeInTheDocument(); expect(screen.getByText(/Declared debts of \$300.00/)).toBeInTheDocument()
  })
  it('warns when the terms changed since the assessment and shows an override with who, when and why', () => {
    render(<AssessmentPanel a={ASSESSMENT({ stale: true, outcome: 'decline', override: { outcome: 'approved', reason: 'Guarantor added', by: 'owner', at: '2026-10-01T00:00:00' } })} />)
    expect(screen.getByRole('alert')).toHaveTextContent(/run it again before deciding/); const o = screen.getByLabelText('Override')
    expect(o).toHaveTextContent('Overridden by owner'); expect(o).toHaveTextContent('Guarantor added'); expect(o).toHaveTextContent('approved')
  })
  it('says plainly when there is no assessment yet', () => { render(<AssessmentPanel a={null} />); expect(screen.getByText(/Not assessed yet/)).toBeInTheDocument() })
})

describe('Applicants and statement analysis', () => {
  const SUMMARY = { id: 5, contact_id: 1, months: 6, tx_count: 120, inputs: { household_type: 'single_no_children', proposed_loan: 200000, interest_rate: 0.065, loan_term_years: 30 }, reviewed: [{ amount: 9500, reason: 'own accounts' }], gap_report: { flags: [] },
    metrics: { proposed_repayment_monthly: 1682, assessment_rate: 0.095, serviced_umi: 1398, max_borrowing_capacity: 251000, dsr: 9.8, lti: 2.56, risk_score: 20, risk_category: 'Low', hem_benchmark_monthly: 1800, flags: [] },
    summary: { headline: { income_monthly: 6500, expenses_monthly: 2780, existing_commitments_monthly: 640, surplus_monthly: 3080, income_verified_pct: 100 }, trend: { income: 'steady', spending: 'rising (+8%)', note: 'The first and last months may be partial.' }, months: [{ month: '2026-01', income: 6500, spending: 3400, net: 3100, transactions: 20 }],
      recurring_income: [{ label: 'Salary Acme', frequency: 'fortnightly', amount: 3000, monthly_equivalent: 6500 }], recurring_commitments: [{ label: 'Car Loan Toyota', amount: 640, monthly_equivalent: 640 }], unusual: [{ date: '2026-04-14', description: 'ATM WITHDRAWAL', amount: 1500, kind: 'cash_withdrawal', reason: 'Cash withdrawal of 1,500: ask what it was for.' }], conduct: { dishonours: 1, overdrawn_days: 0 } } }
  it('lists applicants, opens one and shows profile, debts and analyses; the add button needs a name', async () => {
    L.applicants.list.mockResolvedValue([{ id: 1, name: 'Jordan Haddad', open_applications: 2 }]); L.applicants.get.mockResolvedValue({ contact: { id: 1, name: 'Jordan Haddad', email: 'j@x.com', phone: '0400' }, profile: { household_type: 'single_no_children', dependants: 0, employment_type: 'paye_full_time', employment_months: 36 }, commitments: [{ id: 3, kind: 'car_loan', lender: 'Toyota', monthly_repayment: '640.00', balance: '21000.00', source: 'detected' }], commitments_monthly: '640.00' })
    L.analyses.list.mockResolvedValue([{ id: 5, created_at: '2026-10-01', label: null, source: 'upload', period_from: '2026-01-01', period_to: '2026-06-20', months: 6, income_monthly: 6500, surplus_monthly: 3080, superseded: false }])
    W(<ApplicantsTab me={ME} />)
    expect(await screen.findByText('2 open')).toBeInTheDocument(); fireEvent.click(screen.getByRole('button', { name: /Jordan Haddad/ }))
    expect(await screen.findByText(/Single no children · 0 dependant\(s\) · Paye full time · 36 months in the job/)).toBeInTheDocument(); expect(screen.getByText('Toyota')).toBeInTheDocument(); expect(screen.getByText('Current')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '+ Applicant' })); expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled(); fireEvent.change(screen.getByLabelText('Full name or business name'), { target: { value: 'New Person' } }); expect(screen.getByRole('button', { name: 'Save' })).not.toBeDisabled()
  })
  it('the analysis dialog needs files, or accounts and dates, and sends a percentage as a fraction', async () => {
    L.applicants.list.mockResolvedValue([{ id: 1, name: 'Jordan Haddad', open_applications: 0 }]); L.applicants.get.mockResolvedValue({ contact: { id: 1, name: 'Jordan Haddad' }, profile: null, commitments: [], commitments_monthly: '0.00' }); L.analyses.list.mockResolvedValue([]); L.bankAccounts.mockResolvedValue([{ id: 9, code: '090', name: 'Business Cheque' }])
    L.analyses.fromBooks.mockResolvedValue({ id: 8 }); L.analyses.get.mockResolvedValue(SUMMARY); L.analyses.lines.mockResolvedValue([]); L.analyses.suggestions.mockResolvedValue([])
    W(<ApplicantsTab me={ME} />); fireEvent.click(await screen.findByRole('button', { name: /Jordan Haddad/ })); fireEvent.click(await screen.findByRole('button', { name: 'Analyse statements' }))
    const go = await screen.findByRole('button', { name: 'Analyse' }); expect(go).toBeDisabled()
    fireEvent.click(screen.getByLabelText(/Use bank accounts already in Accfino/)); fireEvent.click(await screen.findByLabelText('090 Business Cheque')); expect(go).toBeDisabled(); fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-01-01' } }); expect(go).not.toBeDisabled()
    fireEvent.change(screen.getByLabelText('Rate (% a year)'), { target: { value: '7' } }); fireEvent.click(go)
    await waitFor(() => expect(L.analyses.fromBooks).toHaveBeenCalled()); expect(L.analyses.fromBooks.mock.calls[0][1]).toMatchObject({ account_ids: [9], date_from: '2026-01-01', interest_rate: 0.07 })
  })
  it('the Applicant Financial Summary shows income, expenses, commitments, surplus, serviceability, recurring items, unusual transactions and the transfers it did not count as income', async () => {
    L.analyses.get.mockResolvedValue(SUMMARY); L.analyses.suggestions.mockResolvedValue([{ kind: 'car_loan', lender: 'Car Loan Toyota', monthly_repayment: 640 }])
    L.analyses.lines.mockResolvedValue([{ id: 77, date: '2026-03-10', description: 'TRANSFER FROM J SMITH', debit: 0, credit: 1800, category: 'Fund Transfer', reclassified: 'Treated as a transfer', overridden: false }])
    W(<AnalysisView id={5} caps={ALL} applicantId={1} />)
    const flow = await screen.findByLabelText('Income, expenses, commitments, surplus'); expect(flow).toHaveTextContent('$6,500.00'); expect(flow).toHaveTextContent('$3,080.00'); expect(flow).toHaveTextContent('100% shown to recur')
    expect(screen.getByText(/credit\(s\) look like transfers/)).toBeInTheDocument(); expect(screen.getByText('Salary Acme')).toBeInTheDocument(); expect(screen.getByText(/Cash withdrawal of 1,500/)).toBeInTheDocument(); expect(screen.getByText(/1 dishonour or late-payment fee/)).toBeInTheDocument()
    expect(screen.getByText('transfer, not income')).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Re-calculate' })).toBeDisabled()
    L.applicants.addCommitment.mockResolvedValue({}); fireEvent.click(screen.getByRole('button', { name: 'Add as a debt' })); await waitFor(() => expect(L.applicants.addCommitment).toHaveBeenCalledWith(1, expect.objectContaining({ kind: 'car_loan', source: 'detected' })))
  })
  it('correcting a category needs a reason and sends it with the new category', async () => {
    L.analyses.get.mockResolvedValue(SUMMARY); L.analyses.suggestions.mockResolvedValue([]); L.analyses.override.mockResolvedValue(SUMMARY)
    L.analyses.lines.mockResolvedValue([{ id: 77, date: '2026-03-10', description: 'TRANSFER FROM J SMITH', debit: 0, credit: 1800, category: 'Fund Transfer', reclassified: 'Treated as a transfer', overridden: false }])
    W(<AnalysisView id={5} caps={ALL} applicantId={1} />); fireEvent.click(await screen.findByRole('button', { name: 'Correct' }))
    fireEvent.change(screen.getByLabelText(/^Category/), { target: { value: 'Income' } }); fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: 'Rent from a tenant, lease sighted' } }); fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(L.analyses.override).toHaveBeenCalledWith(5, 77, { category: 'Income', reason: 'Rent from a tenant, lease sighted' }))
  })
})

describe('Origination', () => {
  const LIST = { total: 3, counts: { draft: 1, submitted: 1, assessing: 0, more_information: 0, approved: 1, declined: 0, settled: 0, withdrawn: 0 }, rows: [{ id: 1, number: 'APP-0001', applicant: 'Jordan Haddad', purpose: 'Home', loan_type: 'home_loan', amount: '200000.00', status: 'submitted', grade: 'B', score: 72, outcome: 'approve', age_days: 3 }] }
  const detail = (status = 'submitted', extra = {}) => ({ application: { id: 1, number: 'APP-0001', contact_id: 1, purpose: 'Home', loan_type: 'home_loan', amount: '200000.00', term_months: 360, rate: '0.065000', repayment_frequency: 'monthly', status, security_description: '14 Wattle Rd', security_value: '400000.00', allowed_next: [] },
    applicant: { contact: { id: 1, name: 'Jordan Haddad' }, profile: { household_type: 'single_no_children', employment_type: 'paye_full_time' }, commitments_monthly: '640.00' }, analysis: { months: 6, headline: { income_monthly: 6500, surplus_monthly: 3080 } }, assessment: ASSESSMENT(), missing: [], next_action: 'Make the decision: approve or decline, with the reason.',
    documents: [{ key: 'photo_id', label: 'Photo identification', required: true, received: true, received_at: '2026-10-02' }, { key: 'income_evidence', label: 'Evidence of income', required: true, received: false }], events: [{ id: 1, at: '2026-10-01T09:00:00', by: 'owner', kind: 'status', from_status: null, to_status: 'draft', reason: 'Application started' }], ...extra })
  it('shows the pipeline with counts and filters by status', async () => {
    L.applications.list.mockResolvedValue(LIST); W(<OriginationTab me={ME} />)
    expect(await screen.findByRole('button', { name: 'All (3)' })).toBeInTheDocument(); expect(screen.getByText('APP-0001')).toBeInTheDocument(); expect(screen.getByText('Grade B · 72')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Approved (1)' })); await waitFor(() => expect(L.applications.list).toHaveBeenLastCalledWith({ status: 'approved', q: '' }))
  })
  it('a new application needs the essentials and the rate is typed as a percentage', async () => {
    L.applications.list.mockResolvedValue(LIST); L.applicants.list.mockResolvedValue([{ id: 1, name: 'Jordan Haddad' }]); L.applications.create.mockResolvedValue(detail('draft')); L.applications.get.mockResolvedValue(detail('draft'))
    W(<OriginationTab me={ME} />); fireEvent.click(await screen.findByRole('button', { name: '+ New application' })); const start = await screen.findByRole('button', { name: 'Start application' }); expect(start).toBeDisabled()
    fireEvent.change(await screen.findByLabelText('Applicant'), { target: { value: '1' } }); fireEvent.change(screen.getByLabelText('Amount (AUD)'), { target: { value: '200000' } }); fireEvent.change(screen.getByLabelText('Term (months)'), { target: { value: '360' } }); fireEvent.change(screen.getByLabelText(/Interest rate/), { target: { value: '6.5' } })
    expect(start).not.toBeDisabled(); fireEvent.click(start); await waitFor(() => expect(L.applications.create).toHaveBeenCalled()); expect(L.applications.create.mock.calls[0][0]).toMatchObject({ contact_id: 1, amount: '200000', term_months: '360', rate: 0.065 })
  })
  it('an approver sees Approve and Decline, and a decision needs a reason that is sent with it', async () => {
    L.applications.list.mockResolvedValue(LIST); L.applications.get.mockResolvedValue(detail()); L.applications.decide.mockResolvedValue(detail('approved'))
    W(<OriginationTab me={ME} />); fireEvent.click(await screen.findByText('APP-0001')); expect((await screen.findByText(/Next:/)).closest('[role=note]')).toHaveTextContent('Make the decision'); expect(screen.getByLabelText('Documents')).toHaveTextContent('Needed')
    fireEvent.click(screen.getByRole('button', { name: 'Approve' })); fireEvent.change(screen.getByLabelText(/^Reason/), { target: { value: 'Meets policy and documents are in' } }); fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(L.applications.decide).toHaveBeenCalledWith(1, 'approved', 'Meets policy and documents are in'))
  })
  it('a bookkeeper can prepare and assess but is told they cannot approve', async () => {
    L.applications.list.mockResolvedValue(LIST); L.applications.get.mockResolvedValue(detail())
    W(<OriginationTab me={{ capabilities: BOOKKEEPER }} />); fireEvent.click(await screen.findByText('APP-0001'))
    expect(await screen.findByRole('button', { name: 'Run the assessment again' })).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument(); expect(screen.getByText(/can prepare and assess but not approve or decline/)).toBeInTheDocument()
  })
  it('an approved application can be settled into a loan, with the rate and date required', async () => {
    L.applications.list.mockResolvedValue(LIST); L.applications.get.mockResolvedValue(detail('approved', { next_action: 'Settle the loan: record the loan details to create it in the register.' })); L.applications.settle.mockResolvedValue({})
    W(<OriginationTab me={ME} />); fireEvent.click(await screen.findByText('APP-0001')); fireEvent.click(await screen.findByRole('button', { name: 'Settle: create the loan' }))
    fireEvent.change(screen.getByLabelText(/Rate \(% a year\)/), { target: { value: '6.9' } }); fireEvent.click(screen.getByRole('button', { name: 'Create the loan' }))
    await waitFor(() => expect(L.applications.settle).toHaveBeenCalledWith(1, expect.objectContaining({ rate: 0.069 })))
  })
})

describe('Credit', () => {
  it('lists assessments, explains the scoring and shows the policy read-only to a role that cannot configure', async () => {
    L.applications.list.mockResolvedValue({ total: 1, counts: {}, rows: [{ id: 1, number: 'APP-0001', applicant: 'Jordan Haddad', amount: '200000.00', status: 'submitted', grade: 'B', score: 72, outcome: 'approve', created_at: '2026-10-01' }] })
    L.settings.get.mockResolvedValue({ policy: { dti_limit: 0.43, max_lti: 6 }, defaults: { dti_limit: 0.43, max_lti: 6 }, ranges: { dti_limit: [0.1, 0.8], max_lti: [1, 12] }, min_cash_buffer: '0.00', note: 'Indicative guides.' })
    W(<CreditTab me={{ capabilities: ['view'] }} />); expect(await screen.findByText('APP-0001')).toBeInTheDocument(); expect(await screen.findByLabelText('Scoring factors')).toHaveTextContent('100'); expect(screen.getByLabelText('Risk grades')).toHaveTextContent('Very low risk')
    fireEvent.click(screen.getByRole('button', { name: 'Policy settings' })); expect(await screen.findByLabelText(/Maximum loan as a multiple/)).toBeDisabled(); expect(screen.queryByRole('button', { name: 'Save policy' })).not.toBeInTheDocument()
  })
  it('an authorised user can change the policy but not outside the allowed range', async () => {
    L.applications.list.mockResolvedValue({ total: 0, counts: {}, rows: [] }); L.settings.save.mockResolvedValue({})
    L.settings.get.mockResolvedValue({ policy: { dti_limit: 0.43, max_lti: 6 }, defaults: { dti_limit: 0.43, max_lti: 6 }, ranges: { dti_limit: [0.1, 0.8], max_lti: [1, 12] }, min_cash_buffer: '0.00', note: 'Indicative guides.' })
    W(<CreditTab me={ME} />); fireEvent.click(await screen.findByRole('button', { name: 'Policy settings' })); const lti = await screen.findByLabelText(/Maximum loan as a multiple/)
    fireEvent.change(lti, { target: { value: '50' } }); expect(screen.getByText(/max lti must be between 1 and 12/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Save policy' })).toBeDisabled()
    fireEvent.change(lti, { target: { value: '4' } }); fireEvent.click(screen.getByRole('button', { name: 'Save policy' })); await waitFor(() => expect(L.settings.save).toHaveBeenCalled()); expect(L.settings.save.mock.calls[0][0].policy.max_lti).toBe('4')
  })
})

describe('Loans', () => {
  const LOANS = { as_at: '2026-10-07', totals: { loans: 2, active: 2, balance: '298000.00', original: '350000.00', in_arrears: 1, arrears: '3597.30' }, rows: [
    { id: 1, number: 'LN-0001', applicant: 'Jordan Haddad', lender: 'CBA', loan_type: 'home_loan', original_amount: '300000.00', balance: '298500.00', rate: '0.060000', term_periods: 360, next_due: '2026-11-01', next_amount: '1798.65', maturity: '2056-01-01', status: 'active', arrears_amount: '3597.30', bucket: '31-60' },
    { id: 2, number: 'LN-0002', applicant: 'Sam Rivera', lender: 'Westpac', loan_type: 'car_loan', original_amount: '50000.00', balance: '49500.00', rate: '0.079000', term_periods: 60, next_due: '2026-11-05', next_amount: '1011.00', maturity: '2031-09-05', status: 'active', arrears_amount: '0.00', bucket: 'Current' }] }
  it('shows the book, the balance and next repayment of each loan, and flags the one in arrears with its bucket', async () => {
    L.loans.list.mockResolvedValue(LOANS); W(<LoansTab me={ME} />)
    expect(await screen.findByText('LN-0001')).toBeInTheDocument(); expect(screen.getByText('$298,000.00')).toBeInTheDocument(); expect(screen.getByText('31-60 days')).toBeInTheDocument(); expect(screen.getByText('6.00%')).toBeInTheDocument(); expect(screen.getByText('Current')).toBeInTheDocument()
  })
  it('a new loan needs the essentials and all three ledger accounts or none, and the rate is a percentage', async () => {
    L.loans.list.mockResolvedValue(LOANS); L.applicants.list.mockResolvedValue([{ id: 1, name: 'Jordan Haddad' }]); L.bankAccounts.mockResolvedValue([{ id: 9, code: '090', name: 'Business Cheque' }])
    L.ledgerAccounts.mockResolvedValue([{ id: 71, code: '900', name: 'Business Loan', type: 'non_current_liability' }, { id: 26, code: '437', name: 'Interest Expense', type: 'expense' }]); L.loans.create.mockResolvedValue({ loan: { id: 5 } }); L.loans.get.mockResolvedValue({}); L.loans.schedule.mockResolvedValue({})
    W(<LoansTab me={ME} />); fireEvent.click(await screen.findByRole('button', { name: '+ Loan' })); const make = await screen.findByRole('button', { name: 'Create the loan' }); expect(make).toBeDisabled()
    fireEvent.change(await screen.findByLabelText('Applicant'), { target: { value: '1' } }); fireEvent.change(screen.getByLabelText('Amount (AUD)'), { target: { value: '100000' } }); fireEvent.change(screen.getByLabelText('Rate (% a year)'), { target: { value: '7' } }); fireEvent.change(screen.getByLabelText('Term (months)'), { target: { value: '60' } })
    expect(make).not.toBeDisabled(); fireEvent.change(await screen.findByLabelText('Loan (liability) account'), { target: { value: '71' } }); expect(screen.getByText(/Give all three ledger accounts, or none/)).toBeInTheDocument(); expect(make).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Loan (liability) account'), { target: { value: '' } }); fireEvent.click(make); await waitFor(() => expect(L.loans.create).toHaveBeenCalled()); expect(L.loans.create.mock.calls[0][0]).toMatchObject({ contact_id: 1, original_amount: '100000', rate: 0.07, term_months: '60' })
  })
  it('the loan page shows position and schedule, and a repayment can be recorded', async () => {
    L.loans.list.mockResolvedValue(LOANS); L.loans.repay.mockResolvedValue({})
    L.loans.get.mockResolvedValue({ loan: { id: 1, number: 'LN-0001', applicant: 'Jordan Haddad', lender: 'CBA', loan_type: 'home_loan', original_amount: '300000.00', frequency: 'monthly', term_periods: 360, status: 'active', ledger_posting: false, application_id: 4 },
      position: { balance: '298500.00', current_rate: '0.060000', next: { amount: '1798.65', due: '2026-11-01' }, arrears_amount: '3597.30', missed_count: 2, days_overdue: 42, bucket: '31-60', maturity: '2056-01-01', payout_estimate: '299100.00' }, rate_changes: [], repayments: [{ id: 3, paid_date: '2026-03-01', amount: '1798.65', voided: false }] })
    L.loans.schedule.mockResolvedValue({ note: 'The contractual schedule ...', totals: { total_interest: '347514.57' }, contractual: [{ n: 1, due: '2026-02-01', opening: '300000.00', interest: '1500.00', principal: '298.65', payment: '1798.65', closing: '299701.35', status: 'paid' }, { n: 2, due: '2026-03-01', opening: '299701.35', interest: '1498.51', principal: '300.14', payment: '1798.65', closing: '299401.21', status: 'unpaid' }] })
    W(<LoansTab me={ME} />); fireEvent.click(await screen.findByText('LN-0001'))
    expect(await screen.findByText(/In arrears: 31-60 days/)).toBeInTheDocument(); expect(screen.getByText('2 missed · 42 days')).toBeInTheDocument(); expect(await screen.findByText(/Total interest over the life of the loan/)).toHaveTextContent('$347,514.57')
    fireEvent.click(screen.getByRole('button', { name: '+ Repayment' })); const save = screen.getByRole('button', { name: 'Save' }); expect(save).toBeDisabled(); fireEvent.change(screen.getByLabelText('Amount (AUD)'), { target: { value: '1798.65' } }); fireEvent.click(save)
    await waitFor(() => expect(L.loans.repay).toHaveBeenCalledWith(1, expect.objectContaining({ amount: '1798.65' }), false))
  })
})

describe('Collections', () => {
  const REG = { as_at: '2026-10-07', note: 'Days overdue are counted from the oldest instalment that is not fully paid.', summary: { loans: 3, in_arrears: 2, arrears_total: '8000.00', hardship: 1, arrangements: 1, broken_arrangements: 1, follow_ups_due: 1, promises: 0 },
    buckets: [{ bucket: 'Current', loans: 1, arrears: '0.00', balance: '90000.00' }, { bucket: '1-30', loans: 0, arrears: '0.00', balance: '0.00' }, { bucket: '31-60', loans: 1, arrears: '3597.30', balance: '298000.00' }, { bucket: '61-90', loans: 0, arrears: '0.00', balance: '0.00' }, { bucket: '90+', loans: 1, arrears: '4402.70', balance: '120000.00' }],
    rows: [{ loan_id: 1, id: 1, number: 'LN-0001', applicant: 'Jordan Haddad', oldest_due_date: '2026-08-20', amount_due: '3597.30', amount_paid: '0.00', last_payment_date: null, arrears_amount: '3597.30', days_overdue: 48, missed_payments: 2, bucket: '31-60', status: 'in_arrears', label: 'In arrears: no contact yet', follow_up_due: true }] }
  const CASE = (caps = {}) => ({ summary: { loan_id: 1, number: 'LN-0001', applicant: 'Jordan Haddad', phone: '0400 111 222', email: 'j@x.com', arrears_amount: '3597.30', missed_payments: 2, days_overdue: 48, bucket: '31-60', balance: '298000.00', status: 'arrangement', label: 'On a payment arrangement', last_activity: { kind: 'call', date: '2026-10-01' }, next_action_date: '2026-10-09',
    arrangement: { id: 2, amount_per_period: '400.00', frequency: 'fortnightly', expected: '1200.00', paid: '0.00', behind: '1200.00', compliance: 'behind', can_complete: false } }, activities: [{ id: 1, date: '2026-10-01', kind: 'call', outcome: 'No answer' }], arrangements: [], hardship: [{ id: 4, requested_date: '2026-10-02', reason: 'Illness', status: 'requested', allowed_next: ['assessing', 'approved', 'declined'] }], ...caps })
  it('shows the five arrears buckets, the totals and the register, and a bucket click filters it', async () => {
    L.collections.register.mockResolvedValue(REG); W(<CollectionsTab me={ME} />)
    const b = await screen.findByLabelText('Arrears buckets'); expect(within(b).getByText('31-60 days')).toBeInTheDocument(); expect(within(b).getByText('90+ days')).toBeInTheDocument(); expect(b).toHaveTextContent('arrears $4,402.70')
    expect(screen.getByText('Follow-ups due')).toBeInTheDocument(); expect(screen.getByText('LN-0001')).toBeInTheDocument(); expect(screen.getByText('follow up')).toBeInTheDocument()
    fireEvent.click(within(b).getByRole('button', { name: /31-60 days/ })); await waitFor(() => expect(L.collections.register).toHaveBeenLastCalledWith({ bucket: '31-60', status: '', q: '' }))
  })
  it('the case shows contact details, warns when the borrower is behind on an arrangement, and a promise to pay needs a date', async () => {
    L.collections.register.mockResolvedValue(REG); L.collections.caseFor.mockResolvedValue(CASE()); L.collections.activity.mockResolvedValue(CASE())
    W(<CollectionsTab me={ME} />); fireEvent.click(await screen.findByText('LN-0001'))
    expect(await screen.findByText(/0400 111 222/)).toBeInTheDocument(); const a = screen.getByLabelText('Payment arrangement'); expect(a).toHaveTextContent('behind by $1,200.00'); expect(a).toHaveClass('alert-error')
    fireEvent.click(screen.getByRole('button', { name: '+ Log contact or note' })); fireEvent.change(await screen.findByLabelText('What happened'), { target: { value: 'promise_to_pay' } })
    expect(screen.getByText(/needs the date it was promised for/)).toBeInTheDocument(); const save = screen.getByRole('button', { name: 'Save' }); expect(save).toBeDisabled(); fireEvent.change(screen.getByLabelText(/Next action/), { target: { value: '2026-10-12' } }); expect(save).not.toBeDisabled()
  })
  it('only someone with approval authority is offered to approve or decline hardship', async () => {
    L.collections.register.mockResolvedValue(REG); L.collections.caseFor.mockResolvedValue(CASE())
    const { unmount } = W(<CollectionsTab me={{ capabilities: BOOKKEEPER }} />); fireEvent.click(await screen.findByText('LN-0001')); await screen.findByText('Contact and activity log')
    expect(screen.getByRole('button', { name: 'Assessing' })).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Approved' })).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Declined' })).not.toBeInTheDocument(); unmount()
    W(<CollectionsTab me={ME} />); fireEvent.click(await screen.findByText('LN-0001')); expect(await screen.findByRole('button', { name: 'Approved' })).toBeInTheDocument()
  })
})

describe('Treasury', () => {
  const W30 = (o = {}) => ({ days: 30, actual: { cash: 2000 }, committed: { inflow: 0, outflow: 9000 }, forecast: { inflow: 0, outflow: 0 }, closing_committed: -7000, closing_forecast: -7000, status: 'short', lowest_committed: { balance: -7000, date: '2026-10-17' }, lowest_forecast: { balance: -7000, date: '2026-10-17' },
    shortfall_committed: { funding_required: 8000, covered_by_facilities: 3000, uncovered: 5000, days_below_buffer: 20 }, shortfall_forecast: { funding_required: 8000 }, ...o })
  const POS = { as_at: '2026-10-07', horizon: 90, min_cash_buffer: '1000.00', explain: 'Actual is the cash in your bank accounts today ... kept apart ...', cash: { total: '2000.00', accounts: [{ id: 9, code: '090', name: 'Business Cheque', balance: '2000.00' }] }, facilities: { limit: '10000.00', drawn: '7000.00', available: '3000.00', rows: [] },
    windows: [W30(), W30({ days: 60 }), W30({ days: 90 })], projection: { days: [{ date: '2026-10-07', committed_balance: 2000, forecast_balance: 2000 }], weekly: [{ week: 2, from_date: '2026-10-14', committed_net: -9000, forecast_net: 0 }] },
    flows: [{ date: '2026-10-17', label: 'Tax payment', source: 'bill', kind: 'committed', amount: -9000 }, { date: '2026-10-20', label: 'Expected sale', source: 'forecast', kind: 'forecast', amount: 4000 }], overdue_receivables: [{ number: 'I-2', contact: 'Client B', due: '2026-09-07', amount: '4000.00', days_overdue: 30 }] }
  const mocks = () => { L.treasury.position.mockResolvedValue(POS); L.treasury.items.mockResolvedValue([]); L.treasury.facilities.mockResolvedValue({ rows: [{ id: 1, name: 'Line of credit', lender: 'CBA', limit: '10000.00', drawn: '7000.00', available: '3000.00', utilisation_pct: 70, over_limit: false, interest_rate: '0.085000', expiry_date: '2026-11-15', days_to_expiry: 39, expiry_warning: true, status: 'active' }], totals: {} }) }
  it('keeps actual, committed and forecast apart and says what funding is needed and whether the facilities cover it', async () => {
    mocks(); W(<TreasuryTab me={ME} />)
    const t = await screen.findByLabelText('Liquidity windows'); expect(t).toHaveTextContent('30 days'); expect(t).toHaveTextContent('Short on committed flows alone'); expect(t).toHaveTextContent('Funding needed $8,000.00: facilities cover $3,000.00, $5,000.00 uncovered')
    expect(screen.getAllByText('Cash today (actual)').length).toBeGreaterThan(0); expect(screen.getByText('Tax payment')).toBeInTheDocument(); expect(screen.getByText('Unpaid bill')).toBeInTheDocument(); expect(screen.getByText(/Overdue invoices \(not counted/)).toBeInTheDocument(); expect(screen.getByText(/I-2 · Client B/)).toBeInTheDocument()
    expect(screen.getAllByTestId('chart').length).toBeGreaterThan(0); expect(screen.getByText('Show the weekly figures')).toBeInTheDocument()
  })
  it('changing the look-ahead asks for that horizon, and facilities show utilisation and an expiry warning', async () => {
    mocks(); W(<TreasuryTab me={ME} />); await screen.findByLabelText('Liquidity windows')
    fireEvent.change(screen.getByLabelText('Look ahead'), { target: { value: '180' } }); await waitFor(() => expect(L.treasury.position).toHaveBeenLastCalledWith(180))
    expect(screen.getByText('70%')).toBeInTheDocument(); expect(screen.getByText('39 days')).toBeInTheDocument()
  })
  it('money going out is saved as a negative amount, and a facility needs a name and a limit', async () => {
    mocks(); L.treasury.saveItem.mockResolvedValue({}); W(<TreasuryTab me={ME} />); fireEvent.click(await screen.findByRole('button', { name: '+ Expected money in or out' }))
    fireEvent.change(screen.getByLabelText('Direction'), { target: { value: 'out' } }); fireEvent.change(screen.getByLabelText('Amount (AUD)'), { target: { value: '2500' } }); fireEvent.change(screen.getByLabelText('What is it'), { target: { value: 'Equipment service' } }); fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(L.treasury.saveItem).toHaveBeenCalled()); expect(L.treasury.saveItem.mock.calls[0][0]).toMatchObject({ amount: -2500, description: 'Equipment service' })
    L.reference.mockResolvedValue(REF); L.ledgerAccounts.mockResolvedValue([]); fireEvent.click(screen.getByRole('button', { name: '+ Facility' })); const save = await screen.findAllByRole('button', { name: 'Save' }); expect(save[save.length - 1]).toBeDisabled()
  })
  it('a bookkeeper can enter forecast items but not facilities', async () => {
    mocks(); W(<TreasuryTab me={{ capabilities: BOOKKEEPER }} />); await screen.findByLabelText('Liquidity windows'); expect(screen.getByRole('button', { name: '+ Expected money in or out' })).toBeInTheDocument(); expect(screen.queryByRole('button', { name: '+ Facility' })).not.toBeInTheDocument()
  })
})

describe('Overview', () => {
  it('shows the pipeline, the book, arrears, cash and what needs attention, and each item takes you to its tab', async () => {
    L.dashboard.mockResolvedValue({ pipeline: { counts: { draft: 1, submitted: 2, assessing: 0, more_information: 1, approved: 1 }, total: 5 }, book: { active: 4, balance: '500000.00' }, arrears: { buckets: [{ bucket: 'Current', loans: 3 }, { bucket: '31-60', loans: 1 }], summary: { arrears_total: '3597.30' } },
      liquidity: { cash: '2000.00', status: 'watch', closing_committed: 1500, facility_available: '3000.00' }, attention: [{ kind: 'loan', id: 1, text: 'LN-0001 (Jordan Haddad): follow-up due, 48 days overdue' }] })
    const go = vi.fn(); render(<Overview onGo={go} />)
    const o = await screen.findByLabelText('Lending overview'); expect(o).toHaveTextContent('4'); expect(o).toHaveTextContent('1 approved, awaiting settlement'); expect(o).toHaveTextContent('$500,000.00 outstanding')
    expect(screen.getByText('Applications open')).toBeInTheDocument(); expect(screen.getByText('Loans behind')).toBeInTheDocument(); fireEvent.click(screen.getByRole('button', { name: /LN-0001 \(Jordan Haddad\)/ })); expect(go).toHaveBeenCalledWith('collections')
    fireEvent.click(screen.getByText('Cash today')); expect(go).toHaveBeenCalledWith('treasury')
  })
  it('shows only the sections the plan includes (the others come back empty from the server)', async () => {
    L.dashboard.mockResolvedValue({ pipeline: null, book: null, arrears: { buckets: [{ bucket: 'Current', loans: 2 }, { bucket: '1-30', loans: 1 }], summary: { arrears_total: '500.00' } }, liquidity: null, attention: [] })
    render(<Overview onGo={vi.fn()} />)
    const o = await screen.findByLabelText('Lending overview'); expect(o).toHaveTextContent('Loans behind'); expect(o).toHaveTextContent('$500.00 in arrears')
    expect(screen.queryByText('Applications open')).not.toBeInTheDocument(); expect(screen.queryByText('Loans on the book')).not.toBeInTheDocument(); expect(screen.queryByText('Cash today')).not.toBeInTheDocument()
  })
})
