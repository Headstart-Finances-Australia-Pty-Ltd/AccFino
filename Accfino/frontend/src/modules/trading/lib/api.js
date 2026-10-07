// trading module API client
import http from '../../../core/lib/http.js'

export const tradingAnalyze = (fd)           => http.post('/trading/analyze', fd, { headers:{'Content-Type':'multipart/form-data'} })

export const tradingExport  = (fd)           => http.post('/trading/export', fd, { headers:{'Content-Type':'multipart/form-data'}, responseType:'blob' })

export const stocksStatus  = ()            => http.get('/stocks/status')

export const stocksAnalyze = (fd)          => http.post('/stocks/analyze', fd, { headers:{'Content-Type':'multipart/form-data'} })

export const stocksExport  = (fd)          => http.post('/stocks/export',  fd, { headers:{'Content-Type':'multipart/form-data'}, responseType:'blob' })
