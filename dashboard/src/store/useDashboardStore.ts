import { create } from 'zustand'
import { dataSource } from '../data/sources'
import { deriveAll, type Derived } from '../logic/derive'
import type { DashboardSnapshot, DataSource, Dispatch } from '../types/schemas'

const POLL_MS = 3000
const MAX_BACKOFF_MS = 30_000

interface DashboardState {
  snapshot: DashboardSnapshot | null
  derived: Derived | null
  selectedSiteId: string | null
  connectionLost: boolean
  lastFetchAt: number | null
  dismissedSuggestionIds: string[]

  refresh(): Promise<boolean>
  startPolling(): () => void
  selectSite(id: string | null): void
  approve(dispatch: Dispatch): Promise<void>
  cancel(id: string): Promise<void>
  dismiss(id: string): void
  sendText(phone: string, body: string): Promise<void>
}

export function createDashboardStore(source: DataSource) {
  let pollTimer: ReturnType<typeof setTimeout> | undefined
  let failures = 0

  return create<DashboardState>((set, get) => ({
    snapshot: null,
    derived: null,
    selectedSiteId: null,
    connectionLost: false,
    lastFetchAt: null,
    dismissedSuggestionIds: [],

    // Fetches a snapshot and recomputes derived values. On failure, keeps the last good data.
    async refresh() {
      try {
        const snapshot = await source.getSnapshot()
        const derived = deriveAll(snapshot, get().derived?.headcounts)
        const liveIds = new Set(derived.suggestions.map((s) => s.dispatch_id))
        set({
          snapshot,
          derived,
          connectionLost: false,
          lastFetchAt: Date.now(),
          // Forget dismissals once the suggestion is gone, so a new shortfall can be suggested again.
          dismissedSuggestionIds: get().dismissedSuggestionIds.filter((id) => liveIds.has(id)),
        })
        return true
      } catch (err) {
        console.warn('Snapshot fetch failed', err)
        set({ connectionLost: true })
        return false
      }
    },

    // Polls every 3 s, backing off exponentially while fetches fail. Returns a stop function.
    startPolling() {
      if (pollTimer !== undefined) return () => {}
      const loop = async () => {
        const ok = await get().refresh()
        failures = ok ? 0 : failures + 1
        const delay = ok ? POLL_MS : Math.min(POLL_MS * 2 ** failures, MAX_BACKOFF_MS)
        pollTimer = setTimeout(loop, delay)
      }
      pollTimer = setTimeout(loop, 0)
      return () => {
        clearTimeout(pollTimer)
        pollTimer = undefined
      }
    },

    selectSite(id) {
      set({ selectedSiteId: id })
    },

    // Suggestions only exist in the dashboard, so approving one submits it as a new dispatch.
    async approve(dispatch) {
      if (dispatch.status === 'suggested' && dispatch.dispatch_id.startsWith('sugg_')) {
        const dispatch_id = `dsp_${Date.now().toString(36)}`
        await source.createDispatch({ ...dispatch, dispatch_id, status: 'pending' })
      } else {
        await source.approveDispatch(dispatch.dispatch_id)
      }
      await get().refresh()
    },

    async cancel(id) {
      await source.cancelDispatch(id)
      await get().refresh()
    },

    dismiss(id) {
      set({ dismissedSuggestionIds: [...get().dismissedSuggestionIds, id] })
    },

    async sendText(phone, body) {
      await source.sendText(phone, body)
      await get().refresh()
    },
  }))
}

export const useDashboardStore = createDashboardStore(dataSource)

