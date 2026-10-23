import { useCallback, useEffect, useRef, useState } from 'react'
import { SendHorizonal, Loader2, Trash2, Sparkles } from 'lucide-react'
import { api, type ChatMessage } from '../lib/api'

const SUGGESTIONS = [
  '现在有什么待我处理的?',
  '帮我看看回复自动化的状态',
  '采集循环为什么停了?',
  '我想给「AI教程」类视频起几个选题',
]

export default function HomePage() {
  const [msgs, setMsgs] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api
      .chatHistory()
      .then(setMsgs)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [msgs, busy])

  const send = useCallback(
    async (raw?: string) => {
      const text = (raw ?? input).trim()
      if (!text || busy) return
      setInput('')
      setError('')
      setMsgs((m) => [...m, { role: 'user', text, ts: Date.now() / 1000 }])
      setBusy(true)
      try {
        const reply = await api.chatSend(text)
        setMsgs((m) => [...m, reply])
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setBusy(false)
      }
    },
    [input, busy],
  )

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col px-6">
      {/* 历史对话 */}
      <div className="flex-1 overflow-y-auto py-6 space-y-4">
        {msgs.length === 0 && !busy && (
          <div className="flex h-full flex-col items-center justify-center gap-5">
            <div className="flex items-center gap-2 text-stone-400">
              <Sparkles size={20} className="text-(--brand)" />
              <span className="text-sm">评论工作台 AI 助手 · 一句话布置任务</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => void send(s)}
                  className="rounded-xl border border-stone-200 bg-white px-4 py-2.5 text-left text-sm text-stone-600 hover:border-(--brand) transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
            <div
              className={
                m.role === 'user'
                  ? 'max-w-[80%] rounded-2xl rounded-br-sm bg-(--brand) px-4 py-2.5 text-sm text-white'
                  : 'max-w-[80%] rounded-2xl rounded-bl-sm bg-white border border-stone-200 px-4 py-2.5 text-sm text-stone-700 whitespace-pre-wrap'
              }
            >
              {m.text}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-stone-400 text-sm">
            <Loader2 size={15} className="animate-spin" /> 思考中…
          </div>
        )}
        {error && <div className="text-sm text-red-500">{error}</div>}
        <div ref={bottomRef} />
      </div>

      {/* 输入区 */}
      <div className="shrink-0 border-t border-stone-200 py-4">
        <div className="flex items-center gap-2">
          {msgs.length > 0 && (
            <button
              onClick={() => {
                void api.chatClear().then(() => setMsgs([]))
              }}
              title="清空历史"
              className="rounded-xl border border-stone-200 bg-white p-2.5 text-stone-400 hover:text-red-500 hover:border-red-200"
            >
              <Trash2 size={15} />
            </button>
          )}
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.nativeEvent.isComposing && void send()}
            placeholder="布置任务、问状态、要选题……"
            className="flex-1 rounded-xl border border-stone-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-(--brand) transition-colors"
          />
          <button
            onClick={() => void send()}
            disabled={busy || !input.trim()}
            className="rounded-xl bg-(--brand) p-2.5 text-white hover:opacity-90 disabled:opacity-40"
          >
            <SendHorizonal size={16} />
          </button>
        </div>
      </div>
    </div>
  )
}
