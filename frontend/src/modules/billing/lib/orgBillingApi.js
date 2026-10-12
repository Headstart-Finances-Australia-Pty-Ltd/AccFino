// Billing: organisation card, subscribe, auto-renew, platform billing admin
import { http } from '../../../core/lib/platformHttp.js'

export const getBilling          = ()              => http.get('/org/current/billing', { params: { _t: Date.now() } })

export const saveBillingCard     = (source_id)     => http.post('/org/current/billing/card', { source_id })

export const deleteBillingCard   = ()              => http.delete('/org/current/billing/card')

export const billingSubscribe    = (billing_period) => http.post('/org/current/billing/subscribe', { billing_period })

export const billingAutoRenew    = (enabled)       => http.post('/org/current/billing/auto-renew', { enabled })

export const adminSquareStatus   = ()              => http.get('/admin/billing/square')

export const adminSaveSquare     = (body)          => http.put('/admin/billing/square', body)

export const adminTestSquare     = ()              => http.post('/admin/billing/square/test')

export const adminBillingOverview = ()             => http.get('/admin/billing/overview', { params: { _t: Date.now() } })

export const adminRunBilling     = ()              => http.post('/admin/billing/run')
