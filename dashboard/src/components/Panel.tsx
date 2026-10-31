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
    <section className={`flex min-h-0 min-w-0 flex-col rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-sm ${className}`}>
      <header className="flex items-center justify-between border-b border-slate-200 dark:border-slate-700 px-3 py-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">{title}</h2>
        {actions}
      </header>
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
    </section>
  )
}

