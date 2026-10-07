import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

vi.mock('../../../../../core/lib/platformApi.js', () => {
  const ok = data => vi.fn(() => Promise.resolve({ data }))
  return {
    errMsg: e => e?.response?.data?.detail || e?.message || 'err',
    fxRates: ok({ base: 'AUD', items: [] }), putFxRate: ok({}), deleteFxRate: ok({}), fxRate: ok({ rate: null }),
    fxFeed: ok({ enabled: false, currencies: [], effective_currencies: ['EUR', 'USD'], source: 'ECB', base: 'AUD', last_run: null }), fxFeedRun: ok({ stored: 4, updated: 0, kept_manual: 1, unsupported: [] }),
    fxAccounts: ok({ base: 'AUD', items: [] }), setFxAccount: ok({}), fxRevaluation: ok({ as_at: '2026-09-30', base: 'AUD', rows: [], missing_rates: [], can_post: false }), fxRevalue: ok({ posted: [], nothing_to_do: true }),
    fxGainsLosses: ok({ from: '2025-07-01', to: '2026-09-30', base: 'AUD', realised: { total: '29.67', by_currency: [] }, unrealised: { total: '-471.90', by_currency: [] }, net: '-442.23', positions: [] }),
    aiJournal: ok({}), aiExplainPL: ok({}), aiReviewDraft: ok({}),
    journalDrafts: ok({ items: [], counts: {} }), journalDraft: ok({}), approveDraft: ok({}), rejectDraft: ok({}), submitDraft: ok({}), deleteDraft: ok({}), bulkApprove: ok({}), generateSuggestions: ok({ created: 0 }),
    accounts: ok([]), taxCodes: ok([]), tracking: ok([]), createDraft: ok({}), updateDraft: ok({}), postJournal: ok({}), journalPreview: ok(null),
  }
})
vi.mock('../../../lib/ledgerApi.js', () => {
  const ok = data => vi.fn(() => Promise.resolve({ data }))
  return {
    errMsg: e => e?.response?.data?.detail || e?.message || 'err',
    fxRates: ok({ base: 'AUD', items: [] }), putFxRate: ok({}), deleteFxRate: ok({}), fxRate: ok({ rate: null }),
    fxFeed: ok({ enabled: false, currencies: [], effective_currencies: ['EUR', 'USD'], source: 'ECB', base: 'AUD', last_run: null }), fxFeedRun: ok({ stored: 4, updated: 0, kept_manual: 1, unsupported: [] }),
    fxAccounts: ok({ base: 'AUD', items: [] }), setFxAccount: ok({}), fxRevaluation: ok({ as_at: '2026-09-30', base: 'AUD', rows: [], missing_rates: [], can_post: false }), fxRevalue: ok({ posted: [], nothing_to_do: true }),
    fxGainsLosses: ok({ from: '2025-07-01', to: '2026-09-30', base: 'AUD', realised: { total: '29.67', by_currency: [] }, unrealised: { total: '-471.90', by_currency: [] }, net: '-442.23', positions: [] }),
    aiJournal: ok({}), aiExplainPL: ok({}), aiReviewDraft: ok({}),
    journalDrafts: ok({ items: [], counts: {} }), journalDraft: ok({}), approveDraft: ok({}), rejectDraft: ok({}), submitDraft: ok({}), deleteDraft: ok({}), bulkApprove: ok({}), generateSuggestions: ok({ created: 0 }),
    accounts: ok([]), taxCodes: ok([]), tracking: ok([]), createDraft: ok({}), updateDraft: ok({}), postJournal: ok({}), journalPreview: ok(null),
  }
})
vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
import * as api from '../../../lib/ledgerApi.js'
import toast from 'react-hot-toast'
import FxTab from '../FxTab.jsx'
import AiTab from '../AiTab.jsx'
import { ReviewTab } from '../JournalTools.jsx'
import { money } from '../JournalEditor.jsx'

