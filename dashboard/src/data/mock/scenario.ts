import type { DashboardSnapshot, InventoryRecord, ItemType, TextMessage } from '../../types/schemas'

// Flood near Hanover, NH. Coordinates are illustrative.
// Seeded so that Shelter 3 is critically low on water and Shelter 1 is low on medical kits.

const minutesAgo = (now: number, m: number) => new Date(now - m * 60_000).toISOString()

type Stock = Record<ItemType, number>

const STARTING_STOCK: Record<string, Stock> = {
  shelter_1: { water_L: 900, food_meals: 800, medical_kits: 3, blankets: 250, cots: 230 },
  shelter_2: { water_L: 1000, food_meals: 900, medical_kits: 8, blankets: 300, cots: 280 },
  shelter_3: { water_L: 120, food_meals: 600, medical_kits: 5, blankets: 200, cots: 180 },
  shelter_4: { water_L: 400, food_meals: 300, medical_kits: 3, blankets: 100, cots: 95 },
  depot_a: { water_L: 5000, food_meals: 4000, medical_kits: 60, blankets: 800, cots: 400 },
  depot_b: { water_L: 3000, food_meals: 2500, medical_kits: 40, blankets: 500, cots: 300 },
}

function seedInventory(now: number): InventoryRecord[] {
  return Object.entries(STARTING_STOCK).flatMap(([site_id, stock]) =>
    (Object.entries(stock) as [ItemType, number][]).map(([item, quantity]) => ({
      site_id,
      item,
      quantity,
      source: site_id.startsWith('depot') ? ('manual' as const) : ('sms' as const),
      timestamp: minutesAgo(now, 0.2),
    })),
  )
}

function seedMessages(now: number): TextMessage[] {
  const msg = (
    n: number,
    ago: number,
    phone: string,
    body: string,
    parsed: TextMessage['parsed'],
    extra: Partial<TextMessage> = {},
  ): TextMessage => ({
    message_id: `msg_${String(n).padStart(3, '0')}`,
    direction: 'in',
    phone,
    body,
    timestamp: minutesAgo(now, ago),
    parsed,
    needs_review: false,
    ...extra,
  })

  return [
    msg(1, 58, '603-555-0101', 'Hanover High shelter open, 200 people so far. Have 900L water.', {
      site_id: 'shelter_1', item: 'water_L', quantity: 900, urgency: 'low', intent: 'inventory_report', confidence: 0.92,
    }),
    msg(2, 55, '603-555-0144', 'Leverone field house has 300 blankets and 280 cots set up', {
      site_id: 'shelter_2', item: 'blankets', quantity: 300, urgency: 'low', intent: 'inventory_report', confidence: 0.88,
    }),
    msg(3, 50, '603-555-0177', 'Water rising on Mill St, need sandbags', {
      lat: 43.6915, lng: -72.2765, urgency: 'high', intent: 'request', confidence: 0.71,
    }),
    msg(4, 47, '603-555-0123', 'Lebanon middle school only has about 120 L of water left!!', {
      site_id: 'shelter_3', item: 'water_L', quantity: 120, urgency: 'high', intent: 'inventory_report', confidence: 0.9,
    }),
    msg(5, 46, '603-555-0123', 'Thanks, we will check on Lebanon shortly.', undefined, { direction: 'out' }),
    msg(6, 42, '603-555-0190', 'Norwich town hall: 90 people, ok for now', {
      site_id: 'shelter_4', urgency: 'low', intent: 'status', confidence: 0.85,
    }),
    msg(7, 39, '603-555-0101', 'Running low on first aid kits at hanover high, only 3 left', {
      site_id: 'shelter_1', item: 'medical_kits', quantity: 3, urgency: 'medium', intent: 'inventory_report', confidence: 0.87,
    }),
    msg(8, 35, '603-555-0166', 'asdf ok?? the thing by the bridge', undefined, { needs_review: true }),
    msg(9, 31, '603-555-0112', 'Family of 5 stuck on 2nd floor, Lyme Rd near the river. Need pickup', {
      lat: 43.7240, lng: -72.2810, urgency: 'high', intent: 'request', confidence: 0.83,
    }),
    msg(10, 27, '603-555-0158', 'My dad cut his leg badly on debris, bleeding a lot. At Mink Brook bridge', {
      lat: 43.6925, lng: -72.2790, item: 'medical_kits', quantity: 1, urgency: 'critical', intent: 'request', confidence: 0.79,
    }, { needs_review: true }),
    msg(11, 22, '603-555-0144', 'Leverone needs 2 more med kits please', {
      site_id: 'shelter_2', item: 'medical_kits', quantity: 2, urgency: 'medium', intent: 'request', confidence: 0.86,
    }),
    msg(12, 18, '603-555-0123', 'Lebanon MS getting more arrivals, water is the main issue', {
      site_id: 'shelter_3', item: 'water_L', urgency: 'high', intent: 'request', confidence: 0.84,
    }),
    msg(13, 12, '603-555-0190', 'Norwich got 400 L of water stored', {
      site_id: 'shelter_4', item: 'water_L', quantity: 400, urgency: 'low', intent: 'inventory_report', confidence: 0.91,
    }),
    msg(14, 6, '603-555-0133', 'Is the Etna road open to West Leb?', {
      urgency: 'low', intent: 'other', confidence: 0.6,
    }),
    msg(15, 3, '603-555-0101', 'Hanover High needs 50 more meals tonight', {
      site_id: 'shelter_1', item: 'food_meals', quantity: 50, urgency: 'medium', intent: 'request', confidence: 0.89,
    }),
  ]
}

