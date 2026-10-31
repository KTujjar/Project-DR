import { describe, expect, it, vi } from 'vitest'
import { createScenario } from '../mock/scenario'
import { createApiSource } from './apiSource'

function fakeFetch(status = 200, body: unknown = {}) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status, statusText: status === 200 ? 'OK' : 'Error' }))
}

describe('apiSource', () => {
  it('GETs the snapshot from /api/snapshot', async () => {
    const snapshot = createScenario(0)
    const f = fakeFetch(200, snapshot)
    const src = createApiSource('http://backend:8000/', f)
    expect(await src.getSnapshot()).toEqual(snapshot)
    expect(f).toHaveBeenCalledWith('http://backend:8000/api/snapshot', expect.anything())
  })

  it('POSTs actions to the documented endpoints', async () => {
    const f = fakeFetch()
    const src = createApiSource('http://backend', f)
    const dispatch = createScenario(0).dispatches[0]

    await src.approveDispatch('dsp 1')
    await src.cancelDispatch('dsp_2')
    await src.createDispatch(dispatch)
    await src.sendText('603-555-0101', 'On the way')

    const calls = f.mock.calls as unknown as [string, RequestInit][]
    expect(calls.map(([url, init]) => `${init.method} ${url}`)).toEqual([
      'POST http://backend/api/dispatches/dsp%201/approve',
      'POST http://backend/api/dispatches/dsp_2/cancel',
      'POST http://backend/api/dispatches',
      'POST http://backend/api/messages',
    ])
    expect(JSON.parse(calls[2][1].body as string)).toEqual(dispatch)
    expect(JSON.parse(calls[3][1].body as string)).toEqual({ phone: '603-555-0101', body: 'On the way' })
  })

  it('throws on a non-2xx response so the store can back off', async () => {
    const src = createApiSource('http://backend', fakeFetch(503))
    await expect(src.getSnapshot()).rejects.toThrow(/503/)
  })
})

