import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../../../lib/booksApi.js', async () => {
  const actual = await vi.importActual('../../../lib/booksApi.js')
  return { ...actual, adminAddressCheck: vi.fn() }
})
import * as api from '../../../lib/booksApi.js'
import TenantAddressCheck from '../../../components/tenancy/TenantAddressCheck.jsx'

const STEP = (key, ok, detail, fix) => ({ key, ok, detail, ...(ok ? {} : { fix }) })
beforeEach(() => vi.clearAllMocks())

describe('Admin > API Keys > Web Addresses', () => {
  it('shows which step is missing and what to do about it', async () => {
    api.adminAddressCheck.mockResolvedValue({ data: { ok: false, base_domain: 'accfino.com', example: 'https://your-organisation.accfino.com', steps: [
      STEP('setting', true, 'TENANT_BASE_DOMAIN = accfino.com'),
      STEP('dns', false, 'check-ab12.accfino.com does not resolve - there is no wildcard record *.accfino.com.', 'Add a wildcard DNS record *.accfino.com (a CNAME to your host\'s address, DNS-only if you use Cloudflare).')] } })
    render(<TenantAddressCheck />)
    expect(screen.queryByTestId('address-check-result')).toBeNull()                              // nothing runs until asked
    fireEvent.click(screen.getByTestId('address-check-run'))
    expect(await screen.findByTestId('fix-dns')).toHaveTextContent('wildcard DNS record *.accfino.com')
    expect(screen.getByTestId('step-setting')).toBeInTheDocument(); expect(screen.queryByTestId('fix-setting')).toBeNull()
    expect(screen.queryByTestId('address-check-ok')).toBeNull()
  })

  it('says everything is in place and shows what an organisation address looks like', async () => {
    api.adminAddressCheck.mockResolvedValue({ data: { ok: true, example: 'https://your-organisation.accfino.com', steps: ['setting', 'dns', 'https', 'routing'].map(k => STEP(k, true, 'ok')) } })
    render(<TenantAddressCheck />)
    fireEvent.click(screen.getByTestId('address-check-run'))
    expect(await screen.findByTestId('address-check-ok')).toHaveTextContent('https://your-organisation.accfino.com')
  })

  it('shows a plain error if the check itself cannot run', async () => {
    api.adminAddressCheck.mockRejectedValue({ response: { data: { detail: 'Administrators only' } } })
    render(<TenantAddressCheck />)
    fireEvent.click(screen.getByTestId('address-check-run'))
    await waitFor(() => expect(screen.getByText(/Administrators only/)).toBeInTheDocument())
  })
})
