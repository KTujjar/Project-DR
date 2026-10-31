import { useEffect } from 'react'
import { AlertsBar } from './components/AlertsBar/AlertsBar'
import { CameraGrid } from './components/CameraGrid/CameraGrid'
import { DispatchQueue } from './components/DispatchQueue/DispatchQueue'
import { InventoryPanel } from './components/InventoryPanel/InventoryPanel'
import { MapPanel } from './components/MapPanel/MapPanel'
import { NeedSupplyPanel } from './components/NeedSupplyPanel/NeedSupplyPanel'
import { TextFeed } from './components/TextFeed/TextFeed'
import { useDashboardStore } from './store/useDashboardStore'

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
        <InventoryPanel />
        <TextFeed />
        <CameraGrid />
      </main>
    </div>
  )
}