const norm = s => s.replace(/\s/g, ' ')
const has = (el, text) => expect(norm(el.textContent)).toContain(norm(text))
const mountFx = (o = {}) => { const onSettings = vi.fn(() => Promise.resolve({})); render(<FxTab canApprove settings={{ fx_feed_enabled: false }} onSettings={onSettings} onChanged={() => {}} {...o} />); return onSettings }
const PV = { as_at: '2026-09-30', base: 'AUD', missing_rates: [], can_post: true, rows: [
  { account_id: 1, code: 'USD-OPS', name: 'USD Operating', currency: 'USD', foreign_balance: '10890.00', historical_base: '16698.00', rate: '1.48000000', revalued_base: '16117.20', adjustment: '-580.80', already_booked: '0.00', to_post: '-580.80' }] }
beforeEach(() => { vi.clearAllMocks(); window.confirm = vi.fn(() => true)
  api.fxAccounts.mockResolvedValue({ data: { base: 'AUD', items: [] } }); api.fxRevaluation.mockResolvedValue({ data: { as_at: '2026-09-30', base: 'AUD', rows: [], missing_rates: [], can_post: false } })
  api.fxFeed.mockResolvedValue({ data: { enabled: false, currencies: [], effective_currencies: ['EUR', 'USD'], source: 'ECB', base: 'AUD', last_run: null } }) })

describe('rates and the automatic feed', () => {
  it('explains the source honestly and lists the effective currencies', async () => {
    mountFx(); const p = await screen.findByTestId('feed-panel'); has(p, 'ECB reference rates'); has(p, 'never overwritten'); has(p, 'not what your bank charged'); await waitFor(() => has(screen.getByTestId('feed-currencies'), 'EUR, USD'))
  })
  it('turns the daily feed on and saves extra currencies (approvers only)', async () => {
    const onSettings = mountFx(); fireEvent.click(await screen.findByLabelText(/Fetch rates automatically/)); expect(onSettings).toHaveBeenCalledWith({ fx_feed_enabled: true })
    fireEvent.change(screen.getByLabelText('Extra currencies'), { target: { value: 'gbp, jpy' } }); fireEvent.click(screen.getByText('Save currencies')); await waitFor(() => expect(onSettings).toHaveBeenCalledWith({ fx_feed_currencies: ['GBP', 'JPY'] }))
  })
  it('fetches now and after a back-fill, reporting what was stored and what of yours was kept', async () => {
    mountFx(); fireEvent.click(await screen.findByText('Fetch now')); await waitFor(() => expect(api.fxFeedRun).toHaveBeenCalledWith({ backfill: false })); expect(toast.success).toHaveBeenCalledWith('4 rate(s) stored, 1 of yours kept')
    fireEvent.click(screen.getByText('Back-fill 90 days')); await waitFor(() => expect(api.fxFeedRun).toHaveBeenLastCalledWith({ backfill: true }))
  })
  it('reports currencies the source does not publish and a failed fetch', async () => {
    api.fxFeedRun.mockResolvedValueOnce({ data: { stored: 0, updated: 0, kept_manual: 0, unsupported: ['XXX'] } }); mountFx(); fireEvent.click(await screen.findByText('Fetch now')); await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Not published by the source: XXX'))
    api.fxFeedRun.mockRejectedValueOnce({ response: { data: { detail: 'Could not reach the rate source (ConnectionError). Existing rates are unchanged' } } }); fireEvent.click(screen.getByText('Fetch now')); await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('Existing rates are unchanged')))
  })
  it('shows the last fetch, and a failure in red words', async () => {
    api.fxFeed.mockResolvedValue({ data: { enabled: true, currencies: [], effective_currencies: ['USD'], source: 'ECB', base: 'AUD', last_run: { ok: false, error: 'Could not reach the rate source' } } }); mountFx()
    has(await screen.findByTestId('feed-last'), 'Last fetch failed: Could not reach the rate source')
  })
  it('hides the controls from people who cannot approve', async () => {
    mountFx({ canApprove: false }); await screen.findByTestId('feed-panel'); expect(screen.queryByText('Fetch now')).toBeNull(); expect(screen.queryByLabelText(/Fetch rates automatically/)).toBeNull()
  })
  it('opens the rates editor', async () => { mountFx(); fireEvent.click(await screen.findByText('Enter or edit rates')); expect(await screen.findByText(/Nothing is ever fetched or guessed/)).toBeInTheDocument() })
})

