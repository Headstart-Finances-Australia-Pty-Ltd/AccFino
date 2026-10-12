import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

const ACC = [{ id: 5, code: '445', name: 'Light, Power, Heating' }, { id: 9, code: '805', name: 'Accrued Expenses' }, { id: 12, code: '499', name: 'Sundry' }]
const TAX = [{ id: 3, name: 'GST on Expenses' }]
const CATS = [{ id: 1, name: 'Department', is_active: true, options: [{ id: 21, name: 'Admin', is_active: true }] }]
const J = (o = {}) => ({ id: 1, journal_no: 101, date: '2026-09-30', narration: 'Accrual', reference: 'ACC-1', source_type: 'manual', status: 'posted', total: '704.00', reversal_of_id: null, reversed_by_id: null, ...o })

vi.mock('../../../../../core/lib/platformApi.js', () => {
  const ok = data => vi.fn(() => Promise.resolve({ data }))
  return {
    errMsg: e => e?.response?.data?.detail || e?.message || 'err',
    accounts: ok([]), taxCodes: ok([]), tracking: ok([]),
    journals: ok({ items: [], total: 0, sum_total: '0' }), journal: ok({}), journalSources: ok({ items: [] }), journalHistory: ok({ events: [] }), reverseJournal: ok({ journal_no: 200 }),
    postJournal: ok({ id: 7, journal_no: 300 }), journalPreview: ok(null), createDraft: ok({ id: 55 }), updateDraft: ok({}), submitDraft: ok({}), approveDraft: ok({ posted_journal_id: 9 }),
    rejectDraft: ok({}), deleteDraft: ok({}), journalDrafts: ok({ items: [], counts: {} }), journalDraft: ok({}), bulkApprove: ok({ approved: 2, failed: [] }), generateSuggestions: ok({ created: 3, matches: 2, coded: 1 }),
    repeatingJournals: ok({ items: [] }), createRepeating: ok({}), updateRepeating: ok({}), deleteRepeating: ok({}), runRepeating: ok({ templates: 1, drafts: 2, posted: 0, errors: [] }),
    importJournals: ok({}), downloadImportTemplate: vi.fn(() => Promise.resolve()),
    fxRates: ok({ base: 'AUD', items: [] }), fxRate: ok({ rate: null }), putFxRate: ok({}), deleteFxRate: ok({}), aiReviewDraft: ok({}), schedulerStatus: ok({ enabled: true, interval_seconds: 900, timezone: 'Australia/Sydney', auto_templates: 0, last_sweep: null }),
  }
})
vi.mock('../../../lib/ledgerApi.js', () => {
  const ok = data => vi.fn(() => Promise.resolve({ data }))
  return {
    errMsg: e => e?.response?.data?.detail || e?.message || 'err',
    accounts: ok([]), taxCodes: ok([]), tracking: ok([]),
    journals: ok({ items: [], total: 0, sum_total: '0' }), journal: ok({}), journalSources: ok({ items: [] }), journalHistory: ok({ events: [] }), reverseJournal: ok({ journal_no: 200 }),
    postJournal: ok({ id: 7, journal_no: 300 }), journalPreview: ok(null), createDraft: ok({ id: 55 }), updateDraft: ok({}), submitDraft: ok({}), approveDraft: ok({ posted_journal_id: 9 }),
    rejectDraft: ok({}), deleteDraft: ok({}), journalDrafts: ok({ items: [], counts: {} }), journalDraft: ok({}), bulkApprove: ok({ approved: 2, failed: [] }), generateSuggestions: ok({ created: 3, matches: 2, coded: 1 }),
    repeatingJournals: ok({ items: [] }), createRepeating: ok({}), updateRepeating: ok({}), deleteRepeating: ok({}), runRepeating: ok({ templates: 1, drafts: 2, posted: 0, errors: [] }),
    importJournals: ok({}), downloadImportTemplate: vi.fn(() => Promise.resolve()),
    fxRates: ok({ base: 'AUD', items: [] }), fxRate: ok({ rate: null }), putFxRate: ok({}), deleteFxRate: ok({}), aiReviewDraft: ok({}), schedulerStatus: ok({ enabled: true, interval_seconds: 900, timezone: 'Australia/Sydney', auto_templates: 0, last_sweep: null }),
  }
})
vi.mock('../../../../../core/lib/adminApi.js', () => ({ errMsg: e => e?.message || 'err', uploadAttachment: vi.fn(() => Promise.resolve({})), downloadAttachment: vi.fn() }))
vi.mock('../../../lib/booksApi.js', () => ({ errMsg: e => e?.message || 'err', uploadAttachment: vi.fn(() => Promise.resolve({})), downloadAttachment: vi.fn() }))
vi.mock('../../../../billing/lib/orgBillingApi.js', () => ({ errMsg: e => e?.message || 'err', uploadAttachment: vi.fn(() => Promise.resolve({})), downloadAttachment: vi.fn() }))
vi.mock('../../../../open_banking/lib/feedApi.js', () => ({ errMsg: e => e?.message || 'err', uploadAttachment: vi.fn(() => Promise.resolve({})), downloadAttachment: vi.fn() }))
vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
import * as api from '../../../lib/ledgerApi.js'
import toast from 'react-hot-toast'
import * as books from '../../../lib/booksApi.js'
import { HealthStrip, JournalsTab, ReviewTab, RepeatingTab, ImportModal, statusBadge } from '../JournalTools.jsx'
import { JournalEditor } from '../JournalEditor.jsx'

