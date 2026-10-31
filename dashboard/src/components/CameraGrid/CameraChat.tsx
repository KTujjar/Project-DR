import { useEffect, useRef, useState, type FormEvent } from 'react'
import { askCamera, fetchSceneLog, type ChatMessage, type SceneLog } from '../../data/sources/cameraChat'
import { timeAgo } from '../labels'

const SCENE_LOG_POLL_MS = 15_000 // the CV service writes a scene note about every 30 s
const QUICK_QUESTIONS = ["What's happening now?", 'What happened in the last 10 minutes?', 'Does anyone need help?']

interface Reply extends ChatMessage {
  usedImage?: boolean
}

// Ask the CV service's AI assistant about this camera: what's happening now (it sees the current
// frame) and what happened earlier (30 min of metrics, passes and its own scene-log notes).
// The conversation resets when the enlarged view closes.
export function CameraChat({ cameraId, cvUrl, siteName }: { cameraId: string; cvUrl: string; siteName: string }) {
  const [messages, setMessages] = useState<Reply[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sceneLog, setSceneLog] = useState<SceneLog | null>(null)
  const [showLog, setShowLog] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  // Rendered with key={cameraId}, so switching cameras starts a fresh conversation.
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const log = await fetchSceneLog(cvUrl, cameraId)
        if (!cancelled) setSceneLog(log)
      } catch {
        // CV service offline: the chat itself reports that when asked
      }
    }
    void load()
    const timer = setInterval(load, SCENE_LOG_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [cameraId, cvUrl])

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'nearest' })
  }, [messages, busy])

  const send = async (text: string) => {
    const question = text.trim()
    if (!question || busy) return
    const convo: Reply[] = [...messages, { role: 'user', content: question }]
    setMessages(convo)
    setInput('')
    setBusy(true)
    setError(null)
    try {
      const answer = await askCamera(
        cvUrl,
        cameraId,
        convo.map(({ role, content }) => ({ role, content })),
        siteName,
      )
      setMessages([...convo, { role: 'assistant', content: answer.reply, usedImage: answer.used.image }])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The camera assistant is unavailable.')
      setMessages(messages) // drop the unanswered question so it can be asked again
      setInput(question)
    } finally {
      setBusy(false)
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    void send(input)
  }

  const notes = sceneLog?.notes ?? []
  return (
    <section className="mt-3 rounded-lg bg-slate-900 p-3 text-slate-200" aria-label={`Ask about ${cameraId}`}>
      <header className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Ask about this camera</h2>
        <span className="text-xs text-slate-500">AI · sees the current image and the last 30 min</span>
      </header>

      <div className="max-h-56 space-y-2 overflow-y-auto pr-1" aria-live="polite">
        {messages.length === 0 && (
          <p className="text-sm text-slate-400">
            Ask what's happening now, what happened earlier, or whether anyone needs help.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
            <div
              className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-1.5 text-sm ${
                m.role === 'user' ? 'bg-sky-700 text-white' : 'bg-slate-800 text-slate-100'
              }`}
            >
              {m.content}
              {m.role === 'assistant' && m.usedImage === false && (
                <div className="mt-1 text-[10px] text-slate-400">No current image (camera offline): answered from history.</div>
              )}
            </div>
          </div>
        ))}
        {busy && <p className="text-sm text-slate-400">Thinking…</p>}
        <div ref={endRef} />
      </div>

      {error && <p className="mt-2 rounded bg-red-900/60 px-2 py-1 text-xs text-red-100">{error}</p>}

      <div className="mt-2 flex flex-wrap gap-1">
        {QUICK_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            disabled={busy}
            onClick={() => void send(q)}
            className="rounded-full bg-slate-800 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-700 disabled:opacity-40"
          >
            {q}
          </button>
        ))}
      </div>

      <form onSubmit={onSubmit} className="mt-2 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about this camera…"
          aria-label="Question about this camera"
          maxLength={2000}
          className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-100 placeholder:text-slate-500"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded bg-sky-600 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40"
        >
          Send
        </button>
      </form>

      <div className="mt-3 border-t border-slate-700 pt-2">
        <button
          type="button"
          onClick={() => setShowLog((v) => !v)}
          className="text-xs font-semibold uppercase tracking-wide text-slate-400 hover:text-slate-200"
          aria-expanded={showLog}
        >
          {showLog ? '▾' : '▸'} Recent observations ({notes.length})
        </button>
        {showLog && (
          <ul className="mt-1 max-h-40 space-y-1 overflow-y-auto">
            {sceneLog && !sceneLog.enabled && (
              <li className="text-xs text-slate-400">Scene log is off (needs an Anthropic API key).</li>
            )}
            {sceneLog?.enabled && notes.length === 0 && (
              <li className="text-xs text-slate-400">No observations yet. The first one arrives within about 30 s.</li>
            )}
            {notes.map((n) => (
              <li key={n.time} className="text-xs text-slate-300">
                <span className="mr-1 text-slate-500">{timeAgo(n.time)}</span>
                {n.text}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
