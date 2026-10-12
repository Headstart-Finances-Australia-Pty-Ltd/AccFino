// Email + phone validation for forms. This MIRRORS backend/accfino_core/security/contact.py so people get the same answer instantly in the browser
// as the server will give; the server remains the authority (it re-checks everything, so skipping this file changes nothing about what is accepted).
export const EMAIL_REQUIRED = 'Email address is required.'
export const EMAIL_INVALID = 'Please enter a valid email address.'
export const PHONE_REQUIRED = 'Phone number is required.'
export const PHONE_INVALID = 'Please enter a valid phone number.'

const LABEL = '[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
const LOCAL = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$/
const DOMAIN = new RegExp(`^${LABEL}(?:\\.${LABEL})+$`)

/** -> '' when valid, else the message to show. */
export function emailError(raw) {
  const s = (raw || '').trim()
  if (!s) return EMAIL_REQUIRED
  if (s.length > 200 || (s.match(/@/g) || []).length !== 1 || /\s/.test(s)) return EMAIL_INVALID
  const i = s.lastIndexOf('@')
  const local = s.slice(0, i), domain = s.slice(i + 1)
  if (!local || local.length > 64 || !LOCAL.test(local) || local.startsWith('.') || local.endsWith('.') || local.includes('..')) return EMAIL_INVALID
  if (!DOMAIN.test(domain) || !/^[A-Za-z]{2,}$/.test(domain.slice(domain.lastIndexOf('.') + 1))) return EMAIL_INVALID
  return ''
}

/** -> E.164 string, or '' when invalid. Australian national format is assumed without a country code. */
export function normalisePhone(raw) {
  const s = (raw || '').trim()
  if (!s || /[^\d\s()+.\-]/.test(s) || s.slice(1).includes('+')) return ''
  const digits = s.replace(/\D/g, '')
  let e164
  if (s.startsWith('+')) e164 = '+' + digits
  else if (digits.startsWith('00')) e164 = '+' + digits.slice(2)
  else if (digits.startsWith('0')) e164 = '+61' + digits.slice(1)
  else if (digits.startsWith('61') && digits.length === 11) e164 = '+' + digits
  else return ''
  if (!/^\+[1-9]\d{7,14}$/.test(e164)) return ''
  if (e164.startsWith('+61') && !/^[2-578]\d{8}$/.test(e164.slice(3))) return ''
  if (e164.startsWith('+1') && !/^[2-9]\d{9}$/.test(e164.slice(2))) return ''
  return e164
}

export function phoneError(raw) {
  if (!(raw || '').trim()) return PHONE_REQUIRED
  return normalisePhone(raw) ? '' : PHONE_INVALID
}

/** 0412 345 678 style display for a stored E.164 number. */
export function formatPhone(e164) {
  const p = (e164 || '').trim()
  if (/^\+61[2-578]\d{8}$/.test(p)) {
    const n = '0' + p.slice(3)
    return n.startsWith('04') ? `${n.slice(0, 4)} ${n.slice(4, 7)} ${n.slice(7)}` : `(${n.slice(0, 2)}) ${n.slice(2, 6)} ${n.slice(6)}`
  }
  return p
}
