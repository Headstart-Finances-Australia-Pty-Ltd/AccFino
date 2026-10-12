// Core: tenant addresses, sign-up, subscription requests, invitations, platform administration (force delete, bulk import, org directory, user plans)
import { http } from './platformHttp.js'

export const adminGetBulkImport = ()      => http.get('/admin/bulk-import')

export const adminSetBulkImport = enabled => http.put('/admin/bulk-import', { enabled })

export const adminGetForceDelete   = ()              => http.get('/admin/force-delete/settings')

export const adminSetForceDelete   = enabled         => http.put('/admin/force-delete/settings', { enabled })

export const adminOrgDirectory     = ()              => http.get('/admin/org-directory', { params: { _t: Date.now() }, headers: { 'Cache-Control': 'no-cache' } })

export const adminPruneEmptyOrgs   = ()              => http.post('/admin/org-directory/prune-empty')

export const adminPruneOrphanUsers = ()              => http.post('/admin/org-directory/prune-orphan-users')

export const adminUserPlans      = ()              => http.get('/admin/org-directory/user-plans', { params: { _t: Date.now() } })

export const adminSetOrgPlan     = (orgId, plan_id) => http.put(`/admin/org-directory/org/${orgId}/plan`, { plan_id })

export const adminAddressCheck   = ()              => http.get('/admin/org-directory/address-check', { params: { _t: Date.now() } })

export const adminBulkDeleteUsers  = (ids, force)    => http.post('/admin/force-delete/users', { ids, force: !!force })

export const adminBulkDeleteOrgs   = (ids, force)    => http.post('/admin/force-delete/organisations', { ids, force: !!force })

export const getSubscription      = ()              => http.get('/org/current/subscription')

export const requestSubscription  = body            => http.post('/org/current/subscription/request', body)

export const adminSubOverview     = ()              => http.get('/admin/subscriptions')

export const adminSubSettings     = body            => http.put('/admin/subscriptions/settings', body)

export const adminSavePlan        = (id, body)      => http.put(`/admin/subscriptions/plans/${id}`, body)

export const adminDeletePlan      = id              => http.delete(`/admin/subscriptions/plans/${id}`)

export const adminSaveAddon       = (id, body)      => http.put(`/admin/subscriptions/addons/${id}`, body)

export const adminDeleteAddon     = id              => http.delete(`/admin/subscriptions/addons/${id}`)

export const adminAssignOrgPlan   = (orgId, body)   => http.put(`/admin/subscriptions/orgs/${orgId}`, body)

export const tenantCurrent       = ()            => http.get('/tenant/current')

export const signupValidateOrg   = org           => http.post('/signup/organisation/validate', org)

export const signupCreateOrg     = body          => http.post('/signup/organisation', body)

export const signupSearchOrgs    = q             => http.get('/signup/organisations/search', { params: { q } })

export const signupLookupOrg     = slug          => http.get('/signup/organisations/lookup', { params: { slug } })

export const signupVerifyCode    = (slug, code)  => http.post('/signup/verify-code', { slug, code })

export const signupJoin          = body          => http.post('/signup/join', body)

export const contactConfig       = ()            => http.get('/signup/contact/config')

export const contactSend         = (channel, destination)       => http.post('/signup/contact/send', { channel, destination })

export const contactVerify       = (channel, destination, code) => http.post('/signup/contact/verify', { channel, destination, code })

export const listInvites         = ()            => http.get('/org/current/invites')

export const createInvites       = body          => http.post('/org/current/invites', body)

export const revokeInvite        = id            => http.delete(`/org/current/invites/${id}`)

export const getTenantProfile    = ()            => http.get('/org/current/tenant')

export const patchTenantProfile  = body          => http.patch('/org/current/tenant', body)
