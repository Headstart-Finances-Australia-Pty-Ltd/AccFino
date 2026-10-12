import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../lib/planningApi.js', () => {
  const fn = vi.fn
  return {
    errMsg: e => e?.message || 'Error', me: fn(), overview: fn(), settings: { get: fn(), save: fn() }, drilldown: fn(),
    forecast: { get: fn(), save: fn(), snapshots: fn(), snapshot: fn(), vsActual: fn() },
    budgets: { list: fn(), create: fn(), get: fn(), saveLines: fn(), importCsv: fn(), exportCsv: fn(), copy: fn(), submit: fn(), approve: fn(), reject: fn(), archive: fn(), remove: fn(), vsActual: fn() },
    scenarios: { templates: fn(), list: fn(), create: fn(), update: fn(), duplicate: fn(), archive: fn(), run: fn(), runs: fn(), runGet: fn(), compare: fn(), sensitivity: fn() },
    reports: { get: fn(), snapshot: fn(), snapshots: fn(), snapshotGet: fn(), exportFile: fn() },
    insights: { get: fn(), saveConfig: fn() },
    assistant: { ask: fn(), suggestions: fn(), history: fn() },
    risk: { alerts: fn(), preview: fn(), scan: fn(), review: fn(), config: fn(), saveConfig: fn() },
  }
})
import * as api from '../lib/planningApi.js'
import { fmtAUD, basisKey, label } from '../lib/format.js'
import Home from '../pages/Home.jsx'
import AssistantTab from '../pages/AssistantTab.jsx'
import RiskTab from '../pages/RiskTab.jsx'
import BudgetTab from '../pages/BudgetTab.jsx'
import ScenarioTab from '../pages/ScenarioTab.jsx'

const W = ui => render(<MemoryRouter>{ui}</MemoryRouter>)
const FULL = ['view', 'edit', 'approve', 'review', 'config', 'ai']
const READONLY = ['view', 'ai']
beforeEach(() => { vi.clearAllMocks(); window.confirm = vi.fn(() => true); window.prompt = vi.fn(() => 'because') })

describe('format helpers', () => {
  it('formats money in AUD with brackets for negatives and a dash for missing values', () => {
    expect(fmtAUD('1234.5')).toBe('$1,234.50'); expect(fmtAUD(-10)).toBe('($10.00)'); expect(fmtAUD(null)).toBe('—'); expect(fmtAUD('abc')).toBe('—')
  })
  it('maps every basis to one of the six labels, defaulting to actual', () => {
    expect(['FORECAST (week)', 'BUDGET', 'scenario', 'AI', 'RULE', 'ledger'].map(basisKey)).toEqual(['FORECAST', 'BUDGET', 'SCENARIO', 'AI', 'RULE', 'ACTUAL'])
    expect(label('open_risk')).toBe('Open risk')
  })
})

