import { describe, it, expect } from 'vitest'
import { emailError, phoneError, normalisePhone, formatPhone, EMAIL_REQUIRED, EMAIL_INVALID, PHONE_REQUIRED, PHONE_INVALID } from './contact.js'

describe('email', () => {
  it('requires it and explains', () => { expect(emailError('')).toBe(EMAIL_REQUIRED); expect(emailError('   ')).toBe(EMAIL_REQUIRED); expect(emailError(undefined)).toBe(EMAIL_REQUIRED) })
  it.each(['plain', 'a@b', '@x.com', 'a@@x.com', 'a b@x.com', 'a@x..com', '.a@x.com', 'a.@x.com', 'a@-x.com', 'a@x.c', 'a@x.123'])('rejects %s', v => expect(emailError(v)).toBe(EMAIL_INVALID))
  it.each(['a@b.co', 'First.Last+tag@Example.COM.au', "o'neil@example.org"])('accepts %s', v => expect(emailError(v)).toBe(''))
})
describe('phone', () => {
  it('requires it', () => { expect(phoneError('')).toBe(PHONE_REQUIRED); expect(phoneError(' ')).toBe(PHONE_REQUIRED) })
  it.each([['0412 345 678', '+61412345678'], ['+61 412 345 678', '+61412345678'], ['(02) 9999 9999', '+61299999999'], ['0061412345678', '+61412345678'],
    ['+64 21 123 4567', '+64211234567'], ['+44 7911 123456', '+447911123456'], ['+1 415 555 2671', '+14155552671']])('accepts %s', (raw, e) => { expect(phoneError(raw)).toBe(''); expect(normalisePhone(raw)).toBe(e) })
  it.each(['abc', '12345', '0112345678', '0412 345', '+61 112 345 678', '++61412345678', '+1 115 555 2671', '04123 45678 ext 5'])('rejects %s', v => expect(phoneError(v)).toBe(PHONE_INVALID))
  it('formats for display', () => { expect(formatPhone('+61412345678')).toBe('0412 345 678'); expect(formatPhone('+61299999999')).toBe('(02) 9999 9999'); expect(formatPhone('+447911123456')).toBe('+447911123456') })
})
