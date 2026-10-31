import { describe, expect, it, vi } from 'vitest'
import { createRelayTextApi, isRelayCase, mergeRelayCases, type RelayCase } from './relayTextApi'

function entry(id = 'case_1', created_at = '2026-10-31T02:00:00Z'): RelayCase {
  return {
    id, created_at, conversation_id: 'community-1', original_message: 'There are six of us. We need food.',
    community_reply: 'How many food packs do you need?', status: 'needs_clarification', mode: 'live',
    review_required: true, clarifying_questions: ['How many food packs do you need?'], sources: [],
    interpretation: {
      purposes: ['assistance_request'], needs: [{ item: 'food', quantity: null, unit: null }],
      location: null, access_barriers: [], delivery_report: null,
      responder_summary: 'Six people reported; the food quantity is unknown.', unanswered_questions: [],
      evidence: [{ message_id: 'msg_1', quote: 'There are six of us. We need food.' }],
    },
  }
}

const reply = (body: unknown, status = 200) => vi.fn(async () => new Response(JSON.stringify(body), { status }))

describe('Relay text adapter', () => {
  it('keeps an unknown item quantity unknown', () => {
    const data = entry()
    expect(isRelayCase(data)).toBe(true)
    expect(data.interpretation.needs[0].quantity).toBeNull()
  })

  it('rejects malformed cards and invalid quantities', () => {
    expect(isRelayCase({})).toBe(false)
    const data = entry()
    data.interpretation.needs[0].quantity = -1
    expect(isRelayCase(data)).toBe(false)
  })

  it('submits incoming text using the Python backend contract', async () => {
    const fetcher = reply(entry())
    const api = createRelayTextApi('/relay-api/', fetcher)
    await api.send('community-1', 'There are six of us. We need food.')
    expect(fetcher).toHaveBeenCalledWith('/relay-api/messages', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: 'community-1', text: 'There are six of us. We need food.' }),
    })
  })

  it('encodes conversation IDs and loads only that conversation', async () => {
    const fetcher = reply({ items: [entry()] })
    const api = createRelayTextApi('/relay-api', fetcher)
    expect(await api.cases('community/1')).toHaveLength(1)
    expect(fetcher).toHaveBeenCalledWith('/relay-api/requests?conversation_id=community%2F1', undefined)
  })

  it('preserves a submitted card when an older poll returns', () => {
    const older = entry('old', '2026-10-31T01:00:00Z')
    const newer = entry('new', '2026-10-31T02:00:00Z')
    expect(mergeRelayCases([newer], [older, older]).map((c) => c.id)).toEqual(['new', 'old'])
  })

  it('displays the backend explanation instead of hiding a failed AI call', async () => {
    const api = createRelayTextApi('/relay-api', reply({ detail: 'API access must be configured.' }, 503))
    await expect(api.send('community-1', 'Hello')).rejects.toThrow('API access must be configured.')
  })

  it('reports an unreachable service without substituting sample data', async () => {
    const fetcher = vi.fn(async () => { throw new Error('Network failure') })
    await expect(createRelayTextApi('/relay-api', fetcher).health()).rejects.toThrow('Start the Python backend')
  })

  it('catches an HTML response from a wrong proxy route', async () => {
    const fetcher = vi.fn(async () => new Response('<html>Wrong route</html>'))
    await expect(createRelayTextApi('/relay-api', fetcher).health()).rejects.toThrow('non-JSON')
  })

  it('keeps preview mode distinguishable from live AI', async () => {
    const health = { mode: 'preview', model: null, examples: [{ label: 'Request', text: 'We need food.' }] }
    expect(await createRelayTextApi('/relay-api', reply(health)).health()).toEqual(health)
  })
})