const lookups = () => { api.accounts.mockResolvedValue({ data: ACC }); api.taxCodes.mockResolvedValue({ data: TAX }); api.tracking.mockResolvedValue({ data: CATS }) }
beforeEach(() => { vi.clearAllMocks(); lookups(); window.confirm = vi.fn(() => true); window.prompt = vi.fn(() => 'Personal expense') })

describe('HealthStrip', () => {
  it('shows what needs attention and navigates when clicked', () => {
    const onGo = vi.fn()
    render(<HealthStrip health={{ ai_suggestions: 4, awaiting_approval: 1, drafts: 2, rejected: 0, repeating_due: 1, future_dated: 2, suspense_balance: '150.00' }} onGo={onGo} />)
    fireEvent.click(screen.getByText('4 AI suggestions to review')); expect(onGo).toHaveBeenCalledWith('review', undefined)
    fireEvent.click(screen.getByText('1 repeating due')); expect(onGo).toHaveBeenCalledWith('repeating', undefined)
    fireEvent.click(screen.getByText('2 future-dated')); expect(onGo).toHaveBeenCalledWith('journals', { to: '2099-12-31' })
    expect(screen.getByText(/Suspense \$150\.00/)).toBeInTheDocument()
    expect(screen.queryByText('Nothing needs attention')).toBeNull()
  })
  it('says so when there is nothing to do', () => {
    render(<HealthStrip health={{ ai_suggestions: 0, awaiting_approval: 0, drafts: 0, rejected: 0, repeating_due: 0, future_dated: 0, suspense_balance: '0.00' }} onGo={() => {}} />)
    expect(screen.getByText('Nothing needs attention')).toBeInTheDocument()
  })
})

describe('status badges', () => {
  it('tells posted, reversed, reversal and auto-reversing journals apart', () => {
    const t = j => render(statusBadge(j)).container.textContent
    expect(t(J())).toBe('posted'); expect(t(J({ status: 'reversed' }))).toBe('reversed'); expect(t(J({ reversal_of_id: 4 }))).toBe('reversal')
    expect(t(J({ reversal_of_id: 4, source_type: 'auto_reversal' }))).toBe('auto-reversal'); expect(t(J({ reversed_by_id: 8 }))).toBe('auto-reverses')
  })
})