describe('foreign-currency accounts', () => {
  const items = [{ id: 1, code: 'USD-OPS', name: 'USD Operating', type: 'bank', currency: 'USD', has_postings: true, foreign_balance: '10890.00', base_value: '16698.00' },
    { id: 2, code: '091', name: 'New bank', type: 'bank', currency: null, has_postings: false }, { id: 3, code: '090', name: 'Everyday', type: 'bank', currency: null, has_postings: true }]
  beforeEach(() => api.fxAccounts.mockResolvedValue({ data: { base: 'AUD', items } }))
  it('lists foreign accounts with the foreign balance and dollar cost', async () => {
    mountFx(); const t = await screen.findByTestId('accounts-panel'); await waitFor(() => has(t, 'USD-OPS · USD Operating')); has(t, money('10890', 'USD')); has(t, money('16698'))
  })
  it('will not offer an account that already has postings', async () => {
    mountFx(); const sel = await screen.findByLabelText('Account to hold in a foreign currency'); await waitFor(() => expect(within(sel).getByText(/090 Everyday \(has postings\)/)).toBeDisabled()); expect(within(sel).getByText('091 New bank')).not.toBeDisabled()
  })
  it('asks for confirmation, then sets the currency', async () => {
    mountFx(); const sel = await screen.findByLabelText('Account to hold in a foreign currency'); await waitFor(() => within(sel).getByText('091 New bank'))
    expect(screen.getByTestId('set-fx-account')).toBeDisabled(); fireEvent.change(sel, { target: { value: '2' } }); fireEvent.change(screen.getByLabelText('Currency code'), { target: { value: 'eur' } })
    window.confirm = vi.fn(() => false); fireEvent.click(screen.getByTestId('set-fx-account')); expect(api.setFxAccount).not.toHaveBeenCalled()
    window.confirm = vi.fn(() => true); fireEvent.click(screen.getByTestId('set-fx-account')); await waitFor(() => expect(api.setFxAccount).toHaveBeenCalledWith(2, 'EUR')); expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('every posting to it must be in EUR'))
  })
  it('shows the server message when it cannot be changed', async () => {
    api.setFxAccount.mockRejectedValueOnce({ response: { data: { detail: 'already has postings' } } }); mountFx(); const sel = await screen.findByLabelText('Account to hold in a foreign currency'); await waitFor(() => within(sel).getByText('091 New bank'))
    fireEvent.change(sel, { target: { value: '2' } }); fireEvent.change(screen.getByLabelText('Currency code'), { target: { value: 'EUR' } }); fireEvent.click(screen.getByTestId('set-fx-account')); await waitFor(() => expect(toast.error).toHaveBeenCalledWith('already has postings'))
  })
})

