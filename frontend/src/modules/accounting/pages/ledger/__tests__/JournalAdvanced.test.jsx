import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

const ACC = [{ id: 5, code: '445', name: 'Light, Power, Heating' }, { id: 9, code: '805', name: 'Accrued Expenses' }]
const CATS = [{ id: 1, name: 'Job', is_active: true, options: [{ id: 21, name: 'Sydney', is_active: true }, { id: 22, name: 'Melbourne', is_active: true }] }]
vi.mock('../../../../../core/lib/platformApi.js', () => {
  const ok = data => vi.fn(() => Promise.resolve({ data }))
  return {
    errMsg: e => e?.response?.data?.detail || e?.message || 'err',
    accounts: ok([]), taxCodes: ok([]), tracking: ok([]), journals: ok({ items: [], total: 0, sum_total: '0' }), journal: ok({}), journalSources: ok({ items: [] }), journalHistory: ok({ events: [] }), reverseJournal: ok({}),
    postJournal: ok({ id: 7, journal_no: 300 }), journalPreview: ok(null), createDraft: ok({ id: 55 }), updateDraft: ok({}), submitDraft: ok({}), approveDraft: ok({}), rejectDraft: ok({}), deleteDraft: ok({}),
    journalDrafts: ok({ items: [], counts: {} }), journalDraft: ok({}), bulkApprove: ok({}), generateSuggestions: ok({ created: 0 }), repeatingJournals: ok({ items: [] }), createRepeating: ok({}), updateRepeating: ok({}),
    deleteRepeating: ok({}), runRepeating: ok({}), importJournals: ok({}), downloadImportTemplate: vi.fn(),
    fxRates: ok({ base: 'AUD', items: [] }), fxRate: ok({ rate: null }), putFxRate: ok({}), deleteFxRate: ok({}),
    schedulerStatus: ok({ enabled: true, interval_seconds: 900, timezone: 'Australia/Sydney', auto_templates: 2, last_sweep: { at: '2026-09-30T01:15:00Z', drafts: 2, posted: 1, errors: [] } }),
  }
})
vi.mock('../../../lib/ledgerApi.js', () => {
  const ok = data => vi.fn(() => Promise.resolve({ data }))
  return {
    errMsg: e => e?.response?.data?.detail || e?.message || 'err',
    accounts: ok([]), taxCodes: ok([]), tracking: ok([]), journals: ok({ items: [], total: 0, sum_total: '0' }), journal: ok({}), journalSources: ok({ items: [] }), journalHistory: ok({ events: [] }), reverseJournal: ok({}),
    postJournal: ok({ id: 7, journal_no: 300 }), journalPreview: ok(null), createDraft: ok({ id: 55 }), updateDraft: ok({}), submitDraft: ok({}), approveDraft: ok({}), rejectDraft: ok({}), deleteDraft: ok({}),
    journalDrafts: ok({ items: [], counts: {} }), journalDraft: ok({}), bulkApprove: ok({}), generateSuggestions: ok({ created: 0 }), repeatingJournals: ok({ items: [] }), createRepeating: ok({}), updateRepeating: ok({}),
    deleteRepeating: ok({}), runRepeating: ok({}), importJournals: ok({}), downloadImportTemplate: vi.fn(),
    fxRates: ok({ base: 'AUD', items: [] }), fxRate: ok({ rate: null }), putFxRate: ok({}), deleteFxRate: ok({}),
    schedulerStatus: ok({ enabled: true, interval_seconds: 900, timezone: 'Australia/Sydney', auto_templates: 2, last_sweep: { at: '2026-09-30T01:15:00Z', drafts: 2, posted: 1, errors: [] } }),
  }
})
vi.mock('../../../../../core/lib/adminApi.js', () => ({ errMsg: e => e?.message || 'err', uploadAttachment: vi.fn(() => Promise.resolve({})), downloadAttachment: vi.fn() }))
vi.mock('../../../lib/booksApi.js', () => ({ errMsg: e => e?.message || 'err', uploadAttachment: vi.fn(() => Promise.resolve({})), downloadAttachment: vi.fn() }))
vi.mock('../../../../billing/lib/orgBillingApi.js', () => ({ errMsg: e => e?.message || 'err', uploadAttachment: vi.fn(() => Promise.resolve({})), downloadAttachment: vi.fn() }))
vi.mock('../../../../open_banking/lib/feedApi.js', () => ({ errMsg: e => e?.message || 'err', uploadAttachment: vi.fn(() => Promise.resolve({})), downloadAttachment: vi.fn() }))
vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
import * as api from '../../../lib/ledgerApi.js'
import toast from 'react-hot-toast'
import { JournalEditor, RepeatingEditor, money } from '../JournalEditor.jsx'
const USD1000 = money('1000', 'USD').replace(/\s/g, ' ')
import { JournalsTab, ReviewTab, RepeatingTab, FxRatesModal, sourceBadge } from '../JournalTools.jsx'