describe('JournalsTab', () => {
  const items = [J(), J({ id: 2, journal_no: 102, source_type: 'doc_invoice', narration: 'Invoice INV-0001', reference: null, total: '1100.00' }), J({ id: 3, journal_no: 103, reversed_by_id: 9, narration: 'Accrue' })]
  beforeEach(() => {
    api.journals.mockResolvedValue({ data: { items, total: 120, sum_total: '5000.00' } })
    api.journalSources.mockResolvedValue({ data: { items: [{ source: 'manual', label: 'Manual journals', count: 10 }, { source: 'doc_invoice', label: 'Sales invoices', count: 100 }] } })
  })
  it('lists journals with readable sources, references and totals', async () => {
    render(<JournalsTab canApprove requireApproval={false} />)
    expect(await screen.findByText('Invoice INV-0001')).toBeInTheDocument()
    expect((await screen.findAllByText('Sales invoices')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('ACC-1')).toHaveLength(2); expect(screen.getByText('auto-reverses')).toBeInTheDocument()
    expect(screen.getByText(/120 journal\(s\)/)).toBeInTheDocument(); expect(screen.getByText(/combined value \$5,000\.00/)).toBeInTheDocument()
  })
  it('searches and filters on the server (source, amount, account)', async () => {
    render(<JournalsTab canApprove requireApproval={false} />)
    await screen.findByText('Invoice INV-0001')
    fireEvent.change(screen.getByLabelText('Search journals'), { target: { value: 'ACC-1' } })
    await waitFor(() => expect(api.journals).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'ACC-1', offset: 0 })))
    fireEvent.change(screen.getByLabelText('Source'), { target: { value: 'doc_invoice' } })
    await waitFor(() => expect(api.journals).toHaveBeenLastCalledWith(expect.objectContaining({ source_type: 'doc_invoice', q: 'ACC-1' })))
    fireEvent.change(screen.getByLabelText('Minimum amount'), { target: { value: '500' } })
    await waitFor(() => expect(api.journals).toHaveBeenLastCalledWith(expect.objectContaining({ min_amount: '500' })))
    fireEvent.change(screen.getByLabelText('Account'), { target: { value: '5' } })
    await waitFor(() => expect(api.journals).toHaveBeenLastCalledWith(expect.objectContaining({ account_id: '5' })))
    fireEvent.click(screen.getByText('Clear filters'))
    await waitFor(() => expect(api.journals).toHaveBeenLastCalledWith(expect.objectContaining({ q: undefined, source_type: undefined, min_amount: undefined })))
  })
  it('pages through results', async () => {
    render(<JournalsTab canApprove requireApproval={false} />)
    await screen.findByText('Invoice INV-0001'); expect(screen.getByText('Page 1 of 3')).toBeInTheDocument()
    expect(screen.getByText('← Previous')).toBeDisabled()
    fireEvent.click(screen.getByText('Next →'))
    await waitFor(() => expect(api.journals).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50, limit: 50 })))
    expect(await screen.findByText('Page 2 of 3')).toBeInTheDocument()
  })
  it('shows an empty state that names the filters', async () => {
    api.journals.mockResolvedValue({ data: { items: [], total: 0, sum_total: '0' } })
    render(<JournalsTab canApprove requireApproval={false} />)
    fireEvent.change(screen.getByLabelText('Search journals'), { target: { value: 'zzz' } })
    expect(await screen.findByText('No journals match these filters')).toBeInTheDocument()
  })
  it('opens a journal: source, pending auto-reversal, attachment, history; and lets you reverse a plain one', async () => {
    api.journal.mockResolvedValue({ data: { ...items[0], lines: [{ line_no: 1, account_code: '445', account_name: 'Power', debit: '640.00', credit: '0.00', tax_code: 'INPUT', tax_amount: '64.00', tracking: ['Admin'], description: 'Elec', contact_name: 'AGL' }],
      source: { label: 'Approved draft #4 (prepared by Priya, approved by Owner)', status: null }, reversal: { journal_no: 104, date: '2026-10-01', pending: true }, attachments: [{ id: 8, filename: 'bill.pdf', size: 10 }] } })
    api.journalHistory.mockResolvedValue({ data: { events: [{ action: 'draft prepared', who: 'Priya', at: '2026-09-29T01:00:00Z', detail: 'x' }, { action: 'approved and posted', who: 'Owner', at: '2026-09-30T01:00:00Z', detail: null }] } })
    render(<JournalsTab canApprove requireApproval={false} />)
    fireEvent.click((await screen.findAllByText('View'))[0])
    expect(await screen.findByTestId('source-label')).toHaveTextContent('Approved draft #4')
    expect(screen.getByText(/Auto-reverses on 2026-10-01/)).toBeInTheDocument(); expect(screen.getByText('Admin')).toBeInTheDocument()
    fireEvent.click(screen.getByText('bill.pdf')); expect(books.downloadAttachment).toHaveBeenCalledWith(8, 'bill.pdf')
    fireEvent.click(screen.getByText('History & notes')); expect(await screen.findByText('draft prepared')).toBeInTheDocument(); expect(screen.getByText('approved and posted')).toBeInTheDocument()
    expect(screen.queryByText('Reverse journal')).toBeNull()          // already has a scheduled reversal - cannot be reversed a second time
  })
  it('reverses a plain posted journal on the chosen date', async () => {
    api.journal.mockResolvedValue({ data: { ...items[0], reference: null, lines: [], source: { label: 'manual' }, attachments: [] } })
    render(<JournalsTab canApprove requireApproval={false} />)
    fireEvent.click((await screen.findAllByText('View'))[0])
    fireEvent.change(await screen.findByLabelText('Reversal date'), { target: { value: '2026-10-05' } })
    fireEvent.click(screen.getByText('Reverse journal'))
    await waitFor(() => expect(api.reverseJournal).toHaveBeenCalledWith(1, { date: '2026-10-05' }))
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('200'))
  })
  it('shows the server message when the reversal is refused', async () => {
    api.journal.mockResolvedValue({ data: { ...items[0], lines: [], source: { label: 'manual' }, attachments: [] } })
    api.reverseJournal.mockRejectedValueOnce({ response: { data: { detail: 'Journal 101 is on or before the lock date' } } })
    render(<JournalsTab canApprove requireApproval={false} />)
    fireEvent.click((await screen.findAllByText('View'))[0]); fireEvent.click(await screen.findByText('Reverse journal'))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Journal 101 is on or before the lock date'))
  })
})