describe('period-end revaluation', () => {
  it('shows balance, cost, closing rate, revalued amount and the unrealised loss', async () => {
    api.fxRevaluation.mockResolvedValue({ data: PV }); mountFx(); const t = await screen.findByTestId('reval-table')
    has(t, money('10890', 'USD')); has(t, money('16698')); has(t, '1.48'); has(t, money('16117.20')); has(t, money('-580.80'))
  })
  it('refuses to guess: a missing rate is shown, and posting is disabled', async () => {
    api.fxRevaluation.mockResolvedValue({ data: { ...PV, missing_rates: ['EUR'], can_post: false } }); mountFx()
    has(await screen.findByTestId('missing-rates'), 'EUR'); has(screen.getByTestId('missing-rates'), 'will not guess'); expect(screen.getByText('Post revaluation')).toBeDisabled()
  })
  it('confirms, posts with the reversal choice, and reports the result', async () => {
    api.fxRevaluation.mockResolvedValue({ data: PV }); api.fxRevalue.mockResolvedValue({ data: { posted: [{ currency: 'USD' }], nothing_to_do: false } }); mountFx()
    await screen.findByTestId('reval-table'); fireEvent.click(screen.getByText('Post revaluation')); expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('reverses it automatically the next day'))
    await waitFor(() => expect(api.fxRevalue).toHaveBeenCalledWith({ as_at: expect.any(String), reverse: true })); expect(toast.success).toHaveBeenCalledWith('Posted 1 revaluation journal(s)')
  })
  it('can post without an automatic reversal, with a clear warning', async () => {
    api.fxRevaluation.mockResolvedValue({ data: PV }); mountFx(); await screen.findByTestId('reval-table'); fireEvent.click(screen.getByLabelText(/Reverse automatically/)); fireEvent.click(screen.getByText('Post revaluation'))
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('will NOT reverse itself')); await waitFor(() => expect(api.fxRevalue).toHaveBeenCalledWith(expect.objectContaining({ reverse: false })))
  })
  it('does nothing if the confirmation is declined', async () => {
    api.fxRevaluation.mockResolvedValue({ data: PV }); window.confirm = vi.fn(() => false); mountFx(); await screen.findByTestId('reval-table'); fireEvent.click(screen.getByText('Post revaluation')); expect(api.fxRevalue).not.toHaveBeenCalled()
  })
  it('says when it is already up to date, and hides posting from non-approvers', async () => {
    api.fxRevaluation.mockResolvedValue({ data: { ...PV, can_post: false } }); const a = mountFx(); await screen.findByText('Already up to date at this date.'); expect(screen.getByText('Post revaluation')).toBeDisabled()
    api.fxRevaluation.mockResolvedValue({ data: PV }); render(<FxTab canApprove={false} settings={{}} onSettings={() => {}} />); expect(await screen.findByText('Only an approver can post a revaluation.')).toBeInTheDocument()
  })
  it('shows a friendly line when there is nothing to revalue', async () => { mountFx(); expect(await screen.findByText(/No foreign-currency account has a balance/)).toBeInTheDocument() })
  it('surfaces a server refusal', async () => {
    api.fxRevaluation.mockResolvedValue({ data: PV }); api.fxRevalue.mockRejectedValueOnce({ response: { data: { detail: 'Date is on or before the lock date' } } }); mountFx(); await screen.findByTestId('reval-table'); fireEvent.click(screen.getByText('Post revaluation'))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Date is on or before the lock date'))
  })
})

describe('gains and losses report', () => {
  it('shows realised, unrealised and net, with gains and losses labelled', async () => {
    api.fxGainsLosses.mockResolvedValue({ data: { from: '2025-07-01', to: '2026-09-30', base: 'AUD', realised: { total: '29.67', by_currency: [{ currency: 'USD', amount: '29.67' }] }, unrealised: { total: '-471.90', by_currency: [{ currency: 'USD', amount: '-471.90' }] }, net: '-442.23',
      positions: [{ code: 'USD-OPS', name: 'USD Operating', currency: 'USD', foreign_balance: '10890.00', historical_base: '16698.00', revalued_base: '16226.10' }] } })
    mountFx(); const p = await screen.findByTestId('gl-panel'); await waitFor(() => has(p, 'Realised (gain)')); has(p, 'Unrealised (loss)'); has(p, 'Net (loss)'); has(p, money('-442.23')); has(p, 'Realised by currency: USD'); has(p, money('16226.10'))
  })
  it('re-runs for the chosen dates', async () => {
    mountFx(); await waitFor(() => expect(api.fxGainsLosses).toHaveBeenCalled()); fireEvent.change(screen.getByLabelText('Gains from'), { target: { value: '2026-01-01' } }); fireEvent.click(screen.getByText('Run'))
    await waitFor(() => expect(api.fxGainsLosses).toHaveBeenLastCalledWith('2026-01-01', expect.any(String)))
  })
})

