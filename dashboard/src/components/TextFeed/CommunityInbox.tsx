import { useEffect, useState } from 'react'
import type { RelayCase, ThreadMessage } from '../../data/relayTextApi'
import { communityApi, useCommunityStore } from '../../store/useCommunityStore'
import { useDashboardStore } from '../../store/useDashboardStore'
import { Panel } from '../Panel'

const field = 'w-full rounded border border-slate-600 bg-slate-900 px-2 py-1.5 text-xs text-slate-100 placeholder:text-slate-500 focus:border-sky-500 focus:outline-none'
const statusLabel = (entry: RelayCase) => entry.review_status === 'needs_information' ? 'Awaiting community' : entry.reply_sent_at ? 'Replied' : 'Needs review'
const pending = (entry: RelayCase) => !entry.reply_sent_at

function maskedContact(contact: string) {
  const digits = contact.replace(/\D/g, '')
  if (digits.length >= 7) return `••• ${digits.slice(-4)}`
  if (contact.includes('@')) return `${contact.slice(0, 2)}•••@${contact.split('@')[1]}`
  return contact ? 'Contact provided' : 'Web conversation'
}

function ConversationDrawer({ entry }: { entry: RelayCase }) {
  const select = useCommunityStore((state) => state.select)
  const upsert = useCommunityStore((state) => state.upsert)
  const refresh = useCommunityStore((state) => state.refresh)
  const locations = useDashboardStore((state) => state.snapshot?.locations)
  const selectSite = useDashboardStore((state) => state.selectSite)
  const [messages, setMessages] = useState<ThreadMessage[]>([])
  const [editedDraft, setEditedDraft] = useState<string | null>(null)
  const draft = editedDraft ?? entry.suggested_reply ?? ''
  const [reviewedId, setReviewedId] = useState(entry.id)
  const [editedAwaitingInformation, setEditedAwaitingInformation] = useState<boolean | null>(null)
  const awaitingInformation = editedAwaitingInformation ?? (entry.clarifying_questions.length > 0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const p = entry.interpretation
  const location = p.location || entry.reported_location || 'Location not provided'
  const mapSite = locations?.find((site) => site.name.trim().toLowerCase() === location.trim().toLowerCase())
  const newerMessage = reviewedId !== entry.id

  useEffect(() => {
    let active = true
    void communityApi.thread(entry.conversation_id).then((thread) => { if (active) setMessages(thread) }).catch(() => { if (active) setError('The conversation could not be loaded.') })
    return () => { active = false }
  }, [entry.conversation_id, entry.updated_at])

  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') select(null) }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [select])

  const sendReply = async () => {
    if (busy || !draft.trim() || newerMessage) return
    setBusy(true)
    setError('')
    try {
      upsert(await communityApi.reply(reviewedId, draft.trim(), awaitingInformation))
      setMessages(await communityApi.thread(entry.conversation_id))
      setEditedDraft(null); setEditedAwaitingInformation(null)
      await refresh()
    } catch (error) { setError(error instanceof Error ? error.message : 'The reply could not be posted.') }
    finally { setBusy(false) }
  }

  return <div className="fixed inset-0 z-[1000] flex justify-end bg-black/55" role="presentation">
    <button type="button" className="absolute inset-0 cursor-default" aria-label="Close conversation" onClick={() => select(null)} />
    <section role="dialog" aria-modal="true" aria-label={`Conversation with ${entry.sender_name}`} className="relative flex h-full w-full max-w-xl flex-col border-l border-slate-700 bg-slate-950 text-slate-100 shadow-2xl">
      <header className="flex items-start justify-between gap-3 border-b border-slate-700 p-4"><div><p className="text-[10px] uppercase tracking-wider text-slate-500">{entry.id} · {entry.channel === 'demo' ? 'Demo scenario' : 'Community web form'}</p><h2 className="mt-1 text-lg font-semibold">{entry.sender_name || 'Community member'}</h2><p className="mt-1 text-xs text-slate-400">{location} · {maskedContact(entry.contact ?? '')}</p></div><button type="button" onClick={() => select(null)} className="rounded px-2 py-1 text-slate-400 hover:bg-slate-800" aria-label="Close">✕</button></header>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <section className="rounded-lg border border-slate-700 bg-slate-900 p-3"><div className="mb-2 flex items-center justify-between gap-2"><h3 className="text-xs font-semibold uppercase tracking-wide text-sky-300">Responder brief</h3><span className="rounded bg-amber-950 px-2 py-0.5 text-[10px] text-amber-200">{statusLabel(entry)}</span></div><p className="text-sm">{p.responder_summary}</p><dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-xs"><dt className="text-slate-500">Reported location</dt><dd>{location}</dd>{p.needs.map((need, index) => <div key={index} className="contents"><dt className="text-slate-500">Requested</dt><dd>{need.quantity ?? 'Quantity unknown'} {need.unit ?? '(unit unknown)'} · {need.item ?? 'item unknown'}</dd></div>)}{p.access_barriers.length > 0 && <><dt className="text-slate-500">Access barrier</dt><dd>{p.access_barriers.join('; ')}</dd></>}{p.delivery_report && <><dt className="text-slate-500">Delivery report</dt><dd>{p.delivery_report}</dd></>}</dl>{mapSite && <button type="button" className="mt-3 text-xs text-sky-400" onClick={() => { selectSite(mapSite.id); select(null) }}>Show reported site on map →</button>}<p className="mt-3 text-[10px] text-slate-500">Community reports are unverified. This review does not change stock or confirm a delivery.</p></section>
        {entry.processing_status === 'processing' && <p className="text-xs text-sky-300">Preparing an AI draft… You can review the original message and write a reply now.</p>}
        {entry.analysis_error && <div className="rounded border border-amber-900 bg-amber-950/40 p-3 text-xs text-amber-200"><p>AI draft unavailable. The original message is saved for manual review.</p><details className="mt-2"><summary className="cursor-pointer">Connection details</summary><p className="mt-1 break-words">{entry.analysis_error}</p></details>{!entry.reply_sent_at && <button type="button" className="mt-2 underline" onClick={() => { void communityApi.retry(entry.id).then(upsert).catch(() => setError('Could not retry the AI draft.')) }}>Retry AI draft</button>}</div>}
        {p.evidence.length > 0 && <details className="rounded border border-slate-700 p-3"><summary className="cursor-pointer text-xs text-slate-300">Supporting message quotes</summary>{p.evidence.map((evidence, index) => <blockquote key={index} className="mt-2 border-l-2 border-sky-800 pl-2 text-xs text-slate-400">“{evidence.quote}”</blockquote>)}</details>}
        {entry.sources.length > 0 && <details className="rounded border border-slate-700 p-3"><summary className="cursor-pointer text-xs text-slate-300">Information used for the draft reply</summary>{entry.sources.map((source) => <div key={source.id} className="mt-2 text-xs"><p className="font-medium">{source.title}</p><p className="mt-1 text-slate-400">{source.answer}</p><p className="text-[10px] text-slate-500">{source.updated_at}</p></div>)}</details>}
        <section><h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Conversation</h3><div className="space-y-2">{messages.map((message) => <article key={message.id} className={`rounded-lg p-3 ${message.role === 'user' ? 'bg-slate-800' : 'border border-slate-800 bg-slate-900/50'}`}><div className="mb-1 flex justify-between gap-2 text-[10px] text-slate-500"><span>{message.role === 'user' ? entry.sender_name : message.kind === 'acknowledgment' ? 'Automatic receipt' : 'Responder'}</span><time>{new Date(message.created_at).toLocaleTimeString()}</time></div><p className="whitespace-pre-wrap break-words text-xs">{message.text}</p></article>)}</div></section>
      </div>
      <footer className="space-y-2 border-t border-slate-700 bg-slate-900 p-4">
        {newerMessage && <div className="rounded bg-amber-950 p-2 text-xs text-amber-200">A new community message arrived. Review it before sending.<button type="button" className="ml-1 underline" onClick={() => { setReviewedId(entry.id); setEditedDraft(entry.suggested_reply ?? ''); setEditedDraft(null); setEditedAwaitingInformation(null) }}>Load latest draft</button></div>}
        {entry.reply_sent_at ? <div className="text-xs text-emerald-300"><p className="font-medium">Reply posted to the community web conversation</p><p className="mt-1 whitespace-pre-wrap text-slate-300">{entry.reply_text}</p></div> : <><label className="block text-xs font-medium text-slate-300" htmlFor="reviewed-reply">Review and edit the suggested reply</label><textarea id="reviewed-reply" rows={4} maxLength={4000} value={draft} onChange={(event) => { setEditedDraft(event.target.value);  }} className={field} placeholder="Write a response or a precise clarification question…" /><label className="flex items-center gap-2 text-[11px] text-slate-400"><input type="checkbox" checked={awaitingInformation} onChange={(event) => { setEditedAwaitingInformation(event.target.checked);  }} />Ask the community for more information</label><div className="flex items-center justify-between gap-3"><p className="text-[10px] text-slate-500">Posts to the web conversation. SMS is not connected.</p><button type="button" disabled={busy || !draft.trim() || newerMessage} onClick={() => { void sendReply() }} className="shrink-0 rounded bg-sky-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">{busy ? 'Posting…' : 'Approve & post reply'}</button></div></>}
        {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
      </footer>
    </section>
  </div>
}

export function CommunityInbox() {
  const items = useCommunityStore((state) => state.items)
  const health = useCommunityStore((state) => state.health)
  const error = useCommunityStore((state) => state.error)
  const select = useCommunityStore((state) => state.select)
  const selectedId = useCommunityStore((state) => state.selectedConversationId)
  const refresh = useCommunityStore((state) => state.refresh)
  const [filter, setFilter] = useState('new')
  const [query, setQuery] = useState('')
  const [loadingDemo, setLoadingDemo] = useState(false)
  const [demoError, setDemoError] = useState('')
  const active = items.find((item) => item.conversation_id === selectedId)
  const newCount = items.filter(pending).length
  const shown = items.filter((item) => (filter !== 'new' || pending(item))
    && `${item.sender_name} ${item.reported_location} ${item.interpretation.location} ${item.original_message}`.toLowerCase().includes(query.toLowerCase()))

  const loadDemo = async () => {
    if (!health || loadingDemo) return
    setLoadingDemo(true)
    setDemoError('')
    try {
      const examples = [0, 1, 4]
      const senders = ['Hanover shelter volunteer', 'Norwich resident', 'Hanover supply runner']
      for (let n = 0; n < examples.length; n++) await communityApi.intake({
        conversation_id: `demo-${crypto.randomUUID()}`, sender_name: senders[n],
        text: health.examples[examples[n]].text, channel: 'demo',
      })
      setFilter('new')
      await refresh()
    } catch (error) { setDemoError(error instanceof Error ? error.message : 'Could not load demonstration messages.') }
    finally { setLoadingDemo(false) }
  }

  return <>
    <Panel title="Community inbox" actions={<span className={`rounded px-1.5 py-0.5 text-[10px] ${error ? 'bg-red-950 text-red-200' : 'bg-emerald-950 text-emerald-200'}`}>{error ? 'Offline' : health ? 'Inbox connected' : 'Connecting…'}</span>}>
      <div className="flex h-full min-h-[250px] flex-col">
        <div className="space-y-2 border-b border-slate-700 p-2"><div className="flex items-center justify-between gap-2 text-xs"><div><span className="font-semibold text-amber-300">{newCount} to review</span><span className="ml-2 text-slate-500">{health?.mode === 'live' ? 'AI configured' : 'Scripted preview'}</span></div><a href="/community" target="_blank" rel="noreferrer" className="text-sky-400">Open community form ↗</a></div><div className="flex gap-1"><button type="button" onClick={() => setFilter('new')} className={`rounded px-2 py-1 text-[10px] ${filter === 'new' ? 'bg-sky-900 text-sky-200' : 'text-slate-400'}`}>Needs review</button><button type="button" onClick={() => setFilter('all')} className={`rounded px-2 py-1 text-[10px] ${filter === 'all' ? 'bg-sky-900 text-sky-200' : 'text-slate-400'}`}>All conversations</button><input aria-label="Search community messages" className={`${field} ml-auto flex-1`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search sender or location" /></div></div>
        {(error || demoError) && <div role="alert" className="bg-red-950/50 p-2 text-xs text-red-200">{error || demoError}<button type="button" className="ml-2 underline" onClick={() => { void refresh() }}>Retry</button></div>}
        <div className="min-h-0 flex-1 overflow-auto">{shown.length === 0 && <div className="p-4 text-xs text-slate-400"><p className="font-medium text-slate-200">{items.length ? 'No matching conversations.' : 'Ready for incoming community messages.'}</p><p className="mt-2">Open the community form in another tab to submit a request. It will appear here with the sender, location, and original message.</p></div>}{shown.map((entry) => <button key={entry.id} type="button" onClick={() => select(entry.conversation_id)} className="block w-full space-y-1 border-b border-slate-800 px-3 py-2.5 text-left hover:bg-slate-800/70"><div className="flex items-center justify-between gap-2"><span className="truncate text-xs font-semibold text-slate-100">{entry.sender_name}</span><time className="shrink-0 text-[10px] text-slate-500">{new Date(entry.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div><p className="truncate text-[10px] text-slate-400">{entry.interpretation.location || entry.reported_location || 'Location needs clarification'}</p><p className="line-clamp-2 text-xs text-slate-300">{entry.original_message}</p><div className="flex items-center gap-2 text-[9px]"><span className={pending(entry) ? 'text-amber-300' : 'text-emerald-300'}>{statusLabel(entry)}</span><span className="text-slate-500">{entry.channel === 'demo' ? 'Demo' : 'Web form'}</span>{entry.processing_status === 'processing' && <span className="text-sky-400">AI reading…</span>}{entry.processing_status === 'unavailable' && <span className="text-amber-400">Manual review</span>}<span className="ml-auto text-slate-600">{entry.id}</span></div></button>)}</div>
        <div className="flex items-center justify-between gap-2 border-t border-slate-700 px-2 py-1.5 text-[9px] text-slate-500"><span>Shared inbox · human-reviewed replies · no automatic dispatch</span><button type="button" disabled={!health || loadingDemo} onClick={() => { void loadDemo() }} className="shrink-0 text-sky-400 disabled:opacity-40">{loadingDemo ? 'Adding…' : 'Add 3 demo messages'}</button></div>
      </div>
    </Panel>
    {active && <ConversationDrawer key={active.conversation_id} entry={active} />}
  </>
}