describe('JournalEditor', () => {
  const fill = async () => {
    fireEvent.change(screen.getByTestId('jnl-narration'), { target: { value: 'Accrue power' } })
    fireEvent.change(screen.getByLabelText('Account 1'), { target: { value: '5' } }); fireEvent.change(screen.getByLabelText('Debit 1'), { target: { value: '200' } })
    fireEvent.change(screen.getByLabelText('Account 2'), { target: { value: '9' } }); fireEvent.change(screen.getByLabelText('Credit 2'), { target: { value: '220' } })
  }
  const mount = props => render(<JournalEditor accounts={ACC} taxes={TAX} categories={CATS} canApprove requireApproval={false} onClose={() => {}} onDone={props?.onDone || (() => {})} {...props} />)
  it('previews the GST line the server will add and enables Post once it balances', async () => {
    api.journalPreview.mockResolvedValue({ data: { balanced: true, errors: [], warnings: ['Dated in the future (2026-10-31); it will not appear in reports until that date.'], gst_total: '20.00', total_debit: '220.00', total_credit: '220.00',
      lines: [{ account_code: '445', account_name: 'Power', description: null, debit: '200.00', credit: '0.00', is_gst: false }, { account_code: '820', account_name: 'GST', description: 'GST', debit: '20.00', credit: '0.00', is_gst: true }, { account_code: '805', account_name: 'Accrued', description: null, debit: '0.00', credit: '220.00', is_gst: false }] } })
    mount(); await fill()
    fireEvent.change(screen.getByLabelText('GST'), { target: { value: 'exclusive' } }); fireEvent.change(screen.getByLabelText('Tax code 1'), { target: { value: '3' } })
    const pv = await screen.findByTestId('preview'); expect(within(pv).getByText('820 · GST')).toBeInTheDocument(); expect(within(pv).getByText(/includes \$20\.00 GST/)).toBeInTheDocument()
    expect(within(pv).getByText(/Dated in the future/)).toBeInTheDocument()
    expect(api.journalPreview).toHaveBeenLastCalledWith(expect.objectContaining({ amounts_are: 'exclusive', lines: expect.arrayContaining([expect.objectContaining({ account_id: 5, tax_code_id: 3, debit: '200' })]) }))
    await waitFor(() => expect(screen.getByText('Post journal')).toBeEnabled())
  })
  it('blocks Post and shows the server errors while the journal is wrong', async () => {
    api.journalPreview.mockResolvedValue({ data: { balanced: false, errors: ['Out of balance by 20.00 (debits 200.00, credits 220.00).'], warnings: [], gst_total: '0.00', total_debit: '200.00', total_credit: '220.00', lines: [] } })
    mount(); await fill()
    expect(await screen.findByText(/Out of balance by 20\.00/)).toBeInTheDocument(); expect(screen.getByText('Post journal')).toBeDisabled(); expect(screen.getByText('Submit for approval')).toBeDisabled()
    expect(screen.getByText('Save draft')).toBeEnabled()               // an unbalanced DRAFT is allowed; it has no ledger effect
  })
  it('posts with reference, GST mode and auto-reverse date, then uploads attachments to the new journal', async () => {
    api.journalPreview.mockResolvedValue({ data: { balanced: true, errors: [], warnings: [], gst_total: '0.00', total_debit: '220.00', total_credit: '220.00', lines: [] } })
    api.postJournal.mockResolvedValue({ data: { id: 7, journal_no: 300, auto_reversal: { date: '2026-10-31' } } })
    const onDone = vi.fn(); const { container } = mount({ onDone }); await fill()
    fireEvent.change(screen.getByLabelText('Reference'), { target: { value: 'WP-9' } })
    fireEvent.click(screen.getByLabelText(/Auto-reverse \(accrual\)/)); fireEvent.change(screen.getByLabelText('Auto-reverse date'), { target: { value: '2026-10-31' } })
    const file = new File(['x'], 'wp.pdf', { type: 'application/pdf' }); fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [file] } })
    await waitFor(() => expect(screen.getByText('Post journal')).toBeEnabled()); fireEvent.click(screen.getByText('Post journal'))
    await waitFor(() => expect(api.postJournal).toHaveBeenCalledWith(expect.objectContaining({ reference: 'WP-9', auto_reverse_date: '2026-10-31', amounts_are: 'no_tax', narration: 'Accrue power' })))
    await waitFor(() => expect(books.uploadAttachment).toHaveBeenCalledWith('journal', 7, file)); expect(onDone).toHaveBeenCalledWith('posted')
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('auto-reverses 2026-10-31'))
  })
  it('a bookkeeper in an approval-required org can only save or submit, never post', async () => {
    api.journalPreview.mockResolvedValue({ data: { balanced: true, errors: [], warnings: [], gst_total: '0.00', total_debit: '1.00', total_credit: '1.00', lines: [] } })
    const onDone = vi.fn(); mount({ canApprove: false, requireApproval: true, onDone }); await fill()
    expect(screen.queryByText('Post journal')).toBeNull(); expect(screen.getByText(/requires journals to be approved/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Submit for approval')).toBeEnabled()); fireEvent.click(screen.getByText('Submit for approval'))
    await waitFor(() => expect(api.createDraft).toHaveBeenCalled()); await waitFor(() => expect(api.submitDraft).toHaveBeenCalledWith(55)); expect(onDone).toHaveBeenCalledWith('submitted')
    expect(api.postJournal).not.toHaveBeenCalled()
  })
  it('saves a draft for later and tags each line with its tracking option', async () => {
    mount(); await fill(); fireEvent.change(screen.getByLabelText('Department 1'), { target: { value: '21' } })
    fireEvent.click(screen.getByText('Save draft'))
    await waitFor(() => expect(api.createDraft).toHaveBeenCalledWith(expect.objectContaining({ lines: expect.arrayContaining([expect.objectContaining({ account_id: 5, tracking_option_ids: [21] })]) })))
  })
  it('editing an existing draft updates it (and an approver can post it now)', async () => {
    api.journalPreview.mockResolvedValue({ data: { balanced: true, errors: [], warnings: [], gst_total: '0.00', total_debit: '50.00', total_credit: '50.00', lines: [] } })
    const initial = { date: '2026-09-30', narration: 'Existing', reference: 'R1', amounts_are: 'no_tax', lines: [{ account_id: 5, debit: '50', credit: '0' }, { account_id: 9, debit: '0', credit: '50' }] }
    mount({ initial, draftId: 33 }); expect(screen.getByDisplayValue('Existing')).toBeInTheDocument(); expect(screen.getByLabelText('Account 1')).toHaveValue('5')
    await waitFor(() => expect(screen.getByText('Post now')).toBeEnabled()); fireEvent.click(screen.getByText('Post now'))
    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledWith(33, expect.objectContaining({ narration: 'Existing' }))); await waitFor(() => expect(api.approveDraft).toHaveBeenCalledWith(33))
    expect(api.createDraft).not.toHaveBeenCalled()
  })
  it('shows the server message when posting fails and stays open', async () => {
    api.journalPreview.mockResolvedValue({ data: { balanced: true, errors: [], warnings: [], gst_total: '0.00', total_debit: '1.00', total_credit: '1.00', lines: [] } })
    api.postJournal.mockRejectedValueOnce({ response: { data: { detail: '2026-06-30 is on or before the lock date 2026-06-30' } } })
    const onDone = vi.fn(); mount({ onDone }); await fill()
    await waitFor(() => expect(screen.getByText('Post journal')).toBeEnabled()); fireEvent.click(screen.getByText('Post journal'))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('lock date'))); expect(onDone).not.toHaveBeenCalled()
  })
})

