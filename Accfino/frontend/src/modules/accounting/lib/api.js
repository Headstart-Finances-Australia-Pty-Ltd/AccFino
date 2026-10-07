// accounting module API client
import http from '../../../core/lib/http.js'

export const ieStatus      = ()              => http.get('/invoice-extractor/status')

export const ieProcess     = (fd)            => http.post('/invoice-extractor/process', fd, { headers:{'Content-Type':'multipart/form-data'} })

export const invoiceGetBusinesses  = ()      => http.get('/invoice/businesses')

export const invoiceCreateBusiness = (data)  => http.post('/invoice/businesses', data)

export const invoiceGetAll   = (bid)         => http.get(`/invoice/businesses/${bid}/invoices`)

export const invoiceCreate   = (data)        => http.post('/invoice/invoices', data)

export const invoiceGetOne   = (id)          => http.get(`/invoice/invoices/${id}`)

export const invoiceNextNum  = ()            => http.get('/invoice/next-number')

export const invoiceUpdateStatus = (id,stat) => http.patch(`/invoice/invoices/${id}/status`, { status:stat })
