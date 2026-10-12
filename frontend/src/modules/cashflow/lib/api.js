// cashflow module API client
import http from '../../../core/lib/http.js'

export const cfDetect       = (fd)           => http.post('/cashflow/detect', fd, { headers:{'Content-Type':'multipart/form-data'} })

export const cfRun          = (rows, colMap) => http.post('/cashflow/run', { rows, col_map:colMap })

export const cfPredict      = (runId, model) => http.post(`/cashflow/predict/${runId}`, model, { headers:{'Content-Type':'application/json'} })