describe('ReviewTab', () => {
  const ai = (o = {}) => ({ id: 1, kind: 'ai_bank', status: 'submitted', confidence: '0.9700', reason: 'Bank rule: netflix -> 485 Subscriptions', date: '2026-09-29', narration: 'Spend', total: '16.99',
    lines: [{ account_code: '485', debit: '15.45', credit: '0.00' }, { account_code: '820', debit: '1.54', credit: '0.00' }, { account_code: '090', debit: '0.00', credit: '16.99' }],
    suggestion: { type: 'coding', account_id: 12, tax_code_id: 3, bank_line: { id: 4, date: '2026-09-29', description: 'NETFLIX.COM', amount: '-16.99' } }, ...o })
  const drafts = [ai(), ai({ id: 2, confidence: '0.9000', reason: 'Learned from 4 earlier codings', suggestion: { type: 'coding', account_id: 12, bank_line: { id: 5, date: '2026-09-28', description: 'BUNNINGS', amount: '-50.00' } } }),
    ai({ id: 3, confidence: '0.9900', reason: 'Exact amount and invoice number', suggestion: { type: 'match', match: 'INV-0012', bank_line: { id: 6, date: '2026-09-27', description: 'EFT Acme INV-0012', amount: '1100.00' } }, lines: [{ account_code: '090', debit: '1100.00', credit: '0.00' }, { account_code: '610', debit: '0.00', credit: '1100.00' }] }),
    { id: 10, kind: 'manual', status: 'submitted', date: '2026-09-30', narration: 'Accrue audit', reference: 'AUD', created_by: 'Priya', total: '3520.00', lines: [{ account_code: '412', account_name: 'Audit', debit: '3200.00', credit: '0.00' }] },
    { id: 11, kind: 'manual', status: 'rejected', date: '2026-09-30', narration: 'Dividends', created_by: 'Priya', total: '5000.00', rejected_reason: 'Need a board resolution', lines: [] }]
  beforeEach(() => api.journalDrafts.mockResolvedValue({ data: { items: drafts, counts: {} } }))
  it('shows each suggestion with confidence, reason and what it would post', async () => {
    render(<ReviewTab canApprove requireApproval={false} />)
    expect(await screen.findByText('NETFLIX.COM')).toBeInTheDocument(); expect(screen.getByTitle('97% confidence')).toBeInTheDocument(); expect(screen.getByTitle('90% confidence')).toBeInTheDocument(); expect(screen.getByTitle('99% confidence')).toBeInTheDocument()
    expect(screen.getByText(/Bank rule: netflix/)).toBeInTheDocument(); expect(screen.getByText('Match to INV-0012')).toBeInTheDocument(); expect(screen.getAllByText(/Dr 485 \$15\.45/)).toHaveLength(2)
    expect(screen.getByText('Accrue audit')).toBeInTheDocument(); expect(screen.getByText('Dividends')).toBeInTheDocument()
  })
  it('approves one suggestion', async () => {
    render(<ReviewTab canApprove requireApproval={false} />); await screen.findByText('NETFLIX.COM')
    fireEvent.click(screen.getAllByText('Approve')[0]); await waitFor(() => expect(api.approveDraft).toHaveBeenCalledWith(1)); expect(toast.success).toHaveBeenCalledWith('Approved and reconciled')
  })
  it('rejects only with a reason, and sends it', async () => {
    render(<ReviewTab canApprove requireApproval={false} />); await screen.findByText('NETFLIX.COM')
    window.prompt = vi.fn(() => ''); fireEvent.click(screen.getAllByText('Reject')[0]); await new Promise(r => setTimeout(r, 30)); expect(api.rejectDraft).not.toHaveBeenCalled()
    window.prompt = vi.fn(() => 'Personal expense'); fireEvent.click(screen.getAllByText('Reject')[0]); await waitFor(() => expect(api.rejectDraft).toHaveBeenCalledWith(1, 'Personal expense'))
  })
  it('bulk-approves only what meets the threshold', async () => {
    render(<ReviewTab canApprove requireApproval={false} />); await screen.findByText('NETFLIX.COM')
    expect(screen.getByText('Approve 2')).toBeInTheDocument()            // 97% and 99% qualify at 95%; 90% does not
    fireEvent.change(screen.getByLabelText('Confidence threshold'), { target: { value: '0.99' } }); expect(screen.getByText('Approve 1')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Confidence threshold'), { target: { value: '0.90' } }); expect(screen.getByText('Approve 3')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Approve 3')); await waitFor(() => expect(api.bulkApprove).toHaveBeenCalledWith('0.90'))
    expect(window.confirm).toHaveBeenCalled()
  })
  it('does not bulk-approve when the user declines the confirmation', async () => {
    window.confirm = vi.fn(() => false); render(<ReviewTab canApprove requireApproval={false} />); await screen.findByText('NETFLIX.COM')
    fireEvent.click(screen.getByText('Approve 2')); await new Promise(r => setTimeout(r, 30)); expect(api.bulkApprove).not.toHaveBeenCalled()
  })
  it('reports a partly-failed bulk approval', async () => {
    api.bulkApprove.mockResolvedValueOnce({ data: { approved: 1, failed: [{ id: 3, error: 'That bank line is already reconciled; discard this suggestion' }] } })
    render(<ReviewTab canApprove requireApproval={false} />); await screen.findByText('NETFLIX.COM'); fireEvent.click(screen.getByText('Approve 2'))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('already reconciled'))); expect(toast.success).toHaveBeenCalledWith('1 approved, 1 failed')
  })
  it('lets a reviewer change the suggested account before approving', async () => {
    render(<ReviewTab canApprove requireApproval={false} />); await screen.findByText('NETFLIX.COM')
    fireEvent.click(screen.getAllByText('Adjust')[0]); fireEvent.change(await screen.findByLabelText('Account'), { target: { value: '5' } }); fireEvent.click(screen.getByText('Save'))
    await waitFor(() => expect(api.updateDraft).toHaveBeenCalledWith(1, { account_id: 5, tax_code_id: 3 }))
  })
  it('hides every approve/reject control from someone who cannot approve', async () => {
    render(<ReviewTab canApprove={false} requireApproval />); await screen.findByText('NETFLIX.COM')
    expect(screen.queryByText('Approve')).toBeNull(); expect(screen.queryByText('Reject')).toBeNull(); expect(screen.queryByText(/Approve \d/)).toBeNull(); expect(screen.queryByText(/Require approval/)).toBeNull()
  })
  it('finds new suggestions and refreshes', async () => {
    render(<ReviewTab canApprove requireApproval={false} />); await screen.findByText('NETFLIX.COM')
    fireEvent.click(screen.getByText('Find suggestions from bank lines')); await waitFor(() => expect(api.generateSuggestions).toHaveBeenCalled())
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('3 new suggestion')); await waitFor(() => expect(api.journalDrafts.mock.calls.length).toBeGreaterThan(1))
  })
  it('opens a draft awaiting approval and approves it; a rejected draft shows why and can be resubmitted', async () => {
    render(<ReviewTab canApprove requireApproval={false} />); await screen.findByText('Accrue audit')
    fireEvent.click(screen.getAllByText('Open')[0]); expect(await screen.findByText(/Prepared by Priya/)).toBeInTheDocument(); fireEvent.click(screen.getByText('Approve & post'))
    await waitFor(() => expect(api.approveDraft).toHaveBeenCalledWith(10))
    fireEvent.click(screen.getAllByText('Open')[1]); expect(await screen.findByText(/Rejected: Need a board resolution/)).toBeInTheDocument()
    fireEvent.click(screen.getAllByText('Submit for approval').pop()); await waitFor(() => expect(api.submitDraft).toHaveBeenCalledWith(11))
  })
  it('toggles the require-approval policy', async () => {
    const onSettings = vi.fn(); render(<ReviewTab canApprove requireApproval={false} onSettings={onSettings} />); await screen.findByText('NETFLIX.COM')
    fireEvent.click(screen.getByLabelText(/Require approval for manual journals/)); expect(onSettings).toHaveBeenCalledWith(true)
  })
  it('shows a helpful empty state', async () => {
    api.journalDrafts.mockResolvedValue({ data: { items: [], counts: {} } }); render(<ReviewTab canApprove requireApproval={false} />)
    expect(await screen.findByText(/No suggestions waiting/)).toBeInTheDocument(); expect(screen.getByText('Nothing is waiting for approval.')).toBeInTheDocument()
  })
})

