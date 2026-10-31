import { config } from '../../logic/config'
import type { DashboardSnapshot, DataSource, Dispatch, ItemType, TextMessage } from '../../types/schemas'
import { INCOMING_TEXTS, createScenario } from '../mock/scenario'

// Ticks a dispatch waits in "pending" before the mock dispatcher sends it out.
const PENDING_TICKS = 2
// Simulated minutes per tick (one tick per 3 s poll): drives travel and consumption.
const MINUTES_PER_TICK = 1
const HEADCOUNT_JITTER = 0.05
const NEW_TEXT_CHANCE = 0.2

export interface MockOptions {
  clock?: () => number
  seed?: number
  // Off in unit tests that need exact numbers.
  drift?: boolean
}

export interface MockSource extends DataSource {
  tick(): void
  // Demo script: new arrivals at Shelter 3 and a text reporting water nearly gone.
  triggerDemoEvent(): void
}

// Small seeded PRNG so a demo run is repeatable.
function mulberry32(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function createMockSource({ clock = Date.now, seed = 42, drift = true }: MockOptions = {}): MockSource {
  const state: DashboardSnapshot = createScenario(clock())
  const pendingTicks = new Map<string, number>()
  let messageSeq = state.messages.length
  const rand = mulberry32(seed)
  // Counts jitter around these targets instead of random-walking away from the scenario.
  const targetCounts = new Map(state.peopleCounts.map((c) => [c.camera_id, c.people_count]))
  // Fractional consumption carried between ticks so slow burn rates still add up.
  const burnCarry = new Map<string, number>()
  let nextIncoming = 0

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

  function addMessage(m: Omit<TextMessage, 'message_id' | 'timestamp'>) {
    messageSeq += 1
    state.messages.push({ ...m, message_id: `msg_${String(messageSeq).padStart(3, '0')}`, timestamp: iso() })
  }

  function addOutgoing(phone: string, body: string) {
    addMessage({ direction: 'out', phone, body, needs_review: false })
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

  function capacityOf(site_id: string) {
    return state.locations.find((l) => l.id === site_id)?.capacity
  }

  // Simulated headcounts refresh within ±5% of their target. Noise alone never pushes a
  // site over the capacity alert line; only a target above it (e.g. the demo event) does.
  function refreshCounts() {
    const now = iso()
    for (const pc of state.peopleCounts) {
      pc.timestamp = now
      if (!drift) continue
      const target = targetCounts.get(pc.camera_id) ?? pc.people_count
      let count = Math.round(target * (1 + (rand() * 2 - 1) * HEADCOUNT_JITTER))
      const capacity = capacityOf(pc.site_id)
      if (capacity) count = Math.min(count, Math.max(target, Math.floor(capacity * config.capacityCriticalRatio)))
      pc.people_count = count
      pc.confidence = Math.round((0.82 + rand() * 0.15) * 100) / 100
    }
  }

  // Occupied shelters consume water and food at the planning rates.
  function consumeStock() {
    const perPersonPerTick = (rate = 0) => (rate * MINUTES_PER_TICK) / (24 * 60)
    for (const pc of state.peopleCounts) {
      for (const item of ['water_L', 'food_meals'] as const) {
        const key = `${pc.site_id}|${item}`
        const used = (burnCarry.get(key) ?? 0) + pc.people_count * perPersonPerTick(config.dailyRates[item])
        const whole = Math.floor(used)
        burnCarry.set(key, used - whole)
        if (whole > 0) adjustStock(pc.site_id, item, -whole)
      }
    }
  }

  function maybeAddIncomingText() {
    if (rand() >= NEW_TEXT_CHANCE) return
    const template = INCOMING_TEXTS[nextIncoming % INCOMING_TEXTS.length]
    nextIncoming += 1
    addMessage({ ...structuredClone(template), direction: 'in', needs_review: false })
  }

  function tick() {
    refreshCounts()
    advanceDispatches()
    if (drift) {
      consumeStock()
      maybeAddIncomingText()
    }
  }

  function triggerDemoEvent() {
    targetCounts.set('sim_s3', 176)
    const pc = state.peopleCounts.find((c) => c.camera_id === 'sim_s3')
    if (pc) pc.people_count = 176
    const record = state.inventory.find((r) => r.site_id === 'shelter_3' && r.item === 'water_L')
    if (record) {
      record.quantity = Math.min(record.quantity, 60)
      record.source = 'sms'
      record.timestamp = iso()
    }
    addMessage({
      direction: 'in',
      phone: '603-555-0123',
      body: 'Lebanon MS: bus of 6 more just arrived, we are down to about 60 L of water',
      parsed: {
        site_id: 'shelter_3', item: 'water_L', quantity: 60, urgency: 'critical', intent: 'inventory_report', confidence: 0.93,
      },
      needs_review: false,
    })
  }

  return {
    tick,
    triggerDemoEvent,

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
