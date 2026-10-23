import { useCallback, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { PenLine, Loader2, Copy, Trash2, Check, Wand2 } from 'lucide-react'
import clsx from 'clsx'
import { api, type Draft } from '../lib/api'

const FORMATS = [
  { key: 'xhs', label: '小红书图文' },
  { key: 'koubo', label: '短视频口播' },
  { key: 'skeleton', label: '长文骨架' },
] as const

const SKELETON_STYLES = [
  { key: 'checklist', label: '清单体/方法论' },
  { key: 'review', label: '个人实测' },
  { key: 'contrarian', label: '认知颠覆/观点文' },
  { key: 'story', label: '故事化/情感共鸣' },
] as const

export default function WriterPage() {
  const location = useLocation() as { state?: { topic_title?: string; topic_context?: string } }
  const [topicTitle, setTopicTitle] = useState(location.state?.topic_title ?? '')
  const [topicContext, setTopicContext] = useState(location.state?.topic_context ?? '')
  const [format, setFormat] = useState<'xhs' | 'koubo' | 'skeleton'>('xhs')
  const [style, setStyle] = useState('checklist')
  const [busy, setBusy] = useState(false)
  const [humanizeBusy, setHumanizeBusy] = useState(false)
  const [changes, setChanges] = useState<string[]>([])
  const [error, setError] = useState('')
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [current, setCurrent] = useState<Draft | null>(null)
  const [copied, setCopied] = useState(false)

  const refresh = useCallback(() => {
    api
      .writerList()
      .then(setDrafts)
      .catch(() => {})
  }, [])

  useEffect(refresh, [refresh])

  const generate = async () => {
    if (!topicTitle.trim() || busy) return
    setBusy(true)
    setError('')
    setChanges([])
    try {
      const d = await api.writerGenerate(topicTitle, topicContext, format, style)
      setCurrent(d)
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const humanize = async () => {
    if (!current || humanizeBusy) return
    setHumanizeBusy(true)
    setError('')
    try {
      const res = await api.writerHumanize(current.body)
      setCurrent({ ...current, body: res.body })
      setChanges(res.changes)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setHumanizeBusy(false)
    }
  }

  const copy = async (d: Draft) => {
    const text = `${d.title}\n\n${d.body}${d.tags.length ? '\n\n' + d.tags.map((t) => `#${t}`).join(' ') : ''}`
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-6 space-y-4">
      <header>
        <h1 className="text-lg font-semibold">文案生成</h1>
        <p className="text-xs text-stone-400">
          选题 → 小红书图文 / 短视频口播 / 长文骨架,支持一键去 AI 味
        </p>
      </header>

      {/* 生成区 */}
      <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-3">
        <input
          value={topicTitle}
          onChange={(e) => setTopicTitle(e.target.value)}
          placeholder="选题标题(可从「选题中心」一键带入)"
          className="w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
        />
        <textarea
          value={topicContext}
          onChange={(e) => setTopicContext(e.target.value)}
          placeholder="背景(可选):评论信号、核心矛盾、角度……"
          rows={2}
          className="w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
        />
        <div className="flex flex-wrap items-center gap-2">
          {FORMATS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFormat(f.key)}
              className={clsx(
                'rounded-lg border px-3 py-1.5 text-sm transition-colors',
                format === f.key
                  ? 'border-(--brand) bg-orange-50 text-(--brand)'
                  : 'border-stone-200 text-stone-500 hover:border-stone-300',
              )}
            >
              {f.label}
            </button>
          ))}
          {format === 'skeleton' && (
            <select
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              className="rounded-lg border border-stone-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-(--brand)"
            >
              {SKELETON_STYLES.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          )}
          <button
            onClick={generate}
            disabled={busy || !topicTitle.trim()}
            className="ml-auto flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-1.5 text-sm text-white hover:opacity-90 disabled:opacity-40"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <PenLine size={14} />}
            {busy ? '生成中…' : '生成稿件'}
          </button>
        </div>
        {error && <p className="text-sm text-red-500">{error}</p>}
      </section>

      {/* 当前稿 */}
      {current && (
        <section className="rounded-2xl border border-(--brand) bg-white p-5 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold">{current.title}</h2>
            <div className="flex items-center gap-3">
              <button
                onClick={humanize}
                disabled={humanizeBusy}
                className="flex items-center gap-1 text-xs text-stone-400 hover:text-(--brand) disabled:opacity-40"
              >
                {humanizeBusy ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Wand2 size={13} />
                )}
                去 AI 味
              </button>
              <button
                onClick={() => copy(current)}
                className="flex items-center gap-1 text-xs text-stone-400 hover:text-(--brand)"
              >
                {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? '已复制' : '复制全文'}
              </button>
            </div>
          </div>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-stone-700">
            {current.body}
          </p>
          {changes.length > 0 && (
            <div className="rounded-lg bg-emerald-50 px-3 py-2">
              <div className="mb-1 text-xs text-emerald-600">去 AI 味改动:</div>
              <ul className="space-y-0.5 text-xs text-emerald-700">
                {changes.map((c, i) => (
                  <li key={i}>· {c}</li>
                ))}
              </ul>
            </div>
          )}
          {current.tags.length > 0 && (
            <p className="text-xs text-sky-600">{current.tags.map((t) => `#${t}`).join(' ')}</p>
          )}
          {current.shots.length > 0 && (
            <div className="rounded-lg bg-stone-50 px-3 py-2">
              <div className="mb-1 text-xs text-stone-400">分镜建议</div>
              <ul className="space-y-0.5 text-xs text-stone-600">
                {current.shots.map((s, i) => (
                  <li key={i}>· {s}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {/* 历史 */}
      {drafts.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-xs font-medium text-stone-400">历史稿件</h3>
          {drafts.map((d) => (
            <button
              key={d.id}
              onClick={() => {
                setCurrent(d)
                setChanges([])
              }}
              className="flex w-full items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-2.5 text-left transition-colors hover:border-(--brand)"
            >
              <span
                className={clsx(
                  'shrink-0 rounded px-1.5 py-0.5 text-xs',
                  d.format === 'xhs'
                    ? 'bg-rose-100 text-rose-600'
                    : d.format === 'koubo'
                      ? 'bg-sky-100 text-sky-600'
                      : 'bg-violet-100 text-violet-600',
                )}
              >
                {d.format === 'xhs' ? '图文' : d.format === 'koubo' ? '口播' : '骨架'}
              </span>
              <span className="flex-1 truncate text-sm text-stone-700">{d.title}</span>
              <span className="shrink-0 text-xs text-stone-400">
                {new Date(d.ts * 1000).toLocaleDateString('zh-CN')}
              </span>
              <span
                onClick={(e) => {
                  e.stopPropagation()
                  void api.writerDelete(d.id).then(refresh)
                }}
                className="shrink-0 text-stone-300 hover:text-red-400"
              >
                <Trash2 size={13} />
              </span>
            </button>
          ))}
        </section>
      )}
    </div>
  )
}