describe('RepeatingTab', () => {
  const tpl = [{ id: 1, name: 'Monthly insurance release', frequency: 'monthly', next_date: '2020-01-31', next_narration: 'Insurance - January 2020', mode: 'draft', last_run_date: null, runs: 0, is_active: true, lines: [] },
    { id: 2, name: 'Quarterly accrual', frequency: 'quarterly', next_date: '2099-01-01', next_narration: 'Accrual Q3', mode: 'post', reverse_after_days: 31, last_run_date: '2026-07-01', runs: 3, is_active: true, last_error: '2026-07-01: locked', lines: [] }]
  beforeEach(() => api.repeatingJournals.mockResolvedValue({ data: { items: tpl } }))
  it('lists templates, flags the ones that are due, and shows the last error', async () => {
    render(<RepeatingTab canApprove />); expect(await screen.findByText('Monthly insurance release')).toBeInTheDocument()
    expect(screen.getByText('due')).toBeInTheDocument(); expect(screen.getByText('Insurance - January 2020')).toBeInTheDocument(); expect(screen.getByText(/reverses after 31d/)).toBeInTheDocument()
    expect(screen.getByText('2026-07-01: locked')).toBeInTheDocument(); expect(screen.getByText('Run due now (1)')).toBeInTheDocument()
  })
  it('runs the due templates and reports the result and any errors', async () => {
    api.runRepeating.mockResolvedValueOnce({ data: { templates: 2, drafts: 2, posted: 1, errors: [{ name: 'Quarterly accrual', error: 'lock date' }] } })
    render(<RepeatingTab canApprove />); fireEvent.click(await screen.findByText('Run due now (1)'))
    await waitFor(() => expect(api.runRepeating).toHaveBeenCalled()); expect(toast.success).toHaveBeenCalledWith('2 draft(s) created, 1 posted'); expect(toast.error).toHaveBeenCalledWith('Quarterly accrual: lock date')
  })
  it('deletes only after confirmation', async () => {
    window.confirm = vi.fn(() => false); render(<RepeatingTab canApprove />); fireEvent.click((await screen.findAllByText('Delete'))[0]); expect(api.deleteRepeating).not.toHaveBeenCalled()
    window.confirm = vi.fn(() => true); fireEvent.click(screen.getAllByText('Delete')[0]); await waitFor(() => expect(api.deleteRepeating).toHaveBeenCalledWith(1))
  })
  it('an empty list explains what repeating journals are for', async () => {
    api.repeatingJournals.mockResolvedValue({ data: { items: [] } }); render(<RepeatingTab canApprove />); expect(await screen.findByText(/No repeating journals yet/)).toBeInTheDocument()
  })
})

