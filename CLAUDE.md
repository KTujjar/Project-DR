# CLAUDE.md: Project-DR Dashboard

## Project context

Project-DR is a hackathon project for natural disaster resource distribution and dispatch. This folder (`dashboard/`) is the **coordinator dashboard**: a single-page web app showing where people are, what supplies exist, where the shortfalls are, and what is being dispatched, all updating live.

The dashboard consumes data from teammate modules and does not own their logic:

- **Video Processing**: people/inventory counts from cameras
- **Video Capture**: camera feeds
- **Text Interface**: SMS in and out, parsed by AI
- **Dispatch Inventory**: stock levels and dispatch orders

The dashboard's job is to combine this data, compute need vs. supply, suggest dispatches, and let a human coordinator approve them.

### Goals

- A live map with sites, depots, dispatch routes, and text-request pins.
- A need-vs-supply view that turns camera headcounts into concrete shortfalls.
- A dispatch queue where suggested dispatches can be approved.
- A text feed showing raw messages next to their AI-parsed fields.
- Runs fully on mock data, so it is never blocked waiting on teammates.

## Rules

- Work only inside `dashboard/`. Never edit teammates' folders.
- Follow the **Build order** below one step at a time. After each step, run the dev server and tests, fix any errors, then commit with a message like `dashboard: step 3 - store and logic`.
- Stick to the **Data contracts** exactly; they are shared with teammates. Ask before changing schemas or the tech stack.
- Keep all calculations in `src/logic/` as pure, unit-tested functions. The UI only renders results.
- Use mock data until told the API is ready.
- Never commit secrets. Keep URLs in `.env`; list variables in `.env.example`.
- Mask phone numbers in the UI (`***-***-1234`).
- Prefer small, readable components over clever abstractions; this is a 24 to 48 hour hackathon.
- Nothing is dispatched without a human clicking Approve.

## Commands

```bash
npm install
npm run dev     # start dev server
npm test        # run Vitest unit tests
npm run build   # production build
```

## Tech stack

| Concern   | Choice                              | Why                                  |
| --------- | ----------------------------------- | ------------------------------------ |
| Framework | React 18 + TypeScript + Vite        | Fast setup, typed data contracts     |
| Styling   | Tailwind CSS                        | Quick, consistent layout             |
| Map       | react-leaflet + OpenStreetMap       | Free, no API key, markers and lines  |
| State     | Zustand                             | One small store for all live data    |
| Charts    | Recharts                            | Simple bars for stock levels         |
| Tests     | Vitest                              | Native to Vite                       |
| Live data | Polling every 3 s (WebSocket later) | Easiest to integrate with teammates  |

## Folder structure

```
dashboard/
  src/
    types/          # data contracts (schemas.ts)
    data/
      mock/         # mock JSON + mock generator
      sources/      # DataSource interface: mockSource.ts, apiSource.ts
    store/          # Zustand store (useDashboardStore.ts)
    logic/          # shortfall, severity, priority, dispatch suggestions + config.ts
    components/
      MapPanel/
      NeedSupplyPanel/
      InventoryPanel/
      DispatchQueue/
      TextFeed/
      AlertsBar/
      CameraGrid/
    App.tsx
  .env.example      # VITE_DATA_SOURCE=mock|api, VITE_API_BASE_URL
```

## Data contracts

Put these in `src/types/schemas.ts`. Every record carries an ISO 8601 `timestamp` so the dashboard can flag stale data.

```ts
// Locations: shelters, depots, camera sites
export type LocationKind = "shelter" | "depot" | "incident";
export interface Location {
  id: string;            // "shelter_3", "depot_b"
  name: string;
  kind: LocationKind;
  lat: number;
  lng: number;
  capacity?: number;     // max people, shelters only
}

// From Video Processing
export interface PeopleCount {
  site_id: string;
  camera_id: string;
  timestamp: string;
  people_count: number;
  confidence: number;    // 0..1
}

// From Dispatch Inventory / Text Interface
export type ItemType = "water_L" | "food_meals" | "medical_kits" | "blankets" | "cots";
export interface InventoryRecord {
  site_id: string;
  item: ItemType;
  quantity: number;
  source: "sms" | "manual" | "camera";
  timestamp: string;
}

// From Dispatch Inventory
export type DispatchStatus = "suggested" | "pending" | "en_route" | "delivered" | "cancelled";
export interface Dispatch {
  dispatch_id: string;
  from_site: string;
  to_site: string;
  items: Partial<Record<ItemType, number>>;
  status: DispatchStatus;
  eta_minutes?: number;
  created_at: string;
  updated_at: string;
}

// From Text Interface
export interface TextMessage {
  message_id: string;
  direction: "in" | "out";
  phone: string;         // mask in UI: ***-***-1234
  body: string;
  timestamp: string;
  parsed?: {
    site_id?: string;
    lat?: number;
    lng?: number;
    item?: ItemType;
    quantity?: number;
    urgency: "low" | "medium" | "high" | "critical";
    intent: "request" | "inventory_report" | "status" | "other";
    confidence: number;
  };
  needs_review: boolean; // true if parse failed or mentions injury
}

// From Video Capture
export interface CameraFeed {
  camera_id: string;
  site_id: string;
  stream_url?: string;
  snapshot_url?: string;
  online: boolean;
  last_frame_at: string;
}
```