describe('AI assistant', () => {
  const proposal = { proposal: { date: '2026-12-31', narration: 'Accrue December audit fees', lines: [{ account_id: 5, debit: '4500.00', credit: '', description: 'Audit fee' }, { account_id: 9, debit: '', credit: '4500.00' }] },
    preview: { lines: [{ account_code: '445', account_name: 'Power', description: 'Audit fee', debit: '4500.00', credit: '0.00' }, { account_code: '805', account_name: 'Accrued', debit: '0.00', credit: '4500.00' }] }, notes: 'Assumed no GST', reverse_next_month: true, dropped: [], errors: [], balanced: true, advisory: 'Generated by AI - check every account and amount before posting. Nothing has been saved.' }
  it('is off by default: explains itself, hides the tools, and asks for informed consent before turning on', () => {
    const onSettings = vi.fn(); render(<AiTab canApprove settings={{}} onSettings={onSettings} onOpenEditor={() => {}} />)
    expect(screen.getByText('off')).toBeInTheDocument(); expect(screen.queryByTestId('describe')).toBeNull()
    window.confirm = vi.fn(() => false); fireEvent.click(screen.getByLabelText(/Use AI assistance/)); expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('Contact names are never sent')); expect(onSettings).not.toHaveBeenCalled()
    window.confirm = vi.fn(() => true); fireEvent.click(screen.getByLabelText(/Use AI assistance/)); expect(onSettings).toHaveBeenCalledWith({ llm_assist: true })
  })
  it('only approvers can switch it on', () => { render(<AiTab canApprove={false} settings={{}} onSettings={() => {}} onOpenEditor={() => {}} />); expect(screen.queryByLabelText(/Use AI assistance/)).toBeNull(); expect(screen.getByText('Only an approver can turn this on.')).toBeInTheDocument() })
  it('drafts a journal from a sentence and hands it to the editor - nothing is saved', async () => {
    api.aiJournal.mockResolvedValue({ data: proposal }); const open = vi.fn(); render(<AiTab canApprove settings={{ llm_assist: true }} onSettings={() => {}} onOpenEditor={open} />)
    const btn = screen.getByText('Draft it'); expect(btn.closest('button')).toBeDisabled(); fireEvent.change(screen.getByLabelText('Describe the journal'), { target: { value: 'Accrue $4,500 audit fees for December' } })
    fireEvent.click(screen.getByText('Draft it')); const p = await screen.findByTestId('proposal'); has(p, '445 · Power'); has(p, 'Assumption: Assumed no GST'); has(p, 'Reverse automatically'); has(p, 'Nothing has been saved')
    fireEvent.click(screen.getByText('Open in the journal editor')); expect(open).toHaveBeenCalledWith(expect.objectContaining({ narration: 'Accrue December audit fees', lines: [expect.objectContaining({ account_id: 5, debit: '4500.00', credit: '0' }), expect.objectContaining({ account_id: 9, debit: '0', credit: '4500.00' })] }))
  })
  it('shows dropped lines and problems but still lets the person fix it in the editor', async () => {
    api.aiJournal.mockResolvedValue({ data: { ...proposal, dropped: ['Line 2: the assistant chose an account (\'9999\') that is not in your chart - line dropped'], errors: ['Out of balance by 100.00'], balanced: false } })
    render(<AiTab canApprove settings={{ llm_assist: true }} onSettings={() => {}} onOpenEditor={() => {}} />); fireEvent.change(screen.getByLabelText('Describe the journal'), { target: { value: 'something long enough' } }); fireEvent.click(screen.getByText('Draft it'))
    has(await screen.findByTestId('proposal'), '9999'); has(screen.getByTestId('proposal-errors'), 'Out of balance by 100.00'); expect(screen.getByText('Open in the journal editor')).toBeInTheDocument()
  })
  it('shows the server message when the assistant cannot help', async () => {
    api.aiJournal.mockRejectedValueOnce({ response: { data: { detail: 'AI is not available right now: No Groq key is available' } } }); render(<AiTab canApprove settings={{ llm_assist: true }} onSettings={() => {}} onOpenEditor={() => {}} />)
    fireEvent.change(screen.getByLabelText('Describe the journal'), { target: { value: 'something long enough' } }); fireEvent.click(screen.getByText('Draft it')); await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('No Groq key')))
  })
  const EX = { headline: { net_profit: { current: '5000.00', previous: '3000.00', change: '2000.00' } }, movements: [{ code: '200', name: 'Sales', current: '9000.00', previous: '6000.00', change: '3000.00' }], commentary: 'Sales rose by 3000.00.', note: null, advisory: 'The figures are computed by AccFino.' }
  it('explains a change in profit: computed table always, commentary when allowed', async () => {
    api.aiExplainPL.mockResolvedValue({ data: EX }); render(<AiTab canApprove settings={{ llm_assist: true }} onSettings={() => {}} onOpenEditor={() => {}} />); fireEvent.click(screen.getByText('Explain'))
    has(await screen.findByTestId('commentary'), 'Sales rose by 3000.00.'); has(screen.getByTestId('movements'), '200 · Sales'); has(screen.getByTestId('movements'), money('3000')); has(screen.getByTestId('explain'), 'The figures are computed by AccFino')
  })
  it('shows only the table and a note when the commentary was withheld', async () => {
    api.aiExplainPL.mockResolvedValue({ data: { ...EX, commentary: null, note: 'AI commentary withheld: it quoted a figure that is not in your data (12345678.99).' } }); render(<AiTab canApprove settings={{ llm_assist: true }} onSettings={() => {}} onOpenEditor={() => {}} />); fireEvent.click(screen.getByText('Explain'))
    has(await screen.findByTestId('explain-note'), 'withheld'); expect(screen.queryByTestId('commentary')).toBeNull(); expect(screen.getByTestId('movements')).toBeInTheDocument()
  })
  it('sends the chosen periods', async () => {
    api.aiExplainPL.mockResolvedValue({ data: EX }); render(<AiTab canApprove settings={{ llm_assist: true }} onSettings={() => {}} onOpenEditor={() => {}} />)
    fireEvent.change(screen.getByLabelText('Period from'), { target: { value: '2026-08-01' } }); fireEvent.click(screen.getByText('Explain')); await waitFor(() => expect(api.aiExplainPL).toHaveBeenCalledWith(expect.objectContaining({ date_from: '2026-08-01' })))
  })
})