describe('Overview', () => {
  const OV = (o = {}) => ({ organisation: 'Alpha Pty Ltd', currency: 'AUD', as_at: '2026-09-30',
    cash: { balance: '83500.00', accounts: 1, unreconciled: 0, stale: false }, forecast: { minimum: { balance: '70000.00', label: 'Week 2' }, confidence: 'medium', warnings: 1, goes_negative: false },
    profit: { net_profit: '4000.00', revenue: '10000.00', expenses: '6000.00' }, budget: { status: 'none', note: 'No approved budget' },
    risk: { new: 2, by_severity: { high: 1, medium: 1, low: 0 } }, insights: { counts: { high: 0, medium: 1, low: 0, info: 0 }, top: [{ severity: 'medium', title: 'Receivables are overdue' }], period: '2026-07-01 to 2026-09-30' },
    scenarios: { active: 1 }, assistant: { questions_24h: 3 }, reports: { snapshots: 0 }, settings: { min_cash_threshold: '5000', horizon_weeks: 13 }, ...o })
  it('shows each headline with what it is (actual, forecast, budget, rule) and the organisation, currency and date', async () => {
    api.overview.mockResolvedValue(OV()); const go = vi.fn()
    W(<Home go={go} />)
    expect(await screen.findByText('Cash at bank')).toBeInTheDocument()
    expect(screen.getByText('$83,500.00')).toBeInTheDocument(); expect(screen.getByText('Lowest forecast cash')).toBeInTheDocument(); expect(screen.getAllByText('Forecast').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Actual').length).toBeGreaterThan(0); expect(screen.getByText('No budget')).toBeInTheDocument(); expect(screen.getByText(/Alpha Pty Ltd/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('Open risk alerts')); expect(go).toHaveBeenCalledWith('risk')
  })
  it('warns when the bank data is stale and when no bank account exists', async () => {
    api.overview.mockResolvedValue(OV({ cash: { balance: '0.00', accounts: 0, unreconciled: 0, stale: true, last_bank_line: '2026-08-01' } }))
    W(<Home go={() => {}} />)
    expect(await screen.findByText(/Bank data may be stale/)).toBeInTheDocument(); expect(screen.getByText(/No bank account is set up/)).toBeInTheDocument()
  })
  it('a failing tile shows its own error and the rest of the page still renders', async () => {
    api.overview.mockResolvedValue(OV({ risk: { error: 'risk engine unavailable' } }))
    W(<Home go={() => {}} />)
    expect(await screen.findByText(/could not be loaded: risk engine unavailable/)).toBeInTheDocument(); expect(screen.getByText('Cash at bank')).toBeInTheDocument()
  })
  it('shows a retry control when the whole overview fails', async () => {
    api.overview.mockRejectedValue(new Error('Server error'))
    W(<Home go={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Server error'); expect(screen.getByText('Try again')).toBeInTheDocument()
  })
})

describe('AI assistant', () => {
  beforeEach(() => { api.assistant.suggestions.mockResolvedValue({ label: 'Read-only assistant.', limit_per_hour: 30, suggestions: ['What is our bank balance?'] }); api.assistant.history.mockResolvedValue([]) })
  it('asks a suggested question and shows the answer with its sources', async () => {
    api.assistant.ask.mockResolvedValue({ status: 'ok', label: 'From balance sheet', answer: 'Bank balance is $83,500.00', citations: [{ report: 'balance_sheet', metric: 'cash', period: '2026-09-30', calculation: 'sum of bank accounts', source: 'ledger', basis: 'ACTUAL' }] })
    W(<AssistantTab />)
    fireEvent.click(await screen.findByText('What is our bank balance?'))
    expect(await screen.findByText('Bank balance is $83,500.00')).toBeInTheDocument(); expect(api.assistant.ask).toHaveBeenCalledWith('What is our bank balance?')
    expect(screen.getByText(/Sources and calculations \(1\)/)).toBeInTheDocument(); expect(screen.getByText(/sum of bank accounts/)).toBeInTheDocument()
  })
  it('shows a declined notice for a write request and an inline error when the call fails', async () => {
    api.assistant.ask.mockResolvedValueOnce({ status: 'refused', label: 'Declined', answer: 'I cannot change records.' })
    W(<AssistantTab />)
    const box = await screen.findByLabelText('Your question')
    fireEvent.change(box, { target: { value: 'delete invoice 5' } }); fireEvent.click(screen.getByText('Ask'))
    expect(await screen.findByText(/declined\. The assistant is read-only/)).toBeInTheDocument()
    api.assistant.ask.mockRejectedValueOnce(new Error('Rate limit reached'))
    fireEvent.change(box, { target: { value: 'cash?' } }); fireEvent.click(screen.getByText('Ask'))
    expect(await screen.findByText('Rate limit reached')).toBeInTheDocument()
  })
  it('does not send an empty question', async () => {
    W(<AssistantTab />)
    await screen.findByLabelText('Your question')
    expect(screen.getByText('Ask')).toBeDisabled(); expect(api.assistant.ask).not.toHaveBeenCalled()
  })
})

describe('Risk', () => {
  const ALERT = { id: 7, rule: 'RISK-DUP', rule_version: 'risk-1.0', severity: 'medium', title: 'Possible duplicate payment to Dup Supplier', reason: 'Two payments of 1,234.56', status: 'new', amount: '1234.56', event_date: '2026-09-23', evidence: {}, baseline: {} }
  const DATA = { counts: { new: 1, acknowledged: 0, resolved: 0, dismissed: 0 }, rules: { 'RISK-DUP': 'Possible duplicate payment' }, alerts: [ALERT] }
  it('never uses the word fraud and states that alerts are not findings of wrongdoing', async () => {
    api.me.mockResolvedValue({ capabilities: FULL }); api.risk.alerts.mockResolvedValue(DATA)
    const { container } = W(<RiskTab />)
    expect(await screen.findByText(/Possible duplicate payment to Dup Supplier/)).toBeInTheDocument(); expect(screen.getByText(/not findings of error or wrongdoing/)).toBeInTheDocument()
    expect(container.textContent.toLowerCase()).not.toContain('fraud')
  })
  it('requires a note to dismiss, then records the review', async () => {
    api.me.mockResolvedValue({ capabilities: FULL }); api.risk.alerts.mockResolvedValue(DATA); api.risk.review.mockResolvedValue({})
    W(<RiskTab />)
    fireEvent.click(await screen.findByText('Review'))
    fireEvent.change(await screen.findByLabelText('Outcome'), { target: { value: 'dismissed' } })
    expect(screen.getByText('Save review')).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Note (required)'), { target: { value: 'Expected: two invoices' } })
    fireEvent.click(screen.getByText('Save review'))
    await waitFor(() => expect(api.risk.review).toHaveBeenCalledWith(7, 'dismissed', 'Expected: two invoices'))
  })
  it('a read-only user sees details but no scan, threshold or review controls', async () => {
    api.me.mockResolvedValue({ capabilities: READONLY }); api.risk.alerts.mockResolvedValue(DATA)
    W(<RiskTab />)
    await screen.findByText(/Possible duplicate payment to Dup Supplier/)
    expect(screen.queryByText('Run scan now')).toBeNull(); expect(screen.queryByText('Thresholds')).toBeNull(); expect(screen.queryByText('Review')).toBeNull(); expect(screen.getByText('Details')).toBeInTheDocument()
  })
})

describe('Budgets', () => {
  const ROW = (status) => [{ id: 3, name: 'FY27 Budget', fy_start: '2026-07-01', version: 1, status, owner: 'owner', lines: 48 }]
  const open = async () => { fireEvent.click(await screen.findByText('FY27 Budget')) }
  it('an editor sees New budget and, on a submitted budget, an approver sees Approve', async () => {
    api.me.mockResolvedValue({ capabilities: FULL }); api.budgets.list.mockResolvedValue(ROW('submitted')); api.budgets.get.mockResolvedValue({ id: 3, name: 'FY27 Budget', status: 'submitted', lines: [], months: [], accounts: [] })
    W(<BudgetTab />)
    expect(await screen.findByText('New budget')).toBeInTheDocument(); await open(); expect(await screen.findByText('Approve')).toBeInTheDocument()
  })
  it('a read-only user cannot create, submit, approve, archive or delete, but can export', async () => {
    api.me.mockResolvedValue({ capabilities: READONLY }); api.budgets.list.mockResolvedValue(ROW('draft')); api.budgets.get.mockResolvedValue({ id: 3, name: 'FY27 Budget', status: 'draft', lines: [], months: [], accounts: [] })
    W(<BudgetTab />)
    await open(); await screen.findByText('Export CSV')
    for (const t of ['New budget', 'Submit for approval', 'Approve', 'Archive', 'Delete draft']) expect(screen.queryByText(t)).toBeNull()
  })
  it('creating requires a name and calls the API with the chosen year', async () => {
    api.me.mockResolvedValue({ capabilities: FULL }); api.budgets.list.mockResolvedValue([]); api.budgets.create.mockResolvedValue({ id: 9 }); api.budgets.get.mockResolvedValue(null)
    W(<BudgetTab />)
    fireEvent.click(await screen.findByText('New budget'))
    expect(screen.getByText('Create')).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'FY28' } }); fireEvent.click(screen.getByText('Create'))
    await waitFor(() => expect(api.budgets.create).toHaveBeenCalled()); expect(api.budgets.create.mock.calls[0][0].name).toBe('FY28')
  })
})

