import { describe, expect, it, vi } from 'vitest'
import { createRelayTextApi, mergeCommunityInbox, type RelayCase } from './relayTextApi'
import { dataSource } from './sources'
import { createCommunityStore } from '../store/useCommunityStore'

const card = (overrides: Partial<RelayCase> = {}): RelayCase => ({
  id: 'R-ONE', schema_version: 2, conversation_id: 'resident-a', sender_name: 'Shelter volunteer',
  original_message: 'We need food.', community_reply: 'Message received.', created_at: '2026-10-31T02:00:00Z',
  updated_at: '2026-10-31T02:00:01Z', mode: 'preview', status: 'pending_review', review_required: true,
  review_status: 'new', reply_sent_at: null, clarifying_questions: ['How much food?'], sources: [],
  interpretation: { purposes: ['assistance_request'], needs: [{ item: 'food', quantity: null, unit: null }],
    location: null, access_barriers: [], delivery_report: null, responder_summary: 'Food requested; quantity unknown.',
    unanswered_questions: [], evidence: [{ message_id: 'msg1', quote: 'We need food.' }] },
  ...overrides,
})

describe('Shared community inbox', () => {
  it('does not show simulated SMS alerts beside the separate inbox', async () => {
    const snapshot = await dataSource.getSnapshot()
    expect(snapshot.messages).toEqual([])
    expect(snapshot.locations.length).toBeGreaterThan(0)
    expect(snapshot.inventory.length).toBeGreaterThan(0)
  })

  it('shows the latest community message once per conversation', () => {
    const older = card()
    const newer = card({ id: 'R-TWO', created_at: '2026-10-31T02:05:00Z' })
    expect(mergeCommunityInbox([older], [newer])).toEqual([newer])
  })

  it('does not undo a posted reply when an earlier poll finishes', () => {
    const old = card()
    const replied = card({ updated_at: '2026-10-31T02:10:00Z', reply_sent_at: '2026-10-31T02:10:00Z', review_required: false })
    expect(mergeCommunityInbox([replied], [old])[0].reply_sent_at).toBeTruthy()
  })

  it('submits a real form message separately from a responder reply', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify(card()), { status: 202 }))
    const api = createRelayTextApi('/relay-api', fetcher)
    const message = { conversation_id: 'resident-a', sender_name: 'Shelter volunteer', text: 'We need food.', channel: 'web' as const }
    await api.intake(message)
    expect(fetcher.mock.calls[0]).toEqual(['/relay-api/intake', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(message),
    }])
  })

  it('only posts a responder reply through the explicit reviewed-reply endpoint', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify(card())))
    await createRelayTextApi('/relay-api', fetcher).reply('R-ONE', 'How many packs?', true)
    expect(fetcher.mock.calls[0]).toEqual(['/relay-api/inbox/R-ONE/reply', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: 'How many packs?', awaiting_information: true }),
    }])
  })

  it('uses the same shared state for header counts and inbox updates', async () => {
    const api = {
      health: async () => ({ mode: 'preview' as const, model: null, examples: [], inbox_version: 2 }),
      inbox: async () => [card()],
    }
    const store = createCommunityStore(api)
    await store.getState().refresh()
    expect(store.getState().items.filter((item) => !item.reply_sent_at)).toHaveLength(1)
    store.getState().upsert(card({ updated_at: '2026-10-31T02:10:00Z', reply_sent_at: '2026-10-31T02:10:00Z', review_required: false }))
    await store.getState().refresh()
    expect(store.getState().items.filter((item) => !item.reply_sent_at)).toHaveLength(0)
  })
})
