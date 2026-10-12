import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { sameAccountNumber } from '../../../core/lib/accountMatch.js'

vi.mock('react-hot-toast', () => ({ default: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }))
vi.mock('../../../core/hooks/useOrgRole.jsx', () => ({ default: () => ({ isOrgAdmin: true }) }))
vi.mock('../../../core/lib/api.js', async () => ({ ...(await vi.importActual('../../../core/lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn() }))
vi.mock('../../accounting/lib/api.js', async () => ({ ...(await vi.importActual('../../accounting/lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn() }))
vi.mock('../../billing/lib/api.js', async () => ({ ...(await vi.importActual('../../billing/lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn() }))
vi.mock('../../cashflow/lib/api.js', async () => ({ ...(await vi.importActual('../../cashflow/lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn() }))
vi.mock('../../open_banking/lib/api.js', async () => ({ ...(await vi.importActual('../../open_banking/lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn() }))
vi.mock('../lib/api.js', async () => ({ ...(await vi.importActual('../lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn() }))
vi.mock('../../trading/lib/api.js', async () => ({ ...(await vi.importActual('../../trading/lib/api.js')), obReconcileAccounts: vi.fn(), obPull: vi.fn() }))
import * as api from '../../open_banking/lib/api.js'
import OpenBankingInput from '../components/OpenBankingInput.jsx'

const ACCTS = [{ key: 'openfeed:a1', provider: 'openfeed', bank: 'ANZ', name: 'ANZ One Offset Account', number: 'xxxxxx xxxxx1912' },
               { key: 'basiq:b1', provider: 'basiq', bank: 'NAB', name: 'NAB Cheque', number: '000123456789' }]
beforeEach(() => { vi.clearAllMocks(); api.obReconcileAccounts.mockResolvedValue({ data: { accounts: ACCTS } }) })

describe('Reconciliation > Open Banking input', () => {
  it('OpenFeed accounts are selectable (no "soon") and counted with the Basiq ones', async () => {
    render(<MemoryRouter><OpenBankingInput onPulled={vi.fn()} /></MemoryRouter>)
    expect(await screen.findByText(/0 of 2 selected/)).toBeInTheDocument()
    expect(screen.queryByText(/soon/i)).toBeNull()
    const boxes = screen.getAllByRole('checkbox')
    expect(boxes.every(b => !b.disabled)).toBe(true)
    expect(screen.getByText('OpenFeed')).toBeInTheDocument(); expect(screen.getByText('Basiq')).toBeInTheDocument()
    fireEvent.click(boxes[0]); expect(screen.getByText(/1 of 2 selected/)).toBeInTheDocument()
  })

  it('pulls an OpenFeed account through the server and hands the rows on for merging', async () => {
    const onPulled = vi.fn()
    api.obPull.mockResolvedValue({ data: { rows: [{ date: '10/09/2026', description: 'x', debit: 5, credit: 0, bank: 'ANZ', account: 'xxxxxx xxxxx1912' }], count: 1, bank: 'ANZ', account: 'xxxxxx xxxxx1912', account_name: 'ANZ One Offset Account' } })
    render(<MemoryRouter><OpenBankingInput onPulled={onPulled} /></MemoryRouter>)
    fireEvent.click((await screen.findAllByRole('checkbox'))[0])
    fireEvent.click(screen.getByRole('button', { name: /Pull account/ }))
    await waitFor(() => expect(api.obPull).toHaveBeenCalledWith(expect.objectContaining({ account_key: 'openfeed:a1' })))
    await waitFor(() => expect(onPulled).toHaveBeenCalledWith(expect.any(Array), expect.objectContaining({ bank: 'ANZ', number: 'xxxxxx xxxxx1912' })))
  })
})

describe('matching a masked bank-feed number to the statement account', () => {
  it('equal digits, or the masked last digits against the full number', () => {
    expect(sameAccountNumber('06-2000 1234 5678', '062000 12345678')).toBe(true)
    expect(sameAccountNumber('012345671912', 'xxxxxx xxxxx1912')).toBe(true)
    expect(sameAccountNumber('xxxxxx xxxxx1912', '012345671912')).toBe(true)
  })
  it('different accounts, too-short tails and empty values never match', () => {
    expect(sameAccountNumber('012345671912', 'xxxxxx xxxxx1913')).toBe(false)
    expect(sameAccountNumber('012345671912', '912')).toBe(false)                   // fewer than 4 digits proves nothing
    expect(sameAccountNumber('', '1912')).toBe(false); expect(sameAccountNumber(null, undefined)).toBe(false)
  })
})
