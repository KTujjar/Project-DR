import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useDashboardStore } from '../../store/useDashboardStore'
import { ITEM_TYPES, type ItemType } from '../../types/schemas'
import { ITEM_LABEL, timeAgo } from '../labels'
import { Panel } from '../Panel'

interface BarRow {
  site_id: string
  name: string
  quantity: number
  threshold: number | null // 24h need for shelters; depots have none
  updated: string | null
}

const needTickBeyondBar = (row: BarRow) => row.threshold !== null && row.threshold > row.quantity

// Draws only a vertical tick at the end of the (invisible) threshold bar.
function ThresholdTick(props: { x?: number; y?: number; width?: number; height?: number; payload?: BarRow }) {
  const { x = 0, y = 0, width = 0, height = 0, payload } = props
  if (!payload || payload.threshold === null) return null
  const tx = x + width
  return <line x1={tx} x2={tx} y1={y - 3} y2={y + height + 3} stroke="var(--viz-threshold)" strokeWidth={2} />
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: BarRow }[] }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  const short = needTickBeyondBar(row)
  return (
    <div className="rounded border border-slate-200 bg-white px-2 py-1 text-xs shadow">
      <div className="font-semibold">{row.name}</div>
      <div>On hand: {row.quantity.toLocaleString()}</div>
      {row.threshold !== null && <div>24h need: {row.threshold.toLocaleString()}</div>}
      {short && <div className="font-semibold text-red-700">⚠ Below need</div>}
      {row.updated && <div className="text-slate-500">Updated {timeAgo(row.updated)}</div>}
    </div>
  )
}

export function InventoryPanel() {
  const snapshot = useDashboardStore((s) => s.snapshot)
  const derived = useDashboardStore((s) => s.derived)
  const selectedSiteId = useDashboardStore((s) => s.selectedSiteId)
  const selectSite = useDashboardStore((s) => s.selectSite)
  const [item, setItem] = useState<ItemType>('water_L')

  const sites = (snapshot?.locations ?? []).filter((l) => l.kind !== 'incident')
  const data: BarRow[] = sites.map((l) => {
    const row = derived?.rows.find((r) => r.location.id === l.id)
    const records = (snapshot?.inventory ?? []).filter((r) => r.site_id === l.id && r.item === item)
    const newest = records.reduce<string | null>((t, r) => (t === null || r.timestamp > t ? r.timestamp : t), null)
    return {
      site_id: l.id,
      name: l.name,
      quantity: derived?.stock[l.id]?.[item] ?? 0,
      threshold: row ? row.items[item].need : null,
      updated: newest,
    }
  })
  const newestUpdate = data.reduce<string | null>((t, r) => (r.updated && (!t || r.updated > t) ? r.updated : t), null)

  const filter = (
    <select
      value={item}
      onChange={(e) => setItem(e.target.value as ItemType)}
      className="rounded border border-slate-300 px-1 py-0.5 text-xs"
      aria-label="Filter inventory by item"
    >
      {ITEM_TYPES.map((i) => (
        <option key={i} value={i}>
          {ITEM_LABEL[i]}
        </option>
      ))}
    </select>
  )

  return (
    <Panel title="Inventory" actions={filter}>
      <div className="flex h-full min-h-[200px] flex-col">
        <div className="min-h-0 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 8, right: 48, bottom: 0, left: 8 }} barGap={-14}>
              <CartesianGrid horizontal={false} stroke="var(--viz-grid)" />
              <XAxis type="number" tick={{ fontSize: 11, fill: 'var(--viz-text-secondary)' }} stroke="var(--viz-grid)" />
              <YAxis
                type="category"
                dataKey="name"
                width={130}
                tick={{ fontSize: 11, fill: 'var(--viz-text-secondary)' }}
                stroke="var(--viz-grid)"
              />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: 'rgba(148,163,184,0.15)' }} />
              <Bar
                dataKey="quantity"
                barSize={14}
                radius={[0, 4, 4, 0]}
                isAnimationActive={false}
                onClick={(row: BarRow) => selectSite(row.site_id)}
                className="cursor-pointer"
              >
                {data.map((row) => (
                  <Cell
                    key={row.site_id}
                    fill={needTickBeyondBar(row) ? 'var(--viz-critical)' : 'var(--viz-series-1)'}
                    stroke={row.site_id === selectedSiteId ? 'var(--viz-threshold)' : 'none'}
                    strokeWidth={2}
                  />
                ))}
                <LabelList
                  position="right"
                  fontSize={11}
                  fill="var(--viz-text-secondary)"
                  valueAccessor={(entry: { payload: BarRow }) => (needTickBeyondBar(entry.payload) ? '' : entry.payload.quantity.toLocaleString())}
                />
              </Bar>
              <Bar dataKey="threshold" barSize={14} shape={<ThresholdTick />} isAnimationActive={false}>
                {/* When the need tick sits past the bar, put the value after the tick so they don't collide. */}
                <LabelList
                  position="right"
                  fontSize={11}
                  fill="var(--viz-text-secondary)"
                  valueAccessor={(entry: { payload: BarRow }) => (needTickBeyondBar(entry.payload) ? entry.payload.quantity.toLocaleString() : '')}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="flex justify-between border-t border-slate-100 px-3 py-1 text-xs text-slate-500">
          <span>
            <span className="mr-1 inline-block h-2 w-2 bg-[var(--viz-series-1)]" />
            On hand
            <span className="ml-3 mr-1 inline-block h-2 w-2 bg-[var(--viz-critical)]" />⚠ below need
            <span className="ml-3 mr-1 inline-block h-3 w-0.5 bg-[var(--viz-threshold)] align-middle" />
            24h need
          </span>
          {newestUpdate && <span>Updated {timeAgo(newestUpdate)}</span>}
        </p>
      </div>
    </Panel>
  )
}