export function createScenario(now = Date.now()): DashboardSnapshot {
  return {
    locations: [
      { id: 'shelter_1', name: 'Hanover High School', kind: 'shelter', lat: 43.7105, lng: -72.287, capacity: 300 },
      { id: 'shelter_2', name: 'Leverone Field House', kind: 'shelter', lat: 43.7005, lng: -72.284, capacity: 400 },
      { id: 'shelter_3', name: 'Lebanon Middle School', kind: 'shelter', lat: 43.642, lng: -72.251, capacity: 200 },
      { id: 'shelter_4', name: 'Norwich Town Hall', kind: 'shelter', lat: 43.715, lng: -72.308, capacity: 150 },
      { id: 'depot_a', name: 'Depot A (Etna)', kind: 'depot', lat: 43.693, lng: -72.223 },
      { id: 'depot_b', name: 'Depot B (West Lebanon)', kind: 'depot', lat: 43.645, lng: -72.31 },
      { id: 'incident_1', name: 'Mink Brook Flood Zone', kind: 'incident', lat: 43.69, lng: -72.278 },
    ],
    cameras: [
      { camera_id: 'cam_s1', site_id: 'shelter_1', online: true, last_frame_at: minutesAgo(now, 0) },
      { camera_id: 'cam_s2', site_id: 'shelter_2', online: true, last_frame_at: minutesAgo(now, 0) },
      { camera_id: 'cam_s3', site_id: 'shelter_3', online: true, last_frame_at: minutesAgo(now, 0) },
      { camera_id: 'cam_s4', site_id: 'shelter_4', online: false, last_frame_at: minutesAgo(now, 14) },
    ],
    peopleCounts: [
      { site_id: 'shelter_1', camera_id: 'cam_s1', timestamp: minutesAgo(now, 0), people_count: 220, confidence: 0.91 },
      { site_id: 'shelter_2', camera_id: 'cam_s2', timestamp: minutesAgo(now, 0), people_count: 260, confidence: 0.88 },
      { site_id: 'shelter_3', camera_id: 'cam_s3', timestamp: minutesAgo(now, 0), people_count: 170, confidence: 0.9 },
      { site_id: 'shelter_4', camera_id: 'cam_s4', timestamp: minutesAgo(now, 14), people_count: 90, confidence: 0.82 },
    ],
    inventory: seedInventory(now),
    dispatches: [
      {
        dispatch_id: 'dsp_001', from_site: 'depot_a', to_site: 'shelter_1', items: { food_meals: 200 },
        status: 'delivered', eta_minutes: 0, created_at: minutesAgo(now, 50), updated_at: minutesAgo(now, 20),
      },
      {
        dispatch_id: 'dsp_002', from_site: 'depot_b', to_site: 'shelter_4', items: { water_L: 100 },
        status: 'en_route', eta_minutes: 6, created_at: minutesAgo(now, 15), updated_at: minutesAgo(now, 5),
      },
      {
        dispatch_id: 'dsp_003', from_site: 'depot_a', to_site: 'shelter_2', items: { blankets: 50 },
        status: 'pending', created_at: minutesAgo(now, 4), updated_at: minutesAgo(now, 4),
      },
    ],
    messages: seedMessages(now),
  }
}

type IncomingText = Pick<TextMessage, 'phone' | 'body' | 'parsed'>

// Routine texts the mock drips in while the demo runs. Nothing here needs review,
// so the alert ranking stays stable.
export const INCOMING_TEXTS: IncomingText[] = [
  {
    phone: '603-555-0144', body: 'Leverone: 10 more families checked in, all fine',
    parsed: { site_id: 'shelter_2', urgency: 'low', intent: 'status', confidence: 0.9 },
  },
  {
    phone: '603-555-0101', body: 'Hanover High: power is back on in the gym',
    parsed: { site_id: 'shelter_1', urgency: 'low', intent: 'status', confidence: 0.88 },
  },
  {
    phone: '603-555-0181', body: 'Road closed at Route 10 and Lyme Rd, water over the road',
    parsed: { lat: 43.7195, lng: -72.2795, urgency: 'medium', intent: 'other', confidence: 0.81 },
  },
  {
    phone: '603-555-0190', body: 'Norwich: could use 20 more blankets tonight',
    parsed: { site_id: 'shelter_4', item: 'blankets', quantity: 20, urgency: 'medium', intent: 'request', confidence: 0.86 },
  },
  {
    phone: '603-555-0122', body: 'Elderly neighbor needs a ride to a shelter, Etna Rd',
    parsed: { lat: 43.6955, lng: -72.2405, urgency: 'high', intent: 'request', confidence: 0.8 },
  },
  {
    phone: '603-555-0144', body: 'Leverone has 1000 L water on hand',
    parsed: { site_id: 'shelter_2', item: 'water_L', quantity: 1000, urgency: 'low', intent: 'inventory_report', confidence: 0.91 },
  },
]

