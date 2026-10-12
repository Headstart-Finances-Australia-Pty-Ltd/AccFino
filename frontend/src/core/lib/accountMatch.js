// Do two bank-account numbers belong to the same account?
// Statements carry the full number ("062000 12345678"); bank feeds (Open Banking) usually give a MASKED one ("xxxxxx xxxxx1912"), i.e. only the last digits.
// Compare the digits only: equal, or one is the end of the other when that shorter one has at least 4 digits (the part a masked number reveals).
export const digitsOf = v => String(v || '').replace(/\D/g, '')

export function sameAccountNumber(a, b) {
  const x = digitsOf(a), y = digitsOf(b)
  if (!x || !y) return false
  if (x === y) return true
  const [short, long] = x.length <= y.length ? [x, y] : [y, x]
  return short.length >= 4 && long.endsWith(short)
}