describe('AI review of a submitted draft', () => {
  const draft = { id: 7, kind: 'manual', status: 'submitted', date: '2026-09-30', narration: 'Accrue audit fee', confidence: null, created_by: 'Priya', amounts_are: 'no_tax', lines: [{ account_code: '445', account_name: 'Power', debit: '4500.00', credit: '0.00' }, { account_code: '805', account_name: 'Accrued', debit: '0.00', credit: '4500.00' }] }
  beforeEach(() => api.journalDrafts.mockResolvedValue({ data: { items: [draft], counts: {} } }))
  it('is offered to approvers only when AI assistance is on', async () => {
    const a = render(<ReviewTab canApprove requireApproval={false} assistEnabled={false} />); fireEvent.click(await screen.findByRole('button', { name: /Open/ })); await screen.findByText('Approve & post'); expect(screen.queryByText('AI review')).toBeNull(); a.unmount()
    render(<ReviewTab canApprove requireApproval={false} assistEnabled />); fireEvent.click(await screen.findByRole('button', { name: /Open/ })); expect(await screen.findByText('AI review')).toBeInTheDocument()
  })
  it('shows the verdict, the points, the automatic checks and that it is advisory', async () => {
    api.aiReviewDraft.mockResolvedValue({ data: { draft_id: 7, summary: 'Accrues an audit fee.', verdict: 'check', points: ['Confirm the period'], checks: ['Weekend date'], advisory: 'AI second opinion - advisory only. It cannot approve or change the journal.' } })
    render(<ReviewTab canApprove requireApproval={false} assistEnabled />); fireEvent.click(await screen.findByRole('button', { name: /Open/ })); fireEvent.click(await screen.findByText('AI review'))
    const r = await screen.findByTestId('ai-review'); has(r, 'check these points'); has(r, 'Accrues an audit fee.'); has(r, 'Confirm the period'); has(r, 'Weekend date'); has(r, 'cannot approve or change the journal'); expect(api.aiReviewDraft).toHaveBeenCalledWith(7)
    expect(screen.getByText('Approve & post')).toBeInTheDocument()
  })
  it('a clean verdict reads as such; a failure is shown as a message and leaves no panel', async () => {
    api.aiReviewDraft.mockResolvedValueOnce({ data: { verdict: 'ok', summary: 'Fine.', points: [], checks: [], advisory: 'x' } }); render(<ReviewTab canApprove requireApproval={false} assistEnabled />)
    fireEvent.click(await screen.findByRole('button', { name: /Open/ })); fireEvent.click(await screen.findByText('AI review')); has(await screen.findByTestId('ai-review'), 'nothing stands out')
    api.aiReviewDraft.mockRejectedValueOnce({ response: { data: { detail: 'AI is not available right now' } } }); fireEvent.click(screen.getByText('AI review')); await waitFor(() => expect(toast.error).toHaveBeenCalledWith('AI is not available right now')); await waitFor(() => expect(screen.queryByTestId('ai-review')).toBeNull())
  })
})
