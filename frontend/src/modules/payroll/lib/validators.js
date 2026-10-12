// Client-side checks for instant feedback. The server validates everything again; these never replace that.
const W = [1, 4, 3, 7, 5, 8, 6, 9, 10]
export const digits = v => String(v ?? '').replace(/\D/g, '')
export const validTfn = v => { const d = digits(v); return d.length === 9 && d.split('').reduce((s, c, i) => s + Number(c) * W[i], 0) % 11 === 0 }
export const validBsb = v => digits(v).length === 6
export const validAccount = v => { const n = digits(v).length; return n >= 5 && n <= 9 }
export const validEmail = v => !v || /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v)
export const validPostcode = v => !v || /^\d{4}$/.test(v)
export const positive = v => v !== '' && v != null && Number(v) > 0

export function employeeProblems(f) {
  const p = []
  if (!f.first_name?.trim()) p.push('First name is required')
  if (!f.last_name?.trim()) p.push('Last name is required')
  if (!f.start_date) p.push('Start date is required')
  if (!validEmail(f.email)) p.push('Email address is not valid')
  if (!validPostcode(f.postcode)) p.push('Postcode must be 4 digits')
  if (f.pay_basis === 'salary' && !positive(f.annual_salary)) p.push('Annual salary must be greater than zero')
  if (f.pay_basis === 'hourly' && !positive(f.hourly_rate)) p.push('Hourly rate must be greater than zero')
  if (f.employment_type === 'casual' && f.pay_basis === 'salary') p.push('Casual employees are paid by the hour')
  if (!positive(f.hours_per_week) || Number(f.hours_per_week) > 100) p.push('Ordinary hours per week must be between 0 and 100')
  if (f.end_date && f.start_date && f.end_date < f.start_date) p.push('End date cannot be before the start date')
  return p
}