const okPv = extra => ({ balanced: true, errors: [], warnings: [], gst_total: '0.00', total_debit: '650.00', total_credit: '650.00', lines: [], fx: null, ...extra })
const mount = props => render(<JournalEditor accounts={ACC} taxes={[]} categories={CATS} canApprove requireApproval={false} onClose={() => {}} onDone={() => {}} {...props} />)
const fill = () => {
  fireEvent.change(screen.getByTestId('jnl-narration'), { target: { value: 'Import freight' } })
  fireEvent.change(screen.getByLabelText('Account 1'), { target: { value: '5' } }); fireEvent.change(screen.getByLabelText('Debit 1'), { target: { value: '1000' } })
  fireEvent.change(screen.getByLabelText('Account 2'), { target: { value: '9' } }); fireEvent.change(screen.getByLabelText('Credit 2'), { target: { value: '1000' } })
}
beforeEach(() => { vi.clearAllMocks(); api.accounts.mockResolvedValue({ data: ACC }); api.taxCodes.mockResolvedValue({ data: [] }); api.tracking.mockResolvedValue({ data: CATS }); api.fxRates.mockResolvedValue({ data: { base: 'AUD', items: [{ id: 1, currency: 'USD', date: '2026-09-20', rate: '0.6700' }] } })
  api.fxRate.mockResolvedValue({ data: { rate: null } }); api.journalPreview.mockResolvedValue({ data: okPv() }); window.confirm = vi.fn(() => true) })

