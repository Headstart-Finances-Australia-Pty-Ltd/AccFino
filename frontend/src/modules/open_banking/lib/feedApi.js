// Open Banking: organisation bank feeds and platform provider set-up
import { http } from '../../../core/lib/platformHttp.js'

export const adminOpenBanking    = ()              => http.get('/admin/open-banking', { params: { _t: Date.now() } })

export const adminSaveBasiq      = (body)          => http.put('/admin/open-banking/basiq', body)

export const adminTestBasiq      = ()              => http.post('/admin/open-banking/basiq/test')

export const obFeedStatus       = ()              => http.get('/org/current/open-banking')

export const obFeedConnect      = (return_to, popup_origin) => http.post('/org/current/open-banking/connect', { return_to, popup_origin })

export const obFeedSetAccount   = (account_id, enabled) => http.post('/org/current/open-banking/account', { account_id, enabled })

export const obFeedSync         = ()              => http.post('/org/current/open-banking/sync')

export const obFeedDisconnect   = ()              => http.post('/org/current/open-banking/disconnect')