Open question for the team: confirm item names and units (`water_L` in litres, `food_meals` per meal) before integration.

## Data layer

All data goes through one `DataSource` interface, so switching from mock to real APIs is a one-line env change (`VITE_DATA_SOURCE=mock|api`).

```ts
export interface DashboardSnapshot {
  locations: Location[];
  peopleCounts: PeopleCount[];
  inventory: InventoryRecord[];
  dispatches: Dispatch[];
  messages: TextMessage[];
  cameras: CameraFeed[];
}

export interface DataSource {
  getSnapshot(): Promise<DashboardSnapshot>;
  approveDispatch(id: string): Promise<void>;
  cancelDispatch(id: string): Promise<void>;
  createDispatch(dispatch: Dispatch): Promise<void>; // approved dashboard suggestion, arrives as "pending"
  sendText(phone: string, body: string): Promise<void>;
}
```

### Mock scenario

A flood near Hanover, NH (coordinates are illustrative):

- 4 shelters (capacity 150 to 400), 2 depots, 1 incident zone, 4 cameras with one offline.
- Starting stock: depots well supplied; Shelter 3 low on water, Shelter 1 low on medical kits.
- 15 text messages mixing requests, inventory reports, one unparseable message, and one mentioning an injury (`needs_review: true`).
- 3 dispatches: one `pending`, one `en_route`, one `delivered`.

The mock source must simulate change every 3 s: drift people counts by ±5%, occasionally add an incoming text, advance `en_route` dispatches toward `delivered`, and reduce stock at occupied sites.

## Layout and panels

One screen, no routing. Fit a 1440 × 900 laptop screen without page scrolling; on narrow screens, panels stack vertically.

```
+----------------------------------------------------------------+
| AlertsBar: top 3 urgent issues  |  data freshness  |  clock    |
+-------------------------------------+--------------------------+
|                                     | NeedSupplyPanel          |
|            MapPanel                 |  (per-site shortfalls)   |
|                                     +--------------------------+
|                                     | DispatchQueue            |
+------------------+------------------+--------------------------+
| InventoryPanel   | TextFeed         | CameraGrid               |
+------------------+------------------+--------------------------+
```

| Panel           | Shows | Interactions |
| --------------- | ----- | ------------ |
| AlertsBar       | Top 3 items from the priority list, stale-data warning if any source is older than 60 s, live clock | Click an alert to select that site |
| MapPanel        | Shelters colored by severity, depots, offline cameras greyed, text-request pins, lines for active dispatches (dashed = pending, solid = en route) | Click a marker to select the site; popup shows headcount and stock |
| NeedSupplyPanel | One row per shelter: headcount + trend arrow, capacity %, need vs. on-hand per item, shortfall, severity badge | Sort by severity; click a row to select the site |
| DispatchQueue   | Dispatches grouped by status; suggested ones at the top with item list and route | Approve or dismiss suggestions; cancel pending ones |
| InventoryPanel  | Stock per item per site as horizontal bars, threshold line, last-updated time | Filter by item |
| TextFeed        | Newest first; raw text beside parsed fields; urgency badge; `needs_review` highlighted; outgoing replies in a different color | Click to select the parsed site; quick reply box |
| CameraGrid      | Thumbnail per camera with people-count overlay, confidence, online/offline status, last frame time | Click to enlarge |

Selecting a site anywhere highlights it in every panel. Keep the selected `site_id` in the store.

## Derived logic

Pure functions in `src/logic/`, with rates and thresholds in `src/logic/config.ts` so they can be tuned during the demo.

### Need per site

24-hour planning horizon, using the latest people count per site (sum across its cameras, or the max if cameras overlap).

| Item         | Rate per person  | Notes |
| ------------ | ---------------- | ----- |
| water_L      | 3 L / day        | Drinking only; configurable |
| food_meals   | 3 meals / day    | |
| medical_kits | 1 per 50 people  | Round up |
| blankets     | 1 per person     | One-time need, not per day |
| cots         | 1 per person     | One-time need, capped at shelter capacity |

- **Shortfall** = max(0, need − on hand)
- **Coverage** = on hand ÷ need

### Severity

Per site, based on the worst item's coverage:

