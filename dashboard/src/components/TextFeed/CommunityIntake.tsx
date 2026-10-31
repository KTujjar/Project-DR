import { useEffect, useState, type FormEvent } from 'react'
import { communityApi } from '../../store/useCommunityStore'
import type { ThreadMessage } from '../../data/relayTextApi'

const KEY = 'relay-public-conversation-v2'
const field = 'w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-sky-500 focus:outline-none'

export function CommunityIntake() {
  const [conversationId] = useState(() => {
    const id = localStorage.getItem(KEY) ?? `web-${crypto.randomUUID()}`
    localStorage.setItem(KEY, id)
    return id
  })
  const [name, setName] = useState(() => localStorage.getItem('relay-public-name') ?? '')
  const [location, setLocation] = useState('')
  const [contact, setContact] = useState('')
  const [text, setText] = useState('')
  const [messages, setMessages] = useState<ThreadMessage[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const thread = await communityApi.thread(conversationId)
        if (active) { setMessages(thread); setError('') }
      } catch {
        if (active) setError('The message service is unavailable. Please try again shortly.')
      } finally {
        if (active) timer = setTimeout(poll, 2000)
      }
    }
    void poll()
    return () => { active = false; clearTimeout(timer) }
  }, [conversationId])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || !text.trim()) return
    setBusy(true)
    setError('')
    try {
      await communityApi.intake({ conversation_id: conversationId, sender_name: name.trim() || 'Community member',
        reported_location: location.trim(), contact: contact.trim(), text: text.trim(), channel: 'web' })
      localStorage.setItem('relay-public-name', name)
      setText('')
      setMessages(await communityApi.thread(conversationId))
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Your message could not be recorded. Please retry.')
    } finally { setBusy(false) }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-5 bg-slate-950 px-5 py-8 text-slate-100">
      <header><a className="text-xs text-sky-400" href="/">← Coordinator dashboard</a><h1 className="mt-4 text-2xl font-semibold">Contact the relief team</h1><p className="mt-2 text-sm text-slate-400">Ask about available services, report a need, or update an earlier request. A responder reviews incoming messages.</p></header>
      <p className="rounded-lg border border-amber-900 bg-amber-950/40 p-3 text-xs text-amber-200">Hackathon demonstration. This form is not monitored by an emergency service. The supplied relief-service information is fictional.</p>
      <form onSubmit={(event) => { void submit(event) }} className="space-y-3 rounded-xl border border-slate-700 bg-slate-900/50 p-4">
        <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-xs text-slate-400">Your name or group<input className={field} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder="e.g. Hanover shelter volunteer" /></label><label className="space-y-1 text-xs text-slate-400">Location, including town<input className={field} value={location} maxLength={200} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. Hanover High School, Hanover" /></label></div>
        <label className="block space-y-1 text-xs text-slate-400">Contact information (optional)<input className={field} value={contact} maxLength={100} onChange={(e) => setContact(e.target.value)} placeholder="A contact the responder can use" /></label>
        <label className="block space-y-1 text-xs text-slate-400">Your message<textarea className={field} rows={4} required maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} placeholder="Tell us what you need, how much, and where. You can also ask a question." /></label>
        <button disabled={busy || !text.trim()} className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">{busy ? 'Recording…' : 'Send to relief team'}</button>
        <p className="text-xs text-slate-500">A receipt confirms your message was recorded. Assistance and delivery need separate confirmation.</p>
      </form>
      {error && <p role="alert" className="rounded-lg bg-red-950 p-3 text-sm text-red-200">{error}</p>}
      <section aria-live="polite" className="space-y-3"><h2 className="text-sm font-semibold">Your conversation</h2>{messages.length === 0 && <p className="text-sm text-slate-500">Your messages and responder replies will appear here.</p>}{messages.map((message) => <article key={message.id} className={`rounded-lg border p-3 ${message.role === 'user' ? 'ml-8 border-sky-800 bg-sky-950' : 'mr-8 border-slate-700 bg-slate-900'}`}><div className="mb-1 flex justify-between gap-2 text-[10px] text-slate-400"><span>{message.role === 'user' ? 'You' : message.kind === 'acknowledgment' ? 'Message receipt' : 'Relief team'}</span><time>{new Date(message.created_at).toLocaleTimeString()}</time></div><p className="whitespace-pre-wrap break-words text-sm">{message.text}</p></article>)}</section>
    </main>
  )
}
