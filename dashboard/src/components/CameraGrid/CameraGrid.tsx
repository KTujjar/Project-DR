import { useEffect, useState } from 'react'
import { useDashboardStore } from '../../store/useDashboardStore'
import type { CameraFeed, PeopleCount } from '../../types/schemas'
import { timeAgo } from '../labels'
import { Panel } from '../Panel'

interface TileProps {
  camera: CameraFeed
  count?: PeopleCount
  siteName: string
  large?: boolean
}

function CameraView({ camera, count, siteName, large = false }: TileProps) {
  // Prefer the live MJPEG stream (smooth video); snapshots only change on each 3 s poll.
  const src = camera.online ? (camera.stream_url ?? camera.snapshot_url) : undefined
  return (
    <div className={`relative overflow-hidden rounded bg-slate-800 ${large ? 'aspect-video w-full' : 'h-full'} ${camera.online ? '' : 'grayscale'}`}>
      {src ? (
        <img src={src} alt={`${camera.camera_id} feed`} className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full items-center justify-center text-3xl text-slate-600">{camera.online ? '🎥' : '⛔'}</div>
      )}
      <div className="absolute left-1 top-1 rounded bg-black/60 px-1.5 text-xs text-white">
        {camera.camera_id} · {siteName}
      </div>
      <div
        className={`absolute right-1 top-1 rounded px-1.5 text-xs font-semibold ${
          camera.online ? 'bg-green-600 text-white' : 'bg-slate-500 text-white'
        }`}
      >
        {camera.online ? '● Live' : 'Offline'}
      </div>
      {count && (
        <div className={`absolute bottom-1 left-1 rounded bg-black/70 px-1.5 text-white ${large ? 'text-lg' : 'text-sm'}`}>
          <span className="font-bold">{count.people_count}</span> people
          <span className="ml-1 text-xs text-slate-300">{Math.round(count.confidence * 100)}% conf.</span>
        </div>
      )}
      <div className="absolute bottom-1 right-1 rounded bg-black/60 px-1.5 text-xs text-slate-200">
        {timeAgo(camera.last_frame_at)}
      </div>
    </div>
  )
}

export function CameraGrid() {
  const snapshot = useDashboardStore((s) => s.snapshot)
  const selectedSiteId = useDashboardStore((s) => s.selectedSiteId)
  const selectSite = useDashboardStore((s) => s.selectSite)
  const [enlarged, setEnlarged] = useState<string | null>(null)

  useEffect(() => {
    if (!enlarged) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setEnlarged(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enlarged])

  const cameras = snapshot?.cameras ?? []
  const siteName = (id: string) => snapshot?.locations.find((l) => l.id === id)?.name ?? id
  const latestCount = (cameraId: string) =>
    (snapshot?.peopleCounts ?? [])
      .filter((c) => c.camera_id === cameraId)
      .reduce<PeopleCount | undefined>((best, c) => (!best || c.timestamp > best.timestamp ? c : best), undefined)
  const enlargedCam = cameras.find((c) => c.camera_id === enlarged)

  return (
    <Panel title="Cameras">
      <div className="grid h-full auto-rows-fr grid-cols-2 gap-2 p-2">
        {cameras.length === 0 && <p className="col-span-2 p-1 text-sm text-slate-400">No cameras connected.</p>}
        {cameras.map((cam) => (
          <button
            key={cam.camera_id}
            type="button"
            onClick={() => {
              selectSite(cam.site_id)
              setEnlarged(cam.camera_id)
            }}
            className={`min-h-[90px] rounded text-left ${cam.site_id === selectedSiteId ? 'ring-2 ring-sky-400 ring-offset-1' : ''}`}
          >
            <CameraView camera={cam} count={latestCount(cam.camera_id)} siteName={siteName(cam.site_id)} />
          </button>
        ))}
      </div>

      {enlargedCam && (
        <div
          className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70 p-4"
          onClick={() => setEnlarged(null)}
          role="dialog"
          aria-label={`Camera ${enlargedCam.camera_id}`}
        >
          <div className="w-full max-w-3xl" onClick={(e) => e.stopPropagation()}>
            <CameraView
              camera={enlargedCam}
              count={latestCount(enlargedCam.camera_id)}
              siteName={siteName(enlargedCam.site_id)}
              large
            />
            <button
              type="button"
              onClick={() => setEnlarged(null)}
              className="mt-2 rounded bg-white px-3 py-1 text-sm font-medium text-slate-800"
            >
              Close (Esc)
            </button>
          </div>
        </div>
      )}
    </Panel>
  )
}