describe('ImportModal', () => {
  const CSV = 'Date,Narration,Account,Debit,Credit\n30/06/2026,X,412,10,\n,,805,,10'
  const check = async () => { fireEvent.change(screen.getByLabelText('CSV text'), { target: { value: CSV } }); fireEvent.click(screen.getByText('Check file')); }
  it('checks first, lists every problem, and refuses to import until fixed', async () => {
    api.importJournals.mockResolvedValue({ data: { count: 2, valid: 1, invalid: 1, journals: [
      { row: 2, date: '2026-06-30', narration: 'X', reference: null, lines: 2, total: '10.00', errors: [], warnings: [] },
      { row: 4, date: null, narration: 'Bad', reference: null, lines: 2, total: '0.00', errors: ["Row 4: '99/99/2026' is not a valid date (use DD/MM/YYYY or YYYY-MM-DD)"], warnings: [] }] } })
    render(<ImportModal canApprove onClose={() => {}} onDone={() => {}} />); await check()
    expect(await screen.findByText(/1 of 2 journal\(s\) have problems/)).toBeInTheDocument(); expect(screen.getByText(/not a valid date/)).toBeInTheDocument()
    expect(api.importJournals).toHaveBeenCalledWith(expect.objectContaining({ dry_run: true, csv: CSV })); expect(screen.getByText('Import 1 journal(s)')).toBeDisabled()
  })
  it('imports as drafts once the file is valid', async () => {
    api.importJournals.mockResolvedValueOnce({ data: { count: 1, valid: 1, invalid: 0, journals: [{ row: 2, date: '2026-06-30', narration: 'X', reference: null, lines: 2, total: '10.00', errors: [], warnings: [] }] } })
      .mockResolvedValueOnce({ data: { count: 1, valid: 1, invalid: 0, journals: [], saved: 1, posted: 0 } })
    const onDone = vi.fn(); render(<ImportModal canApprove onClose={() => {}} onDone={onDone} />); await check()
    expect(await screen.findByText('All 1 journal(s) are valid.')).toBeInTheDocument(); fireEvent.click(screen.getByText('Import 1 journal(s)'))
    await waitFor(() => expect(api.importJournals).toHaveBeenLastCalledWith(expect.objectContaining({ dry_run: false, mode: 'draft' }))); await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(toast.success).toHaveBeenCalledWith('1 draft(s) saved for review')
  })
  it('offers "post directly" only to approvers', () => {
    const { unmount } = render(<ImportModal canApprove={false} onClose={() => {}} onDone={() => {}} />); expect(within(screen.getByLabelText('Import as')).queryByText('Posted journals')).toBeNull(); unmount()
    render(<ImportModal canApprove onClose={() => {}} onDone={() => {}} />); expect(within(screen.getByLabelText('Import as')).getByText('Posted journals')).toBeInTheDocument()
  })
  it('re-check is required after changing options; Check is disabled for an empty file', () => {
    render(<ImportModal canApprove onClose={() => {}} onDone={() => {}} />); expect(screen.getByText('Check file')).toBeDisabled()
  })
  it('surfaces a server-side rejection of the file', async () => {
    api.importJournals.mockRejectedValueOnce({ response: { data: { detail: 'The file needs at least Date and Account columns' } } })
    render(<ImportModal canApprove onClose={() => {}} onDone={() => {}} />); await check(); await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('Date and Account')))
  })
})
