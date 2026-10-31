import { useState, type FormEvent } from 'react'
import { maskPhone } from '../../logic/format'
import { useDashboardStore } from '../../store/useDashboardStore'
import type { TextMessage } from '../../types/schemas'
import { ITEM_LABEL, timeAgo } from '../labels'
import { Panel } from '../Panel'
import { RelayTextFeed } from './RelayTextFeed'

const NO_MESSAGES: TextMessage[] = []

const URGENCY_CLASS = {
  low: 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200',
  medium: 'bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200',
  high: 'bg-orange-100 dark:bg-orange-900 text-orange-800 dark:text-orange-200',
  critical: 'bg-red-600 text-white',
}

function ParsedFields({ m, siteName }: { m: TextMessage; siteName: (id: string) => string }) {
  if (m.direction === 'out') return <span className="text-slate-400">Outgoing reply</span>
  if (!m.parsed) return <span className="font-semibold text-red-700 dark:text-red-400">Could not parse</span>
  const p = m.parsed
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-2">
      <dt className="text-slate-400">Intent</dt>
      <dd>{p.intent.replace('_', ' ')}</dd>
      {p.site_id && (
        <>
          <dt className="text-slate-400">Site</dt>
          <dd>{siteName(p.site_id)}</dd>
        </>
      )}
      {!p.site_id && p.lat !== undefined && (
        <>
          <dt className="text-slate-400">Location</dt>
          <dd>
            {p.lat.toFixed(3)}, {p.lng?.toFixed(3)}
          </dd>
        </>
      )}
      {p.item && (
        <>
          <dt className="text-slate-400">Item</dt>
          <dd>
            {p.quantity !== undefined ? `${p.quantity} ` : ''}
            {ITEM_LABEL[p.item]}
          </dd>
        </>
      )}
      <dt className="text-slate-400">Conf.</dt>
      <dd>{Math.round(p.confidence * 100)}%</dd>
    </dl>
  )
}

export function TextFeed() {
  return (import.meta.env.VITE_TEXT_SOURCE ?? 'relay') === 'relay' ? <RelayTextFeed /> : <SnapshotTextFeed />
}

function SnapshotTextFeed() {
  const messages = useDashboardStore((s) => s.snapshot?.messages ?? NO_MESSAGES)
  const locations = useDashboardStore((s) => s.snapshot?.locations)
  const selectedSiteId = useDashboardStore((s) => s.selectedSiteId)
  const selectSite = useDashboardStore((s) => s.selectSite)
  const sendText = useDashboardStore((s) => s.sendText)
  const [replyTo, setReplyTo] = useState<TextMessage | null>(null)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)

  const siteName = (id: string) => locations?.find((l) => l.id === id)?.name ?? id
  const newestFirst = [...messages].sort((a, b) => b.timestamp.localeCompare(a.timestamp))

  const onSelect = (m: TextMessage) => {
    if (m.parsed?.site_id) selectSite(m.parsed.site_id)
    if (m.direction === 'in') setReplyTo(m)
  }

  const onSend = async (e: FormEvent) => {
    e.preventDefault()
    if (!replyTo || !draft.trim()) return
    setSending(true)
    try {
      await sendText(replyTo.phone, draft.trim())
      setDraft('')
    } finally {
      setSending(false)
    }
  }

  return (
    <Panel title="Text Feed">
      <div className="flex h-full flex-col">
        <ul className="min-h-0 flex-1 divide-y divide-slate-100 dark:divide-slate-800 overflow-auto">
          {newestFirst.length === 0 && <li className="p-3 text-sm text-slate-400">No texts yet.</li>}
          {newestFirst.map((m) => {
            const selected = (m.parsed?.site_id && m.parsed.site_id === selectedSiteId) || replyTo?.message_id === m.message_id
            const tone = m.needs_review
              ? 'bg-red-50 border-l-4 border-red-500'
              : m.direction === 'out'
                ? 'bg-sky-50 border-l-4 border-sky-400'
                : 'border-l-4 border-transparent'
            return (
              <li
                key={m.message_id}
                onClick={() => onSelect(m)}
                className={`grid cursor-pointer grid-cols-[3fr_2fr] gap-2 px-2 py-1.5 text-xs ${tone} ${
                  selected ? 'ring-2 ring-inset ring-sky-400' : ''
                }`}
              >
                <div>
                  <div className="mb-0.5 flex items-center gap-1.5 text-slate-500 dark:text-slate-400">
                    <span>{m.direction === 'in' ? '←' : '→'}</span>
                    <span className="font-mono">{maskPhone(m.phone)}</span>
                    <span>{timeAgo(m.timestamp)}</span>
                    {m.parsed && (
                      <span className={`rounded px-1 font-semibold ${URGENCY_CLASS[m.parsed.urgency]}`}>
                        {m.parsed.urgency}
                      </span>
                    )}
                    {m.needs_review && <span className="rounded bg-red-600 px-1 font-semibold text-white">review</span>}
                  </div>
                  <p className="text-slate-900 dark:text-slate-100">{m.body}</p>
                </div>
                <div className="border-l border-slate-200 dark:border-slate-700 pl-2">
                  <ParsedFields m={m} siteName={siteName} />
                </div>
              </li>
            )
          })}
        </ul>

        <form onSubmit={onSend} className="flex gap-1 border-t border-slate-200 dark:border-slate-700 p-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={!replyTo || sending}
            placeholder={replyTo ? `Reply to ${maskPhone(replyTo.phone)}` : 'Click a message to reply'}
            className="min-w-0 flex-1 rounded border border-slate-300 dark:border-slate-600 px-2 py-1 text-xs bg-white dark:bg-slate-800 disabled:bg-slate-50 dark:disabled:bg-slate-900"
          />
          <button
            type="submit"
            disabled={!replyTo || !draft.trim() || sending}
            className="rounded bg-sky-600 px-3 py-1 text-xs font-medium text-white hover:bg-sky-700 disabled:opacity-40"
          >
            Send
          </button>
        </form>
      </div>
    </Panel>
  )
}
