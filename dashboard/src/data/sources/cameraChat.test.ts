import { describe, expect, it, vi } from 'vitest'
import { askCamera, fetchSceneLog } from './cameraChat'

const respond = (status: number, body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status }))

describe('askCamera', () => {
  it('POSTs the conversation and site, and returns the answer', async () => {
    const answer = { reply: 'About 8 people, calm.', used: { image: true, minutes: 30, scene_notes: 3 } }
    const f = respond(200, answer)
    const messages = [{ role: 'user' as const, content: "What's happening now?" }]
    expect(await askCamera('http://cv:8001/', 'cam laptop', messages, 'Hanover High School', f)).toEqual(answer)
    const [url, init] = (f.mock.calls as unknown as [string, RequestInit][])[0]
    expect(url).toBe('http://cv:8001/api/cameras/cam%20laptop/chat')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ messages, site_name: 'Hanover High School' })
  })

  it("surfaces the service's reason when it fails", async () => {
    const noKey = respond(503, { detail: 'Add an Anthropic API key to use the camera chat.' })
    await expect(askCamera('http://cv', 'c', [{ role: 'user', content: 'q' }], undefined, noKey)).rejects.toThrow(
      'Add an Anthropic API key',
    )
    const html = vi.fn(async () => new Response('<html>', { status: 500 }))
    await expect(askCamera('http://cv', 'c', [{ role: 'user', content: 'q' }], undefined, html)).rejects.toThrow('(500)')
  })
})

describe('fetchSceneLog', () => {
  it('returns the notes', async () => {
    const log = { enabled: true, notes: [{ time: '2026-10-31T08:00:00.000Z', text: 'Two people at the desk.' }] }
    expect(await fetchSceneLog('http://cv', 'cam_laptop', respond(200, log))).toEqual(log)
  })
})
