import { Panel } from './components/Panel'

function Placeholder({ label }: { label: string }) {
  return <p className="p-3 text-sm text-slate-400">{label} coming soon</p>
}

export default function App() {
  return (
    <div className="flex min-h-full flex-col gap-2 p-2 lg:h-full">
      <header className="rounded-lg bg-slate-900 px-3 py-2 text-white">
        <span className="font-semibold">Project-DR</span> <span className="text-slate-400">Coordinator Dashboard</span>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-2 lg:grid-cols-3 lg:grid-rows-[3fr_2fr]">
        <Panel title="Map" className="min-h-[360px] lg:col-span-2">
          <Placeholder label="Map" />
        </Panel>
        <div className="grid min-h-0 grid-rows-2 gap-2">
          <Panel title="Need vs Supply">
            <Placeholder label="Need vs supply" />
          </Panel>
          <Panel title="Dispatch Queue">
            <Placeholder label="Dispatch queue" />
          </Panel>
        </div>
        <Panel title="Inventory">
          <Placeholder label="Inventory" />
        </Panel>
        <Panel title="Text Feed">
          <Placeholder label="Text feed" />
        </Panel>
        <Panel title="Cameras">
          <Placeholder label="Cameras" />
        </Panel>
      </main>
    </div>
  )
}
