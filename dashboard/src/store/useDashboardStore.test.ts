import { describe, expect, it, vi } from 'vitest'
import { createMockSource } from '../data/sources/mockSource'
import { createDashboardStore } from './useDashboardStore'

describe('dashboard store', () => {
  it('loads a snapshot and derives values', async () => {
    const store = createDashboardStore(createMockSource({ drift: false }))
    await store.getState().refresh()
    const { snapshot, derived, connectionLost } = store.getState()
    expect(snapshot?.locations).toHaveLength(7)
    expect(derived?.rows).toHaveLength(4)
    expect(connectionLost).toBe(false)
  })

  it('keeps the last good data when a fetch fails', async () => {
    const source = createMockSource({ drift: false })
    const store = createDashboardStore(source)
    await store.getState().refresh()
    const good = store.getState().snapshot

    vi.spyOn(source, 'getSnapshot').mockRejectedValueOnce(new Error('offline'))
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(await store.getState().refresh()).toBe(false)
    expect(store.getState().snapshot).toBe(good)
    expect(store.getState().connectionLost).toBe(true)
  })

  it('approving a suggestion creates a pending dispatch and removes the suggestion', async () => {
    const store = createDashboardStore(createMockSource({ drift: false }))
    await store.getState().refresh()
    const sugg = store.getState().derived!.suggestions.find((s) => s.to_site === 'shelter_3')!

    await store.getState().approve(sugg)
    const { snapshot, derived } = store.getState()
    const created = snapshot!.dispatches.find((d) => d.to_site === 'shelter_3')!
    expect(created.status).toBe('pending')
    expect(created.dispatch_id).not.toBe(sugg.dispatch_id)
    expect(derived!.suggestions.find((s) => s.to_site === 'shelter_3')).toBeUndefined()
  })

  it('dismissed suggestions are remembered while they remain suggested', async () => {
    const store = createDashboardStore(createMockSource({ drift: false }))
    await store.getState().refresh()
    const id = store.getState().derived!.suggestions[0].dispatch_id
    store.getState().dismiss(id)
    await store.getState().refresh()
    expect(store.getState().dismissedSuggestionIds).toEqual([id])
  })
})

