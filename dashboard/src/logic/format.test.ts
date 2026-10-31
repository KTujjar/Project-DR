import { describe, expect, it } from 'vitest'
import { maskPhone } from './format'

describe('maskPhone', () => {
  it('keeps only the last 4 digits', () => {
    expect(maskPhone('603-555-0123')).toBe('***-***-0123')
    expect(maskPhone('+1 (603) 555-9876')).toBe('***-***-9876')
  })

  it('never leaks short or empty input', () => {
    expect(maskPhone('12')).toBe('***-***-**12')
    expect(maskPhone('')).toBe('***-***-****')
  })
})