describe('Scenarios', () => {
  const SC = { id: 4, name: 'Downside', kind: 'downside', status: 'active', version: 1, base_source: 'run_rate' }
  const RUN = { scenario: { name: 'Downside', version: 1 }, organisation: 'Alpha Pty Ltd', currency: 'AUD', period_from: '2026-10', period_to: '2027-09', input_hash: 'abcdef1234567890',
    base: { opening_cash: '83500.00', provenance: { detail: 'ledger run-rate' } }, summary: { revenue: '100.00', expenses: '120.00', profit: '-20.00', profit_margin_pct: '-20.0', closing_cash: '83480.00', lowest_cash: { month: '2027-09', balance: '83480.00' } },
    months: [], limitations: ['A scenario is not a prediction.'] }
  beforeEach(() => { api.scenarios.templates.mockResolvedValue({}); api.budgets.list.mockResolvedValue([]); api.scenarios.list.mockResolvedValue([SC]) })
  it('previewing a scenario labels the result hypothetical, shows limitations and the reproducibility fingerprint', async () => {
    api.me.mockResolvedValue({ capabilities: FULL }); api.scenarios.run.mockResolvedValue(RUN)
    W(<ScenarioTab />)
    fireEvent.click(await screen.findByText('Preview'))
    expect(await screen.findByText(/Hypothetical results\. Nothing here is posted to your books/)).toBeInTheDocument(); expect(screen.getByText('A scenario is not a prediction.')).toBeInTheDocument()
    expect(screen.getByText(/Input fingerprint abcdef123456/)).toBeInTheDocument(); expect(api.scenarios.run).toHaveBeenCalledWith(4, { save: false })
  })
  it('a read-only user can preview but cannot create, save a run, edit, duplicate or archive', async () => {
    api.me.mockResolvedValue({ capabilities: READONLY })
    W(<ScenarioTab />)
    await screen.findByText('Preview')
    for (const t of ['New scenario', 'Edit', 'Archive']) expect(screen.queryByText(t)).toBeNull()
    expect(screen.queryByText(/Run & save/)).toBeNull()
  })
  it('compare needs between 2 and 6 scenarios', async () => {
    api.me.mockResolvedValue({ capabilities: FULL })
    W(<ScenarioTab />)
    const btn = await screen.findByText(/Compare selected \(0\)/)
    expect(btn).toBeDisabled(); fireEvent.click(screen.getByLabelText('Compare Downside')); expect(screen.getByText(/Compare selected \(1\)/)).toBeDisabled()
  })
})
