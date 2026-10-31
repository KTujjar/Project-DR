import { useEffect } from 'react'
import { AlertsBar } from './components/AlertsBar/AlertsBar'
import { CameraGrid } from './components/CameraGrid/CameraGrid'
import { DispatchQueue } from './components/DispatchQueue/DispatchQueue'
import { InventoryPanel } from './components/InventoryPanel/InventoryPanel'
import { MapPanel } from './components/MapPanel/MapPanel'
import { NeedSupplyPanel } from './components/NeedSupplyPanel/NeedSupplyPanel'
import { TextFeed } from './components/TextFeed/TextFeed'
import { triggerDemoEvent } from './data/sources'
import { useDashboardStore } from './store/useDashboardStore'
import { useCommunityStore } from './store/useCommunityStore'
import { CommunityIntake } from './components/TextFeed/CommunityIntake'

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-slate-200 dark:bg-slate-800 ${className}`} />
}

export default function App() {
  return window.location.pathname === '/community' ? <CommunityIntake /> : <CoordinatorDashboard />
}

function CoordinatorDashboard() {
  const startPolling = useDashboardStore((s) => s.startPolling)
  const startCommunityPolling = useCommunityStore((s) => s.startPolling)
  const loaded = useDashboardStore((s) => s.snapshot !== null)

  useEffect(() => startPolling(), [startPolling])
  useEffect(() => (import.meta.env.VITE_TEXT_SOURCE ?? 'relay') === 'relay' ? startCommunityPolling() : undefined, [startCommunityPolling])

  // Esc clears the selected site. Shift+D stages the demo event (mock data only).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement || e.target instanceof HTMLTextAreaElement
      if (e.key === 'Escape') useDashboardStore.getState().selectSite(null)
      if (e.key.toLowerCase() === 'd' && e.shiftKey && !typing && triggerDemoEvent) {
        triggerDemoEvent()
        void useDashboardStore.getState().refresh()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="flex min-h-full flex-col gap-2 p-2 lg:h-full">
      <AlertsBar />

      {(import.meta.env.VITE_DATA_SOURCE ?? 'mock') === 'mock' && (
        <p className="px-1 text-[10px] text-slate-500 dark:text-slate-400">Simulation data: map, inventory, dispatch, and camera panels. The community text panel shows its own connection status.</p>
      )}

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-2 lg:grid-cols-[repeat(3,minmax(0,1fr))] lg:grid-rows-[3fr_2fr]">
        {loaded ? (
          <>
            <MapPanel className="min-h-[360px] lg:col-span-2" />
            <div className="grid min-h-0 min-w-0 gap-2 lg:grid-rows-[1.15fr_1fr]">
              <NeedSupplyPanel />
              <DispatchQueue />
            </div>
            <InventoryPanel />
            <TextFeed />
            <CameraGrid />
          </>
        ) : (
          <>
            <Skeleton className="min-h-[360px] lg:col-span-2" />
            <div className="grid gap-2 lg:grid-rows-2">
              <Skeleton className="min-h-[160px]" />
              <Skeleton className="min-h-[160px]" />
            </div>
            <Skeleton className="min-h-[200px]" />
            <TextFeed />
            <Skeleton className="min-h-[200px]" />
          </>
        )}
      </main>
    </div>
  )
}