describe('multi-currency journal editor', () => {
  it('needs no currency for a base-currency journal and sends none', async () => {
    mount(); fill(); await waitFor(() => expect(screen.getByText('Post journal')).toBeEnabled()); fireEvent.click(screen.getByText('Post journal'))
    await waitFor(() => expect(api.postJournal).toHaveBeenCalledWith(expect.objectContaining({ currency: null, exchange_rate: null })))
    expect(api.fxRate).not.toHaveBeenCalled()
  })
  it("prefills the rate from the organisation's OWN stored rate, says where it came from, and lets the user override it", async () => {
    api.fxRate.mockResolvedValue({ data: { rate: '0.6700', rate_date: '2026-09-20', source: 'RBA' } })
    mount(); fill(); fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'usd' } })
    expect(await screen.findByDisplayValue('0.67')).toBeInTheDocument()
    expect(screen.getByTestId('fx-rate-note')).toHaveTextContent('Your stored rate: 1 USD = 0.67 AUD (2026-09-20, RBA)')
    await waitFor(() => expect(api.fxRate).toHaveBeenCalledWith('USD', expect.any(String)))
    fireEvent.change(screen.getByLabelText(/^Rate/), { target: { value: '0.655' } })
    await waitFor(() => expect(api.journalPreview).toHaveBeenLastCalledWith(expect.objectContaining({ currency: 'USD', exchange_rate: '0.655', amounts_are: 'no_tax' })))
  })
  it('never guesses: with no stored rate the field is empty, the user is told, and posting is blocked until a rate is entered', async () => {
    mount(); fill(); fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'EUR' } })
    expect(await screen.findByText(/no stored EUR rate/)).toBeInTheDocument(); expect(screen.getByLabelText(/^Rate/)).toHaveValue('')
    expect(screen.getByText('Post journal')).toBeDisabled(); expect(screen.getByText('Submit for approval')).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/^Rate/), { target: { value: '1.62' } }); await waitFor(() => expect(screen.getByText('Post journal')).toBeEnabled())
  })
  it('does not overwrite a rate the user typed when the date changes', async () => {
    api.fxRate.mockResolvedValue({ data: { rate: '0.6700', rate_date: '2026-09-20' } })
    mount(); fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'USD' } }); await screen.findByDisplayValue('0.67')
    fireEvent.change(screen.getByLabelText(/^Rate/), { target: { value: '0.9' } }); fireEvent.change(screen.getByLabelText('Date'), { target: { value: '2026-08-01' } })
    await waitFor(() => expect(api.fxRate).toHaveBeenLastCalledWith('USD', '2026-08-01')); expect(screen.getByLabelText(/^Rate/)).toHaveValue('0.9')
  })
  it('keeps GST available on a foreign-currency journal, says it is worked out in base currency, and sends the GST basis', async () => {
    mount(); fill(); fireEvent.change(screen.getByLabelText('GST'), { target: { value: 'inclusive' } }); fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'USD' } })
    expect(screen.getByLabelText('GST')).not.toBeDisabled(); expect(screen.getByTestId('fx-gst-note')).toHaveTextContent('worked out in AUD on the converted amount')
    fireEvent.change(screen.getByLabelText(/^Rate/), { target: { value: '1.5' } })
    await waitFor(() => expect(api.journalPreview).toHaveBeenLastCalledWith(expect.objectContaining({ currency: 'USD', exchange_rate: '1.5', amounts_are: 'inclusive' })), { timeout: 3000 })
  })
  it('a rate typed before the stored-rate lookup returns is NOT overwritten by the late response', async () => {
    let resolve; api.fxRate.mockImplementation(() => new Promise(r => { resolve = r }))
    mount(); fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'USD' } }); fireEvent.change(screen.getByLabelText(/^Rate/), { target: { value: '1.55' } })
    resolve({ data: { rate: '1.4', rate_date: '2026-09-01' } }); await waitFor(() => expect(screen.getByTestId('fx-rate-note')).toHaveTextContent('Your stored rate'))
    expect(screen.getByLabelText(/^Rate/)).toHaveValue('1.55')
  })
  it('shows the GST in dollars in the conversion note', async () => {
    api.fxRate.mockResolvedValue({ data: { rate: '1.5', rate_date: '2026-09-01' } })
    api.journalPreview.mockResolvedValue({ data: okPv({ total_debit: '165.00', fx: { currency: 'USD', rate: '1.50000000', foreign_total: '110.00', rounding: '0.00', base: 'AUD', gst_base: '15.00' } }) })
    mount(); fill(); fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'USD' } })
    expect(await screen.findByTestId('fx-note')).toHaveTextContent('including')
  })
  it('treats the base currency code as no conversion', async () => {
    mount(); await waitFor(() => expect(api.fxRates).toHaveBeenCalled()); fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'AUD' } })
    expect(screen.queryByLabelText(/^Rate/)).toBeNull(); expect(api.fxRate).not.toHaveBeenCalled()
  })
  it('shows the conversion, the amounts entered and what the ledger will hold', async () => {
    api.fxRate.mockResolvedValue({ data: { rate: '0.65', rate_date: '2026-09-01' } })
    api.journalPreview.mockResolvedValue({ data: okPv({ fx: { currency: 'USD', rate: '0.65000000', foreign_total: '1000.00', rounding: '0.00', base: 'AUD' }, lines: [
      { account_code: '445', account_name: 'Power', debit: '650.00', credit: '0.00', orig_debit: '1000.00', orig_credit: '0.00', description: null, is_gst: false }, { account_code: '805', account_name: 'Accrued', debit: '0.00', credit: '650.00', orig_debit: '0.00', orig_credit: '1000.00', description: null, is_gst: false }] }) })
    mount(); fill(); fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'USD' } })
    const note = await screen.findByTestId('fx-note'); expect(note).toHaveTextContent('1 USD = 0.65 AUD'); expect(note).toHaveTextContent(USD1000); expect(note).toHaveTextContent('$650.00')
    const pv = screen.getByTestId('preview'); expect(within(pv).getByText('USD entered')).toBeInTheDocument(); expect(within(pv).getAllByText(USD1000).length).toBeGreaterThan(0)
  })
  it('posts a foreign-currency journal with its currency and rate', async () => {
    api.fxRate.mockResolvedValue({ data: { rate: '0.65', rate_date: '2026-09-01' } })
    mount(); fill(); fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'USD' } }); await screen.findByDisplayValue('0.65')
    await waitFor(() => expect(screen.getByText('Post journal')).toBeEnabled()); fireEvent.click(screen.getByText('Post journal'))
    await waitFor(() => expect(api.postJournal).toHaveBeenCalledWith(expect.objectContaining({ currency: 'USD', exchange_rate: '0.65', amounts_are: 'no_tax' })))
  })
  it('surfaces the server\'s refusal (e.g. unbalanced in USD) without closing', async () => {
    api.journalPreview.mockResolvedValue({ data: okPv({ balanced: false, errors: ['Out of balance in USD by 10.00 (debits 100.00, credits 90.00).'] }) }); mount(); fill()
    expect(await screen.findByText(/Out of balance in USD by 10\.00/)).toBeInTheDocument(); expect(screen.getByText('Post journal')).toBeDisabled()
  })
})

