import type { DashboardSnapshot, DataSource, Dispatch, ItemType } from '../../types/schemas'
import { createScenario } from '../mock/scenario'

// Ticks a dispatch waits in "pending" before the mock dispatcher sends it out.
const PENDING_TICKS = 2
// Simulated minutes of travel per tick (one tick per 3 s poll).
const MINUTES_PER_TICK = 1

export interface MockSource extends DataSource {
  tick(): void
}

export function createMockSource(clock: () => number = Date.now): MockSource {
  const state: DashboardSnapshot = createScenario(clock())
  const pendingTicks = new Map<string, number>()
  let messageSeq = state.messages.length

  const iso = () => new Date(clock()).toISOString()

  function adjustStock(site_id: string, item: ItemType, delta: number) {
    const record = state.inventory.find((r) => r.site_id === site_id && r.item === item)
    if (record) {
      record.quantity = Math.max(0, record.quantity + delta)
      record.timestamp = iso()
    } else {
      state.inventory.push({ site_id, item, quantity: Math.max(0, delta), source: 'manual', timestamp: iso() })
    }
  }

  function moveItems(d: Dispatch, site_id: string, sign: 1 | -1) {
    for (const [item, qty] of Object.entries(d.items) as [ItemType, number][]) {
      adjustStock(site_id, item, sign * qty)
    }
  }

  function addOutgoing(phone: string, body: string) {
    messageSeq += 1
    state.messages.push({
      message_id: `msg_${String(messageSeq).padStart(3, '0')}`,
      direction: 'out',
      phone,
      body,
      timestamp: iso(),
      needs_review: false,
    })
  }

  function siteName(id: string) {
    return state.locations.find((l) => l.id === id)?.name ?? id
  }

  // Latest inbound phone that wrote about a site, so delivery confirmations reach a person there.
  function contactFor(site_id: string) {
    return [...state.messages].reverse().find((m) => m.direction === 'in' && m.parsed?.site_id === site_id)?.phone
  }

  function advanceDispatches() {
    for (const d of state.dispatches) {
      if (d.status === 'pending') {
        const waited = (pendingTicks.get(d.dispatch_id) ?? 0) + 1
        pendingTicks.set(d.dispatch_id, waited)
        if (waited >= PENDING_TICKS) {
          d.status = 'en_route'
          d.eta_minutes = d.eta_minutes ?? 5
          d.updated_at = iso()
          moveItems(d, d.from_site, -1)
        }
      } else if (d.status === 'en_route') {
        d.eta_minutes = Math.max(0, (d.eta_minutes ?? 0) - MINUTES_PER_TICK)
        d.updated_at = iso()
        if (d.eta_minutes === 0) {
          d.status = 'delivered'
          moveItems(d, d.to_site, 1)
          const phone = contactFor(d.to_site)
          if (phone) addOutgoing(phone, `Delivery ${d.dispatch_id} has arrived at ${siteName(d.to_site)}.`)
        }
      }
    }
  }

  function refreshCameras() {
    const now = iso()
    for (const cam of state.cameras) {
      if (!cam.online) continue
      cam.last_frame_at = now
      for (const pc of state.peopleCounts) {
        if (pc.camera_id === cam.camera_id) pc.timestamp = now
      }
    }
  }

  function tick() {
    refreshCameras()
    advanceDispatches()
  }

  return {
    tick,

    async getSnapshot() {
      tick()
      return structuredClone(state)
    },

    async approveDispatch(id) {
      const d = state.dispatches.find((x) => x.dispatch_id === id)
      if (d && d.status === 'suggested') {
        d.status = 'pending'
        d.updated_at = iso()
      }
    },

    async cancelDispatch(id) {
      const d = state.dispatches.find((x) => x.dispatch_id === id)
      if (d && (d.status === 'suggested' || d.status === 'pending')) {
        d.status = 'cancelled'
        d.updated_at = iso()
      }
    },

    async createDispatch(dispatch) {
      if (state.dispatches.some((x) => x.dispatch_id === dispatch.dispatch_id)) return
      state.dispatches.push({ ...structuredClone(dispatch), status: 'pending', created_at: iso(), updated_at: iso() })
    },

    async sendText(phone, body) {
      addOutgoing(phone, body)
    },
  }
}
