// Shared data contracts. Keep in sync with CLAUDE.md; teammates rely on these shapes.
// Every record carries an ISO 8601 `timestamp` so the dashboard can flag stale data.

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

export const ITEM_TYPES: ItemType[] = ["water_L", "food_meals", "medical_kits", "blankets", "cots"];

// Data layer
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
  // Submits a dashboard-suggested dispatch the coordinator approved (arrives as "pending").
  createDispatch(dispatch: Dispatch): Promise<void>;
  sendText(phone: string, body: string): Promise<void>;
}
