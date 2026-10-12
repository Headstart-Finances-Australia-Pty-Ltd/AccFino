import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }))
const H = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../../lib/platformHttp.js', () => ({ http: H, errMsg: e => e?.message || 'error' }))
import { BulkLoadButton } from '../BulkLoadButton.jsx'

const CAT = { items: [
  { key: 'clients', label: 'Clients', area: 'Clients', allowed: true, notes: '', columns: [{ name: 'legal_name', required: true, help: '', example: 'X' }] },
  { key: 'rates', label: 'Rates', area: 'Billing', allowed: true, notes: '', columns: [] },
] }
const csv = () => new File(['legal_name\nX\n'], 'c.csv', { type: 'text/csv' })

beforeEach(() => {
  vi.clearAllMocks()
  H.get.mockImplementation(url => url.endsWith('/status') ? Promise.resolve({ data: { enabled: true } }) : Promise.resolve({ data: CAT }))
})

describe('BulkLoadButton', () => {
  it('is hidden when the platform has switched bulk import off', async () => {
    H.get.mockImplementation(() => Promise.resolve({ data: { enabled: false } }))
    render(<BulkLoadButton base="/practice/bulk" />)
    await waitFor(() => expect(H.get).toHaveBeenCalled())
    expect(screen.queryByText(/Bulk load/)).toBeNull()
  })

  it('offers only the tables of its own area', async () => {
    render(<BulkLoadButton base="/practice/bulk" areas={['Clients']} />)
    fireEvent.click(await screen.findByText(/Bulk load/))
    const sel = await screen.findByLabelText('Table to load')
    expect([...sel.options].map(o => o.value)).toEqual(['clients'])
  })

  it('checks first (apply=false), only then allows the load, and sends apply=true', async () => {
    H.post.mockResolvedValueOnce({ data: { dry_run: true, applied: 0, valid_rows: 1, rejected: [], ignored_columns: [] } })
      .mockResolvedValueOnce({ data: { dry_run: false, applied: 1, valid_rows: 1, rejected: [], ignored_columns: [] } })
    render(<BulkLoadButton base="/practice/bulk" areas={['Clients']} />)
    fireEvent.click(await screen.findByText(/Bulk load/))
    const file = await screen.findByLabelText('CSV file')
    expect(screen.getByText('Load')).toBeDisabled()
    fireEvent.change(file, { target: { files: [csv()] } })
    expect(screen.getByText('Load')).toBeDisabled()                       // not checked yet
    fireEvent.click(screen.getByText('Check file'))
    await screen.findByText(/nothing saved/i)
    expect(H.post.mock.calls[0][1].get('apply')).toBe('false')
    fireEvent.click(screen.getByText('Load'))
    await screen.findByText(/1 row\(s\) loaded/)
    expect(H.post.mock.calls[1][0]).toBe('/practice/bulk/clients')
    expect(H.post.mock.calls[1][1].get('apply')).toBe('true')
  })

  it('shows row problems and blocks an all-or-nothing load while any row is bad', async () => {
    H.post.mockResolvedValueOnce({ data: { dry_run: true, applied: 0, valid_rows: 1, rejected: [{ row: 3, error: 'Legal name is required' }], ignored_columns: [] } })
    render(<BulkLoadButton base="/practice/bulk" areas={['Clients']} />)
    fireEvent.click(await screen.findByText(/Bulk load/))
    fireEvent.change(await screen.findByLabelText('CSV file'), { target: { files: [csv()] } })
    fireEvent.click(screen.getByText('Check file'))
    await screen.findByText('Legal name is required')
    expect(screen.getByText('Load')).toBeDisabled()
  })
})
