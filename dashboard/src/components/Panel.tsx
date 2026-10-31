import type { ReactNode } from 'react'

interface PanelProps {
  title: string
  actions?: ReactNode
  className?: string
  children?: ReactNode
}

// Titled card used by every dashboard panel. The body scrolls, the page does not.
export function Panel({ title, actions, className = '', children }: PanelProps) {
  return (
    <section className={`flex min-h-0 flex-col rounded-lg border border-slate-200 bg-white shadow-sm ${className}`}>
      <header className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">{title}</h2>
        {actions}
      </header>
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
    </section>
  )
}
