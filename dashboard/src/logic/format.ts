// Shows only the last 4 digits of a phone number: "***-***-1234".
export function maskPhone(phone: string): string {
  const digits = phone.replace(/\D/g, '')
  return `***-***-${digits.slice(-4).padStart(4, '*')}`
}
