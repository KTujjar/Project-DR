import { useEffect } from 'react'
import { Circle, CircleMarker, MapContainer, Polyline, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet'
import { useDashboardStore } from '../../store/useDashboardStore'
import { ITEM_TYPES, type Location } from '../../types/schemas'
import { ITEM_LABEL } from '../labels'
import { Panel } from '../Panel'
import { SEVERITY_COLOR, SeverityBadge } from '../SeverityBadge'

const CENTER: [number, number] = [43.68, -72.27]
const DEPOT_COLOR = '#2563eb'
const INCIDENT_COLOR = '#9333ea'
const OFFLINE_COLOR = '#94a3b8'
const URGENCY_COLOR = { low: '#64748b', medium: '#f59e0b', high: '#ea580c', critical: '#dc2626' }

const pos = (l: Location): [number, number] => [l.lat, l.lng]

// Pans to the selected site whenever the selection changes from any panel.
function FollowSelection({ target }: { target?: Location }) {
  const map = useMap()
  const lat = target?.lat
  const lng = target?.lng
  useEffect(() => {
    if (lat !== undefined && lng !== undefined) map.flyTo([lat, lng], Math.max(map.getZoom(), 13), { duration: 0.6 })
  }, [map, lat, lng])
  return null
}

function Legend() {
  const dot = (color: string, label: string) => (
    <span className="flex items-center gap-1">
      <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  )
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
      {dot(SEVERITY_COLOR.ok, 'OK')}
      {dot(SEVERITY_COLOR.low, 'Low')}
      {dot(SEVERITY_COLOR.critical, 'Critical')}
      {dot(DEPOT_COLOR, 'Depot')}
      {dot(OFFLINE_COLOR, 'Camera offline')}
      <span>- - pending</span>
      <span>── en route</span>
    </div>
  )
}

export function MapPanel({ className = '' }: { className?: string }) {
  const snapshot = useDashboardStore((s) => s.snapshot)
  const derived = useDashboardStore((s) => s.derived)
  const selectedSiteId = useDashboardStore((s) => s.selectedSiteId)
  const selectSite = useDashboardStore((s) => s.selectSite)

  const locations = snapshot?.locations ?? []
  const byId = new Map(locations.map((l) => [l.id, l]))
  const rows = new Map((derived?.rows ?? []).map((r) => [r.location.id, r]))
  const activeDispatches = (snapshot?.dispatches ?? []).filter((d) => d.status === 'pending' || d.status === 'en_route')
  const textPins = (snapshot?.messages ?? []).filter(
    (m) => m.direction === 'in' && m.parsed?.lat !== undefined && m.parsed?.lng !== undefined,
  )

  const ringFor = (id: string, base: string) =>
    id === selectedSiteId ? { color: '#0f172a', weight: 4 } : { color: base, weight: 2 }

  return (
    <Panel title="Map" actions={<Legend />} className={className}>
      <MapContainer center={CENTER} zoom={12} className="h-full min-h-[300px] w-full">
        <FollowSelection target={selectedSiteId ? byId.get(selectedSiteId) : undefined} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {activeDispatches.map((d) => {
          const from = byId.get(d.from_site)
          const to = byId.get(d.to_site)
          if (!from || !to) return null
          return (
            <Polyline
              key={d.dispatch_id}
              positions={[pos(from), pos(to)]}
              pathOptions={{ color: DEPOT_COLOR, weight: 3, dashArray: d.status === 'pending' ? '8 8' : undefined }}
            >
              <Tooltip sticky>
                {d.dispatch_id}: {d.status === 'pending' ? 'pending' : `en route, ETA ${d.eta_minutes} min`}
              </Tooltip>
            </Polyline>
          )
        })}

        {locations
          .filter((l) => l.kind === 'incident')
          .map((l) => (
            <Circle key={l.id} center={pos(l)} radius={700} pathOptions={{ color: INCIDENT_COLOR, fillOpacity: 0.15 }}>
              <Tooltip>{l.name}</Tooltip>
            </Circle>
          ))}

        {locations
          .filter((l) => l.kind === 'depot')
          .map((l) => {
            const stock = derived?.stock[l.id]
            return (
              <CircleMarker
                key={l.id}
                center={pos(l)}
                radius={9}
                pathOptions={{ ...ringFor(l.id, DEPOT_COLOR), fillColor: DEPOT_COLOR, fillOpacity: 0.9 }}
                eventHandlers={{ click: () => selectSite(l.id) }}
              >
                <Popup>
                  <strong>{l.name}</strong>
                  {stock && (
                    <ul className="mt-1">
                      {ITEM_TYPES.map((item) => (
                        <li key={item}>
                          {ITEM_LABEL[item]}: {stock[item].toLocaleString()}
                        </li>
                      ))}
                    </ul>
                  )}
                </Popup>
              </CircleMarker>
            )
          })}

        {locations
          .filter((l) => l.kind === 'shelter')
          .map((l) => {
            const row = rows.get(l.id)
            const severity = row?.severity ?? 'ok'
            const offline = (row?.offlineCameras ?? 0) > 0
            return (
              <CircleMarker
                key={l.id}
                center={pos(l)}
                radius={12}
                pathOptions={{
                  ...ringFor(l.id, offline ? OFFLINE_COLOR : '#ffffff'),
                  dashArray: offline ? '4 4' : undefined,
                  fillColor: SEVERITY_COLOR[severity],
                  fillOpacity: offline ? 0.45 : 0.9,
                }}
                eventHandlers={{ click: () => selectSite(l.id) }}
              >
                <Tooltip direction="top" offset={[0, -10]}>
                  {l.name}
                </Tooltip>
                <Popup>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <strong>{l.name}</strong>
                      <SeverityBadge severity={severity} />
                    </div>
                    {row && (
                      <>
                        <div>
                          {row.headcount} people{l.capacity ? ` / ${l.capacity} capacity` : ''}
                        </div>
                        {offline && <div className="text-slate-500">Camera offline: headcount may be stale</div>}
                        <table className="text-xs">
                          <tbody>
                            {ITEM_TYPES.map((item) => (
                              <tr key={item} className={row.items[item].shortfall > 0 ? 'text-red-700' : ''}>
                                <td className="pr-2">{ITEM_LABEL[item]}</td>
                                <td className="pr-1 text-right">{row.items[item].onHand.toLocaleString()}</td>
                                <td>/ {row.items[item].need.toLocaleString()}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </>
                    )}
                  </div>
                </Popup>
              </CircleMarker>
            )
          })}

        {textPins.map((m) => (
          <CircleMarker
            key={m.message_id}
            center={[m.parsed!.lat!, m.parsed!.lng!]}
            radius={5}
            pathOptions={{
              color: m.needs_review ? '#000000' : '#ffffff',
              weight: m.needs_review ? 2 : 1,
              fillColor: URGENCY_COLOR[m.parsed!.urgency],
              fillOpacity: 1,
            }}
          >
            <Popup>
              <div className="max-w-[220px]">
                <div className="text-xs font-semibold uppercase">{m.parsed!.urgency} text request</div>
                <div>{m.body}</div>
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </Panel>
  )
}
