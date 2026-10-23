import { useCallback, useEffect, useRef, useState } from 'react'
import { Play, Square, Loader2, Activity } from 'lucide-react'
import clsx from 'clsx'
import { api, type CrawlerStatus, type CrawlerLog } from '../lib/api'

const PLATFORMS = [
  { key: 'bili', label: 'B 站' },
  { key: 'dy', label: '抖音' },
  { key: 'xhs', label: '小红书(冻结中)' },
  { key: 'ks', label: '快手' },
  { key: 'wb', label: '微博' },
  { key: 'zhihu', label: '知乎' },
]

function elapsedSince(iso: string): string {
  const sec = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000))
  if (sec < 60) return `${sec} 秒`
  if (sec < 3600) return `${Math.floor(sec / 60)} 分 ${sec % 60} 秒`
  return `${Math.floor(sec / 3600)} 小时 ${Math.floor((sec % 3600) / 60)} 分`
}

/** 从原始日志行提取可读部分:优先「正在做的一件事」 */
function readableLog(message: string): string {
  // 抓 store.xxx 入库动作,浓缩成「评论 +123456」
  const m = message.match(/video comment: (\d+), content: (.{0,24})/)
  if (m) return `入库评论 ${m[1]}:${m[2]}…`
  const v = message.match(/Bilibili video: (\d+).*?title: (.{0,30})/)
  if (v) return `入库视频《${v[2]}…》`
  // 去掉 logger 前缀噪声
  return message.replace(/^.*?\(\w+\.py:\d+\)\s*-\s*/, '').slice(0, 120)
}

