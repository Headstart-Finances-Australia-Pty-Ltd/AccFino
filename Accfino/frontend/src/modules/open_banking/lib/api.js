// open_banking module API client
import http from '../../../core/lib/http.js'

export const obStatus      = ()              => http.get('/openbanking/status')

export const obCreateUser  = (data)          => http.post('/openbanking/create-user', data)

export const obAccounts    = (uid)           => http.get(`/openbanking/accounts/${uid}`)

export const obTransactions= (uid)           => http.get(`/openbanking/transactions/${uid}`)

export const obFetchNormalise = (body)     => http.post('/openbanking/fetch-and-normalise', body)

export const obReconcileAccounts = ()        => http.get('/openbanking/reconcile-accounts')

export const obSavedAccounts     = ()        => http.get('/openbanking/saved-accounts')

export const obSaveAccounts      = (accounts) => http.post('/openbanking/saved-accounts', { accounts })

export const obPull              = (body)    => http.post('/openbanking/pull', body)

export const openfeedStatus     = ()        => http.get('/openfeed/status')

export const openfeedSaveConfig = (data)    => http.post('/openfeed/config', data)

export const openfeedPublicKey    = ()      => http.get('/openfeed/public-key')

export const openfeedTest         = ()      => http.post('/openfeed/test')

export const openfeedGenerateKeys = ()      => http.post('/openfeed/keys', {})