describe('splitting a line across jobs', () => {
  const openSplit = async () => { mount(); fill(); await waitFor(() => expect(screen.getAllByText('Split across jobs').length).toBe(2)); fireEvent.click(screen.getAllByText('Split across jobs')[0]) }
  it('splits by percent and sends the parts as allocations', async () => {
    await openSplit()
    fireEvent.change(screen.getByLabelText('Split job 1'), { target: { value: '21' } }); fireEvent.change(screen.getByLabelText('Split value 1'), { target: { value: '60' } })
    fireEvent.change(screen.getByLabelText('Split job 2'), { target: { value: '22' } }); fireEvent.change(screen.getByLabelText('Split value 2'), { target: { value: '40' } })
    expect(screen.getByTestId('split')).toHaveTextContent('100% of 100% ✓')
    await waitFor(() => expect(api.journalPreview).toHaveBeenLastCalledWith(expect.objectContaining({ lines: expect.arrayContaining([expect.objectContaining({ account_id: 5, allocations: [{ tracking_option_ids: [21], percent: '60' }, { tracking_option_ids: [22], percent: '40' }] })]) })))
  })
  it('shows a running total that turns red until the shares add up', async () => {
    await openSplit(); fireEvent.change(screen.getByLabelText('Split value 1'), { target: { value: '60' } }); fireEvent.change(screen.getByLabelText('Split value 2'), { target: { value: '30' } })
    expect(screen.getByTestId('split')).toHaveTextContent('90% of 100%'); expect(screen.getByTestId('split')).not.toHaveTextContent('✓')
  })
  it('switches to amounts, checking against the line amount', async () => {
    await openSplit(); fireEvent.change(screen.getByLabelText('Split by'), { target: { value: 'amount' } })
    fireEvent.change(screen.getByLabelText('Split value 1'), { target: { value: '300' } }); fireEvent.change(screen.getByLabelText('Split value 2'), { target: { value: '700' } })
    expect(screen.getByTestId('split')).toHaveTextContent('1000 of 1000 ✓')
    await waitFor(() => expect(api.journalPreview).toHaveBeenLastCalledWith(expect.objectContaining({ lines: expect.arrayContaining([expect.objectContaining({ allocations: [{ tracking_option_ids: [], amount: '300' }, { tracking_option_ids: [], amount: '700' }] })]) })))
  })
  it('keeps an unassigned part (a share with no job) so the shares still add up on the server', async () => {
    await openSplit(); fireEvent.change(screen.getByLabelText('Split job 1'), { target: { value: '21' } }); fireEvent.change(screen.getByLabelText('Split value 1'), { target: { value: '70' } }); fireEvent.change(screen.getByLabelText('Split value 2'), { target: { value: '30' } })
    await waitFor(() => expect(api.journalPreview).toHaveBeenLastCalledWith(expect.objectContaining({ lines: expect.arrayContaining([expect.objectContaining({ allocations: [{ tracking_option_ids: [21], percent: '70' }, { tracking_option_ids: [], percent: '30' }] })]) })))
  })
  it('adds and removes parts, and can drop the split entirely', async () => {
    await openSplit(); fireEvent.click(screen.getByText('+ part')); expect(screen.getByLabelText('Split job 3')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Remove part 3')); expect(screen.queryByLabelText('Split job 3')).toBeNull()
    fireEvent.click(screen.getByText('Remove split')); expect(screen.queryByTestId('split')).toBeNull()
  })
  it('shows the split lines in the preview and loads a saved split back into the editor', async () => {
    api.journalPreview.mockResolvedValue({ data: okPv({ lines: [{ account_code: '445', account_name: 'Power', debit: '600.00', credit: '0.00', is_gst: false }, { account_code: '445', account_name: 'Power', debit: '400.00', credit: '0.00', is_gst: false }, { account_code: '805', account_name: 'Accrued', debit: '0.00', credit: '1000.00', is_gst: false }] }) })
    const initial = { date: '2026-09-30', narration: 'Saved split', lines: [{ account_id: 5, debit: '1000', credit: '0', allocations: [{ tracking_option_ids: [21], percent: '60' }, { tracking_option_ids: [22], percent: '40' }] }, { account_id: 9, debit: '0', credit: '1000' }] }
    mount({ initial }); expect(screen.getByLabelText('Split job 1')).toHaveValue('21'); expect(screen.getByLabelText('Split value 2')).toHaveValue('40')
    expect(await screen.findByText('Will post')).toBeInTheDocument(); expect(within(screen.getByTestId('preview')).getAllByText('445 · Power').length).toBe(2)
  })
})

describe('exchange rates manager', () => {
  const rates = { base: 'AUD', items: [{ id: 3, currency: 'USD', date: '2026-09-20', rate: '0.6700', source: 'RBA' }] }
  beforeEach(() => api.fxRates.mockResolvedValue({ data: rates }))
  it('lists the organisation\'s rates and explains nothing is guessed', async () => {
    render(<FxRatesModal onClose={() => {}} />); expect(await screen.findByText('RBA')).toBeInTheDocument(); expect(screen.getByText(/Nothing is ever fetched or guessed/)).toBeInTheDocument(); expect(screen.getByText('0.67')).toBeInTheDocument()
  })
  it('saves a new rate (currency upper-cased) and reloads', async () => {
    render(<FxRatesModal onClose={() => {}} />); await screen.findByText('RBA')
    expect(screen.getByText('Save rate')).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Rate currency'), { target: { value: 'eur' } }); fireEvent.change(screen.getByLabelText('Rate value'), { target: { value: '1.62' } }); fireEvent.change(screen.getByLabelText('Rate source'), { target: { value: 'bank' } })
    fireEvent.click(screen.getByText('Save rate')); await waitFor(() => expect(api.putFxRate).toHaveBeenCalledWith(expect.objectContaining({ currency: 'EUR', rate: '1.62', source: 'bank' })))
    expect(toast.success).toHaveBeenCalledWith('Rate saved'); await waitFor(() => expect(api.fxRates.mock.calls.length).toBeGreaterThan(1))
  })
  it('shows the server message for a bad rate', async () => {
    api.putFxRate.mockRejectedValueOnce({ response: { data: { detail: 'The exchange rate is outside a sensible range' } } })
    render(<FxRatesModal onClose={() => {}} />); await screen.findByText('RBA'); fireEvent.change(screen.getByLabelText('Rate currency'), { target: { value: 'EUR' } }); fireEvent.change(screen.getByLabelText('Rate value'), { target: { value: '99999999' } })
    fireEvent.click(screen.getByText('Save rate')); await waitFor(() => expect(toast.error).toHaveBeenCalledWith('The exchange rate is outside a sensible range'))
  })
  it('deletes only after confirmation', async () => {
    window.confirm = vi.fn(() => false); render(<FxRatesModal onClose={() => {}} />); fireEvent.click(await screen.findByText('Delete')); expect(api.deleteFxRate).not.toHaveBeenCalled()
    window.confirm = vi.fn(() => true); fireEvent.click(screen.getByText('Delete')); await waitFor(() => expect(api.deleteFxRate).toHaveBeenCalledWith(3))
  })
  it('opens from the Journals tab', async () => {
    render(<JournalsTab canApprove requireApproval={false} />); fireEvent.click(await screen.findByText('Exchange rates')); expect(await screen.findByText(/Rates are 1 unit of the foreign currency/)).toBeInTheDocument()
  })
})

describe('foreign-currency journals in the list and detail', () => {
  const fj = { id: 1, journal_no: 9, date: '2026-09-20', narration: 'Freight', reference: null, source_type: 'manual', status: 'posted', total: '650.00', currency: 'USD', reversal_of_id: null, reversed_by_id: null }
  const detail = { ...fj, exchange_rate: '0.65000000', lines: [{ line_no: 1, account_code: '445', account_name: 'Power', debit: '650.00', credit: '0.00', orig_debit: '1000.00', orig_credit: '0.00', tax_amount: '0.00', tracking: [] }, { line_no: 2, account_code: '805', account_name: 'Accrued', debit: '0.00', credit: '650.00', orig_debit: '0.00', orig_credit: '1000.00', tax_amount: '0.00', tracking: [] }], source: { label: 'manual' }, attachments: [] }
  it('badges the currency in the list, shows the rate and both amounts in the detail, and copies the ORIGINAL amounts', async () => {
    api.journals.mockResolvedValue({ data: { items: [fj], total: 1, sum_total: '650.00' } }); api.journal.mockResolvedValue({ data: detail })
    render(<JournalsTab canApprove requireApproval={false} />); expect(await screen.findByText('USD')).toBeInTheDocument()
    fireEvent.click(screen.getByText('View')); const v = await screen.findByTestId('fx-view'); expect(v).toHaveTextContent('1 USD = 0.65')
    expect(screen.getAllByText(USD1000).length).toBe(2)
    fireEvent.click(screen.getByText('Copy to new journal')); expect(await screen.findByLabelText('Debit 1')).toHaveValue('1000.00'); expect(screen.getByLabelText('Currency')).toHaveValue('USD')
  })
})

describe('AI suggestions opt-in and source badges', () => {
  const d = (src, type = 'coding') => ({ id: 1, kind: 'ai_bank', status: 'submitted', confidence: '0.8000', reason: 'why', lines: [{ account_code: '445', debit: '10.00', credit: '0.00' }], suggestion: { type, source: src, match: 'INV-1', account_id: 5, bank_line: { id: 1, date: '2026-09-01', description: 'X', amount: '-10.00' } } })
  it('labels where every suggestion came from', () => {
    const t = x => render(sourceBadge(x)).container.textContent
    expect(t(d('llm'))).toBe('AI'); expect(t(d('rdr'))).toBe('Platform rule'); expect(t(d('learned'))).toBe('Learned'); expect(t(d('rule:4'))).toBe('Your rule'); expect(t(d(undefined, 'match'))).toBe('Match')
  })
  it('shows the badge beside each suggestion', async () => {
    api.journalDrafts.mockResolvedValue({ data: { items: [d('llm')], counts: {} } }); render(<ReviewTab canApprove requireApproval={false} />)
    expect(await screen.findByText('AI')).toBeInTheDocument()
  })
  it('asks for informed consent before turning AI on, and does nothing if declined', async () => {
    const onLlm = vi.fn(); window.confirm = vi.fn(() => false); render(<ReviewTab canApprove requireApproval={false} llmEnabled={false} onLlm={onLlm} />)
    fireEvent.click(await screen.findByLabelText(/Use AI for lines with no rule/)); expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('sent to Groq')); expect(onLlm).not.toHaveBeenCalled()
    window.confirm = vi.fn(() => true); fireEvent.click(screen.getByLabelText(/Use AI for lines with no rule/)); expect(onLlm).toHaveBeenCalledWith(true)
  })
  it('turning it off needs no confirmation', async () => {
    const onLlm = vi.fn(); render(<ReviewTab canApprove requireApproval={false} llmEnabled onLlm={onLlm} />); fireEvent.click(await screen.findByLabelText(/Use AI for lines with no rule/))
    expect(onLlm).toHaveBeenCalledWith(false); expect(window.confirm).not.toHaveBeenCalled()
  })
  it('hides the AI switch from people who cannot approve', async () => {
    render(<ReviewTab canApprove={false} requireApproval={false} />); await screen.findByText(/AI & rule suggestions/); expect(screen.queryByLabelText(/Use AI/)).toBeNull()
  })
  it('reports how many came from platform rules and AI, and tells the user when the AI could not be reached', async () => {
    api.generateSuggestions.mockResolvedValue({ data: { created: 5, matches: 1, coded: 4, rdr: 2, llm: 1, llm_unavailable: 'No Groq key is available' } })
    render(<ReviewTab canApprove requireApproval={false} />); fireEvent.click(await screen.findByText('Find suggestions from bank lines'))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('5 new suggestion(s) — 1 matches, 4 coded (2 from platform rules, 1 by AI)')); expect(toast.error).toHaveBeenCalledWith('AI unavailable: No Groq key is available')
  })
})