export default function CollectPanel() {
  const [platform, setPlatform] = useState('bili')
  const [keywords, setKeywords] = useState('')
  const [maxNotes, setMaxNotes] = useState(10)
  const [maxComments, setMaxComments] = useState(50)
  const [fullComments, setFullComments] = useState(true)
  const [status, setStatus] = useState<CrawlerStatus | null>(null)
  const [logs, setLogs] = useState<CrawlerLog[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [now, setNow] = useState(Date.now())
  const logBoxRef = useRef<HTMLPreElement>(null)

  const refresh = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([api.crawlerStatusFresh(), api.crawlerLogs(30)])
      setStatus(s)
      setLogs(l.logs ?? [])
      setNow(Date.now())
    } catch {
      /* 后端未启动时静默 */
    }
  }, [])

  useEffect(() => {
    void refresh()
    const t = setInterval(refresh, 3000)
    const tick = setInterval(() => setNow(Date.now()), 1000)
    return () => {
      clearInterval(t)
      clearInterval(tick)
    }
  }, [refresh])

  useEffect(() => {
    logBoxRef.current?.scrollTo(0, logBoxRef.current.scrollHeight)
  }, [logs])

  const running = status?.status === 'running' || status?.status === 'stopping'
  const crawled = status?.comments_crawled ?? 0
  const staleSec = status?.progress_updated_at
    ? Math.floor((now - new Date(status.progress_updated_at).getTime()) / 1000)
    : null
  const maybeStuck = running && staleSec !== null && staleSec > 90

  const start = async () => {
    setBusy(true)
    setNotice('')
    try {
      await api.crawlerStart({
        platform,
        crawler_type: 'search',
        keywords,
        max_notes_count: maxNotes,
        ...(fullComments ? {} : { max_comments_count: maxComments }),
      })
      await refresh()
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const stop = async () => {
    setBusy(true)
    try {
      await api.crawlerStop()
      await refresh()
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-stone-700">
          评论采集
          <span className="ml-2 text-xs font-normal text-stone-400">
            按 B 站搜索综合排序取前 N 个视频(热度高的排前面),评论默认全量采
          </span>
        </h2>
        <span
          className={clsx(
            'rounded-full px-2.5 py-0.5 text-xs font-medium',
            running ? 'bg-sky-100 text-sky-700' : 'bg-stone-100 text-stone-500',
          )}
        >
          {status?.status === 'running'
            ? '采集中'
            : status?.status === 'stopping'
              ? '停止中'
              : status?.status === 'error'
                ? '出错'
                : '空闲'}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
          disabled={running}
          className="rounded-lg border border-stone-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-(--brand)"
        >
          {PLATFORMS.map((p) => (
            <option key={p.key} value={p.key}>
              {p.label}
            </option>
          ))}
        </select>
        <input
          value={keywords}
          onChange={(e) => setKeywords(e.target.value)}
          placeholder="搜索关键词,英文逗号分隔,如:AI视频,AI教程"
          disabled={running}
          className="min-w-64 flex-1 rounded-lg border border-stone-200 px-3 py-1.5 text-sm outline-none focus:border-(--brand)"
        />
        <label className="flex items-center gap-1 text-xs text-stone-500">
          帖子
          <input
            type="number"
            min={1}
            value={maxNotes}
            onChange={(e) => setMaxNotes(Number(e.target.value) || 1)}
            disabled={running}
            className="w-16 rounded-lg border border-stone-200 px-2 py-1.5 text-sm"
          />
        </label>
        <label className="flex items-center gap-1.5 text-xs text-stone-500">
          <input
            type="checkbox"
            checked={fullComments}
            onChange={(e) => setFullComments(e.target.checked)}
            disabled={running}
          />
          评论全量
        </label>
        {!fullComments && (
          <label className="flex items-center gap-1 text-xs text-stone-500">
            每帖上限
            <input
              type="number"
              min={1}
              value={maxComments}
              onChange={(e) => setMaxComments(Number(e.target.value) || 1)}
              disabled={running}
              className="w-16 rounded-lg border border-stone-200 px-2 py-1.5 text-sm"
            />
          </label>
        )}
        {running ? (
          <button
            onClick={stop}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-lg bg-red-500 px-3.5 py-1.5 text-sm text-white hover:opacity-90 disabled:opacity-40"
          >
            <Square size={13} /> 停止
          </button>
        ) : (
          <button
            onClick={start}
            disabled={busy || !keywords.trim()}
            className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-3.5 py-1.5 text-sm text-white hover:opacity-90 disabled:opacity-40"
          >
            {busy ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />} 开始采集
          </button>
        )}
      </div>

      {notice && <p className="text-xs text-red-500">{notice}</p>}

      {/* 进度区:运行中或刚跑完都显示 */}
      {status && (running || crawled > 0) && (
        <div
          className={clsx(
            'rounded-xl border px-4 py-3 space-y-2',
            maybeStuck ? 'border-amber-200 bg-amber-50' : 'border-stone-200 bg-stone-50',
          )}
        >
          <div className="flex items-center gap-4 text-sm">
            <span className="flex items-center gap-1.5 font-medium text-stone-700">
              {running && <Activity size={14} className="animate-pulse text-sky-600" />}
              已采评论 <span className="text-lg text-(--brand)">{crawled}</span> 条
            </span>
            {status.started_at && (
              <span className="text-xs text-stone-400">
                已运行 {elapsedSince(status.started_at)}
              </span>
            )}
            {staleSec !== null && running && (
              <span
                className={clsx(
                  'text-xs',
                  maybeStuck ? 'text-amber-600 font-medium' : 'text-stone-400',
                )}
              >
                {maybeStuck
                  ? `已 ${elapsedSince(status!.progress_updated_at!)} 没有新数据,可能在等平台响应或被限速,继续观察;超过 10 分钟无进展再停止`
                  : `最后进展:${staleSec} 秒前`}
              </span>
            )}
            {!running && status.finished_at && (
              <span className="text-xs text-emerald-600">
                已结束{status.result_message ? `:${status.result_message}` : ''}
              </span>
            )}
          </div>
          {status.error_message && (
            <p className="text-xs text-red-500">错误:{status.error_message}</p>
          )}
        </div>
      )}

      {/* 实时日志:运行时常驻显示 */}
      {(running || logs.length > 0) && (
        <div>
          <div className="mb-1 text-xs text-stone-400">实时日志(最近 30 条,自动滚动)</div>
          <pre
            ref={logBoxRef}
            className="h-40 overflow-y-auto rounded-lg bg-stone-900 px-3 py-2 text-[11px] leading-relaxed text-stone-300 whitespace-pre-wrap"
          >
            {logs.length === 0
              ? '等待日志…'
              : logs.map((l) => `[${l.timestamp}] ${readableLog(l.message)}`).join('\n')}
          </pre>
        </div>
      )}
    </section>
  )
}