- ≥ 1.0 → **OK** (green)
- 0.5 to 1.0 → **Low** (yellow)
- < 0.5 → **Critical** (red)

Also raise a Critical alert when headcount exceeds 90% of capacity.

### Priority list (feeds AlertsBar)

Score each issue as severity weight (Critical 3, Low 1) × people affected, plus a bonus for any `needs_review` text and for offline cameras at occupied sites. Sort descending.

### Dispatch suggestions (greedy)

1. For each shortfall, most severe first, find depots with surplus of that item (stock above a 20% safety reserve).
2. Pick the nearest by haversine distance; split across depots if one can't cover it.
3. Estimate ETA as distance ÷ 40 km/h.
4. Create a `Dispatch` with status `suggested`, skipping shortfalls already covered by a `pending` or `en_route` dispatch.
5. Approving calls `approveDispatch` and moves it to `pending`.

## Real-time updates and integration

The store polls `DataSource.getSnapshot()` every 3 s and recomputes derived values; panels subscribe to the store.

```
Cameras -> Video Processing --\
SMS -> Text Interface (AI) ----+--> API / backend --> DataSource --> Zustand store --> logic/ --> panels
Dispatch Inventory ------------/                                         ^
                                              approve / cancel / reply --+ (calls back through DataSource)
```

### Expected endpoints for `apiSource.ts`

To be confirmed with whoever owns the backend.

| Method | Path                          | Returns / does |
| ------ | ----------------------------- | -------------- |
| GET    | `/api/snapshot`               | Full `DashboardSnapshot` (simplest option) |
| GET    | `/api/locations`              | `Location[]` (if split endpoints are used) |
| GET    | `/api/people-counts?since=`   | `PeopleCount[]` |
| GET    | `/api/inventory`              | `InventoryRecord[]` |
| GET    | `/api/dispatches`             | `Dispatch[]` |
| GET    | `/api/messages?since=`        | `TextMessage[]` |
| POST   | `/api/dispatches`             | Creates a dispatch from an approved suggestion (body: `Dispatch`, status `pending`) |
| POST   | `/api/dispatches/:id/approve` | Moves a dispatch to `pending` |
| POST   | `/api/dispatches/:id/cancel`  | Cancels a dispatch |
| POST   | `/api/messages`               | Sends an outgoing text `{ phone, body }` |

### Resilience

- If a fetch fails, keep the last good data, show a "connection lost" banner, and retry with backoff.
- Mark any source whose newest timestamp is older than 60 s as stale.
- Upgrade to a WebSocket only if polling is too slow in practice.

## Build order

Steps 1 to 6 are the minimum demo; everything after is polish. **Stop after step 6 and summarize what works.**

1. Scaffold Vite + React + TS + Tailwind in `dashboard/`; add react-leaflet, Zustand, Recharts, Vitest. Confirm `npm run dev` works.
2. Add `schemas.ts`, the `DataSource` interface, and the mock source with seeded scenario data.
3. Add the store with 3 s polling and the `logic/` functions plus unit tests.
4. Build MapPanel with severity-colored markers and dispatch lines.
5. Build NeedSupplyPanel and DispatchQueue with approve/dismiss.
6. Build TextFeed with raw vs. parsed view.
7. Build AlertsBar with the priority list and stale-data warning.
8. Build InventoryPanel and CameraGrid.
9. Add cross-panel site selection, then mock simulation drift so the demo feels live.
10. Add `apiSource.ts` and switch via env once teammates' endpoints exist.
11. Polish: dark theme, loading and empty states, responsive stacking.

## Acceptance criteria

- [ ] `npm run dev` starts with no console errors; `npm test` passes.
- [ ] Every panel renders with mock data and updates within 3 s of a data change.
- [ ] Shelter 3 shows as Critical on the map and in NeedSupplyPanel with a correct water shortfall.
- [ ] A suggested dispatch appears for Shelter 3 from the nearest depot with surplus.
- [ ] Approving it moves it to pending → en route → delivered, and Shelter 3 turns green.
- [ ] The injury text appears highlighted in TextFeed and in AlertsBar.
- [ ] The offline camera is greyed out and listed as an alert.
- [ ] Clicking a site in any panel highlights it in all panels.
- [ ] Switching `VITE_DATA_SOURCE` to `api` uses `apiSource.ts` with no other code changes.

## Demo script (about 2 minutes)

1. Show the calm dashboard; point out the map, sources, and live counts.
2. A camera headcount at Shelter 3 jumps; it turns red and tops the alerts.
3. An incoming text reports low water there; show the raw text next to the AI-parsed fields.
4. The system suggests a dispatch from the nearest depot; approve it.
5. Watch the route appear, the status advance, and an outgoing confirmation text.
6. Shelter 3 turns green. End on the full dashboard.
