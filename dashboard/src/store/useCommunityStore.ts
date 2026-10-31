import { create } from 'zustand'
import { createRelayTextApi, mergeCommunityInbox, type RelayCase, type RelayHealth } from '../data/relayTextApi'

export const communityApi = createRelayTextApi(import.meta.env.VITE_TEXT_API_BASE_URL ?? '/relay-api')

interface CommunityState {
  items: RelayCase[]
  health: RelayHealth | null
  error: string
  selectedConversationId: string | null
  refresh(): Promise<void>
  startPolling(): () => void
  select(conversationId: string | null): void
  upsert(item: RelayCase): void
}

export function createCommunityStore(api: Pick<typeof communityApi, 'inbox' | 'health'>) {
  let running = false
  let generation = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  return create<CommunityState>((set, get) => ({
    items: [], health: null, error: '', selectedConversationId: null,
    select: (selectedConversationId) => set({ selectedConversationId }),
    upsert: (item) => set((state) => ({ items: mergeCommunityInbox(state.items, [item]) })),
    async refresh() {
      try {
        const [health, items] = await Promise.all([api.health(), api.inbox()])
        if (health.inbox_version !== 2) throw new Error('Update the Python backend to enable the community inbox.')
        set((state) => ({ health, items: mergeCommunityInbox(state.items, items), error: '' }))
      } catch (error) {
        set({ error: error instanceof Error ? error.message : 'Community inbox is offline.' })
      }
    },
    startPolling() {
      if (running) return () => {}
      running = true
      const current = ++generation
      const loop = async () => {
        await get().refresh()
        if (running && generation === current) timer = setTimeout(loop, 2000)
      }
      void loop()
      return () => { running = false; generation++; clearTimeout(timer) }
    },
  }))
}

export const useCommunityStore = createCommunityStore(communityApi)
