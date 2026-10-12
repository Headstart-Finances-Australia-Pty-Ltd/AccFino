import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
vi.mock('../../../core/lib/adminApi.js', async () => { const { booksApiMockFactory } = await import('../../../core/test/testUtils.js'); return { ...(await booksApiMockFactory()), codeLine: vi.fn(), transferLine: vi.fn(), excludeLine: vi.fn(), matchLine: vi.fn() } })
vi.mock('../lib/booksApi.js', async () => { const { booksApiMockFactory } = await import('../../../core/test/testUtils.js'); return { ...(await booksApiMockFactory()), codeLine: vi.fn(), transferLine: vi.fn(), excludeLine: vi.fn(), matchLine: vi.fn() } })
vi.mock('../../billing/lib/orgBillingApi.js', async () => { const { booksApiMockFactory } = await import('../../../core/test/testUtils.js'); return { ...(await booksApiMockFactory()), codeLine: vi.fn(), transferLine: vi.fn(), excludeLine: vi.fn(), matchLine: vi.fn() } })
vi.mock('../../open_banking/lib/feedApi.js', async () => { const { booksApiMockFactory } = await import('../../../core/test/testUtils.js'); return { ...(await booksApiMockFactory()), codeLine: vi.fn(), transferLine: vi.fn(), excludeLine: vi.fn(), matchLine: vi.fn() } })
vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
import BankingPage from '../pages/BankingPage.jsx'
import * as api from '../lib/booksApi.js'
import toast from 'react-hot-toast'
import { fmtMoney, fmtAUD } from '../../../core/components/ui/Common.jsx'

const norm = s => s.replace(/\s/g, ' ')
const USD = { id: 2, code: 'USD-OPS', name: 'USD Operating', currency: 'USD', foreign: true, ledger_balance: '10890.00', base_value: '16698.00', unreconciled: 1, last_statement_date: null }
const AUD = { id: 1, code: '090', name: 'Everyday', currency: 'AUD', foreign: false, ledger_balance: '5000.00', base_value: '5000.00', unreconciled: 0, last_statement_date: null }
const LINE = { id: 9, date: '2026-10-05', description: 'Sold USD', amount: '-1000.00', status: 'unreconciled', coding: null, suggestion: null }
beforeEach(() => { vi.clearAllMocks()
  api.bankAccounts.mockResolvedValue({ data: { items: [AUD, USD] } }); api.listBankLines.mockResolvedValue({ data: { items: [LINE] } })
  api.ledgerAccounts.mockResolvedValue({ data: [{ id: 5, code: '445', name: 'Power', type: 'expense' }] }); api.taxCodes.mockResolvedValue({ data: [] })
  api.codeLine.mockResolvedValue({ data: { realised_fx: '66.67' } }); api.transferLine.mockResolvedValue({ data: { realised_fx: '-33.33' } }) })
const openUsd = async () => { render(<BankingPage />); fireEvent.click(await screen.findByText(/USD-OPS USD Operating/)); await screen.findByText('Sold USD') }

describe('foreign-currency bank accounts', () => {
  it('shows the currency badge, the balance in that currency and the dollar value at cost', async () => {
    render(<BankingPage />); await screen.findByText(/USD-OPS USD Operating/)
    expect(norm(screen.getByText(/USD-OPS USD Operating/).parentElement.textContent)).toContain(norm(fmtMoney('10890.00', 'USD'))); expect(screen.getByTestId('base-value')).toHaveTextContent(norm(fmtAUD('16698.00')).replace('$', '$'))
    expect(screen.getAllByText('USD').length).toBeGreaterThan(0)
  })
  it('statement lines are shown in the account currency', async () => {
    await openUsd(); expect(norm(document.body.textContent)).toContain(norm(fmtMoney('-1000.00', 'USD')))
  })
  it('explains how the line will be booked and offers an optional exchange rate', async () => {
    await openUsd(); fireEvent.click(screen.getByText('Code…')); expect(await screen.findByTestId('fx-line-note')).toHaveTextContent('held in USD'); expect(screen.getByTestId('fx-line-note')).toHaveTextContent('average cost'); expect(screen.getByLabelText('Exchange rate')).toBeInTheDocument()
  })
  it('sends the typed rate when coding, and reports the realised gain', async () => {
    await openUsd(); fireEvent.click(screen.getByText('Code…')); await screen.findByTestId('fx-line-note')
    fireEvent.change(screen.getByDisplayValue('Choose…'), { target: { value: '445' } }); fireEvent.change(screen.getByLabelText('Exchange rate'), { target: { value: '1.6' } }); fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.codeLine).toHaveBeenCalledWith(9, expect.objectContaining({ rate: '1.6' }))); await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining('Realised foreign exchange gain')))
  })
  it('a base-currency account shows no foreign-currency note or rate field', async () => {
    render(<BankingPage />); fireEvent.click(await screen.findByText(/090 Everyday/)); await screen.findByText('Sold USD'); fireEvent.click(screen.getByText('Code…')); await screen.findByText(/Code to an account/)
    expect(screen.queryByTestId('fx-line-note')).toBeNull(); expect(screen.queryByLabelText('Exchange rate')).toBeNull()
  })
  it('a conversion needs the amount that arrived, so the exchange rate is the real one', async () => {
    await openUsd(); fireEvent.click(screen.getByText('Code…')); fireEvent.click(await screen.findByText('Transfer between accounts'))
    fireEvent.change(screen.getByDisplayValue('Choose…'), { target: { value: '090' } }); const save = screen.getByRole('button', { name: 'Save' })
    const amt = await screen.findByLabelText(/Amount received in 090|Amount sent from 090/); expect(save).toBeDisabled()
    fireEvent.change(amt, { target: { value: '1500' } }); expect(save).not.toBeDisabled(); fireEvent.click(save)
    await waitFor(() => expect(api.transferLine).toHaveBeenCalledWith(9, expect.objectContaining({ to_account: '090', other_amount: '1500' }))); await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining('Realised foreign exchange loss: ')))
  })
  it('a transfer between accounts of the same currency needs no extra amount', async () => {
    api.bankAccounts.mockResolvedValue({ data: { items: [USD, { ...USD, id: 3, code: 'USD-2', name: 'USD Two' }] } }); await openUsd(); fireEvent.click(screen.getByText('Code…')); fireEvent.click(await screen.findByText('Transfer between accounts'))
    fireEvent.change(screen.getByDisplayValue('Choose…'), { target: { value: 'USD-2' } }); expect(screen.queryByLabelText(/Amount (received in|sent from)/)).toBeNull(); expect(screen.getByRole('button', { name: 'Save' })).not.toBeDisabled()
  })
  it('shows a refusal from the server (e.g. USD to EUR must go through AUD)', async () => {
    api.transferLine.mockRejectedValueOnce({ response: { data: { detail: 'USD to EUR cannot be transferred directly. Convert to AUD first' } } }); api.bankAccounts.mockResolvedValue({ data: { items: [USD, { ...USD, id: 3, code: 'EUR-1', currency: 'EUR' }] } })
    await openUsd(); fireEvent.click(screen.getByText('Code…')); fireEvent.click(await screen.findByText('Transfer between accounts')); fireEvent.change(screen.getByDisplayValue('Choose…'), { target: { value: 'EUR-1' } })
    fireEvent.change(await screen.findByLabelText(/Amount/), { target: { value: '90' } }); fireEvent.click(screen.getByRole('button', { name: 'Save' })); await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('Convert to AUD first')))
  })
})
