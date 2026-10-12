// Core API client: auth, users, licence, pricing, platform admin, file manager (shared HTTP client: ./http.js)
import axios from 'axios'
import http from './http.js'
import { persistTokenFields } from './authFetch.js'
export { errMsg } from './http.js'
export { default } from './http.js'

export const login          = (email, pw)    => http.post('/auth/login', { email, password: pw })

export const verifySession  = (userId)       => http.get(`/auth/verify/${userId}`)

export const register       = (data)         => http.post('/auth/register', data)

export const changePassword = (data)         => http.post('/auth/change-password', data).then(r => { persistTokenFields(r.data); return r })

export const getAllUsers     = ()             => http.get('/auth/users')

export const deleteUser     = (id)           => http.delete(`/auth/users/${id}`)

export const groqPoolList       = ()              => http.get('/groq-pool')

export const groqPoolAdd        = (body)          => http.post('/groq-pool', body)

export const groqPoolUpdate     = (id, body)      => http.patch(`/groq-pool/${id}`, body)

export const groqPoolRemove     = (id)            => http.delete(`/groq-pool/${id}`)

export const groqPoolListModels = (key_value)     => http.post('/groq-pool/models', { key_value })

export const platformSettings       = (service)         => http.get('/platform-settings', { params: service ? { service } : {} })

export const savePlatformSetting    = (body)             => http.post('/platform-settings', body)

export const deletePlatformSetting  = (id)               => http.delete(`/platform-settings/${id}`)

export const testDatabaseConnection = (connection_url)   => http.post('/platform-settings/test-database', { connection_url })

export const testS3Connection       = (body)             => http.post('/platform-settings/test-s3', body)

export const fmTree      = ()           => http.get('/filemanager/tree')

export const fmRead      = (path, tbl)  => http.get(`/filemanager/read/${encodeURIComponent(path)}`, { params: { table: tbl||'' } })

export const fmSave      = (body)       => http.post('/filemanager/save', body)

export const fmDeleteRow = (body)       => http.delete('/filemanager/delete-row', { data: body })

export const dbListTables      = ()                        => http.get('/db-browser/tables')

export const dbTableSchema     = (table)                    => http.get(`/db-browser/tables/${table}/schema`)

export const dbTableRows       = (table, params)            => http.get(`/db-browser/tables/${table}/rows`, { params })

export const dbUpdateRow       = (table, id, data)          => http.put(`/db-browser/tables/${table}/rows/${encodeURIComponent(id)}`, { data })

export const dbDeleteRow       = (table, id)                => http.delete(`/db-browser/tables/${table}/rows/${encodeURIComponent(id)}`)

export const dbBulkDeleteRows  = (table, ids)                => http.delete(`/db-browser/tables/${table}/rows`, { data: { ids } })

export const dbInsertRow       = (table, data)              => http.post(`/db-browser/tables/${table}/rows`, { data })

export const dbUploadCsv       = (table, file)               => { const fd = new FormData(); fd.append('file', file); return http.post(`/db-browser/tables/${table}/upload-csv`, fd, { headers: { 'Content-Type': 'multipart/form-data' } }) }

export const dbRunQuery        = (sql)                       => http.post('/db-browser/query', { sql })

export const licenceList       = ()          => http.get('/licence/list')

export const licenceSave       = (body)      => http.post('/licence/save', body)

export const licenceDeleteUser = (uid)       => http.delete(`/licence/user/${uid}`)

export const licenceMyModules  = (uid)       => http.get('/licence/my-modules', { params: { user_id: uid } })

export const licenceUpdateUser = (uid, body) => http.patch(`/licence/user/${uid}`, body)

export const forgotPassword   = (email)     => http.post('/auth/forgot-password', { email })

export const resetPassword    = (token, pw) => http.post('/auth/reset-password', { token, new_password: pw })

export const verifyResetToken = (token)     => http.get('/auth/verify-reset-token', { params: { token } })

export const getPlans       = ()     => http.get('/payments/plans')

export const getMyPlan      = (uid)  => http.get(`/payments/my-plan/${uid}`)

export const getPricingPlans    = ()              => http.get('/pricing/plans')

export const savePricingPlans   = (data)          => http.post('/pricing/plans', data)

export const updatePricingPlan  = (planId, data)  => http.patch(`/pricing/plans/${planId}`, data)

export const getModuleVisibility  = ()      => axios.get('/api/module-visibility')

export const saveModuleVisibility = (data)  => http.post('/module-visibility', data)
