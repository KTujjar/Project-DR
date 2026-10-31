import { useEffect } from 'react'
import { AlertsBar } from './components/AlertsBar/AlertsBar'
import { DispatchQueue } from './components/DispatchQueue/DispatchQueue'
import { MapPanel } from './components/MapPanel/MapPanel'
import { NeedSupplyPanel } from './components/NeedSupplyPanel/NeedSupplyPanel'
import { Panel } from './components/Panel'
import { TextFeed } from './components/TextFeed/TextFeed'
import { useDashboardStore } from './store/useDashboardStore'

function Placeholder({ label }: { label: string }) {
  return <p className="p-3 text-sm text-slate-400">{label} coming soon</p>
}

export default function App() {
  const startPolling = useDashboardStore((s) => s.startPolling)

  useEffect(() => startPolling(), [startPolling])

  return (
    <div className="flex min-h-full flex-col gap-2 p-2 lg:h-full">
      <AlertsBar />

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-2 lg:grid-cols-3 lg:grid-rows-[3fr_2fr]">
        <MapPanel className="min-h-[360px] lg:col-span-2" />
        <div className="grid min-h-0 grid-rows-2 gap-2">
          <NeedSupplyPanel />
          <DispatchQueue />
        </div>
        <Panel title="Inventory">
          <Placeholder label="Inventory" />
        </Panel>
        <TextFeed />
        <Panel title="Cameras">
          <Placeholder label="Cameras" />
        </Panel>
      </main>
    </div>
  )
}