describe('automatic repeating journals', () => {
  it('shows whether the scheduler is on, how often it checks, and what the last check did', async () => {
    render(<RepeatingTab canApprove />); const s = await screen.findByTestId('scheduler-status')
    expect(s).toHaveTextContent('Automatic runs are on'); expect(s).toHaveTextContent('every 15 min'); expect(s).toHaveTextContent('2 template(s) opted in'); expect(s).toHaveTextContent('2 draft(s), 1 posted')
  })
  it('says so when the scheduler is switched off on the server', async () => {
    api.schedulerStatus.mockResolvedValue({ data: { enabled: false, interval_seconds: 900, timezone: 'x', auto_templates: 0, last_sweep: null } }); render(<RepeatingTab canApprove />)
    expect(await screen.findByTestId('scheduler-status')).toHaveTextContent('Automatic runs are off')
  })
  it('surfaces errors from the last check and the no-check-yet case', async () => {
    api.schedulerStatus.mockResolvedValue({ data: { enabled: true, interval_seconds: 900, timezone: 'x', auto_templates: 1, last_sweep: { at: '2026-09-30T01:15:00Z', drafts: 0, posted: 0, errors: [{}, {}] } } }); const a = render(<RepeatingTab canApprove />)
    expect(await screen.findByTestId('scheduler-status')).toHaveTextContent('2 error(s)'); a.unmount()
    api.schedulerStatus.mockResolvedValue({ data: { enabled: true, interval_seconds: 900, timezone: 'x', auto_templates: 1, last_sweep: null } }); render(<RepeatingTab canApprove />)
    expect(await screen.findByTestId('scheduler-status')).toHaveTextContent('No check has run yet')
  })
  it('marks auto-run and foreign-currency templates in the list', async () => {
    api.repeatingJournals.mockResolvedValue({ data: { items: [{ id: 1, name: 'Retainer', frequency: 'monthly', next_date: '2099-01-01', mode: 'post', is_active: true, auto_run: true, currency: 'GBP', runs: 0, lines: [] }] } })
    render(<RepeatingTab canApprove />); expect(await screen.findByText('auto')).toBeInTheDocument(); expect(screen.getByText('GBP')).toBeInTheDocument()
  })
  it('lets the user opt a template into automatic runs and set its currency', async () => {
    const onDone = vi.fn(); render(<RepeatingEditor accounts={ACC} taxes={[]} categories={[]} canApprove onClose={() => {}} onDone={onDone} />)
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Retainer' } }); fireEvent.change(screen.getByLabelText('Account 1'), { target: { value: '5' } }); fireEvent.change(screen.getByLabelText('Debit 1'), { target: { value: '10' } })
    fireEvent.change(screen.getByLabelText('Account 2'), { target: { value: '9' } }); fireEvent.change(screen.getByLabelText('Credit 2'), { target: { value: '10' } })
    fireEvent.click(screen.getByLabelText(/Run automatically when due/)); fireEvent.change(screen.getByLabelText('Currency (optional)'), { target: { value: 'gbp' } })
    expect(screen.getByText(/uses YOUR stored GBP rate/)).toBeInTheDocument(); await waitFor(() => expect(screen.getByText('Save')).toBeEnabled()); fireEvent.click(screen.getByText('Save'))
    await waitFor(() => expect(api.createRepeating).toHaveBeenCalledWith(expect.objectContaining({ auto_run: true, currency: 'GBP', amounts_are: 'no_tax' }))); await waitFor(() => expect(onDone).toHaveBeenCalled())
  })
})
