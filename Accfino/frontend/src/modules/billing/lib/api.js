// billing module API client
import http from '../../../core/lib/http.js'

export const createCheckout = (body) => http.post('/payments/create-checkout', body)

export const adminActivate  = (body) => http.post('/payments/admin/activate', body)

export const activateAfterPayment = (body) => http.post('/payments/activate-after-payment', body)

export const squareStatus     = ()          => http.get('/square/status')

export const squareSaveConfig = (data)      => http.post('/square/config', data)

export const stripeStatus     = ()          => http.get('/stripe/status')

export const stripeSaveConfig = (data)      => http.post('/stripe/config', data)

export const bankAccountStatus     = ()     => http.get('/bank-account/status')

export const bankAccountSaveConfig = (data) => http.post('/bank-account/config', data)
