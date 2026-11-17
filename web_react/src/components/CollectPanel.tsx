import { useCallback, useEffect, useRef, useState } from 'react'
import { Play, Square, Loader2, Activity } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import clsx from 'clsx'
import { Field } from './ui/Field'
import { inputClass } from './ui/helpers'
import { normalizeKeywords } from '../lib/collect-input'
import { api, type CrawlerStatus, type CrawlerLog } from '../lib/api'

const PLATFORMS = [
  { key: 'bili', label: 'B 站' },
  { key: 'dy', label: '抖音' },
  { key: 'xhs', label: '小红书' },
  { key: 'ks', label: '快手' },
  { key: 'wb', label: '微博' },
  { key: 'zhihu', label: '知乎' },
]

const PLATFORM_LABELS: Record<string, string> = Object.fromEntries(
  PLATFORMS.map((p) => [p.key, p.label]),
)

/** 各平台的采集口径说明(搜索语义和登录方式不同,别共用一句话) */
const PLATFORM_HINTS: Record<string, string> = {
  bili: '按关键词搜索视频，再采集视频下的评论。第一次建议用 B 站熟悉流程。',
  xhs: '搜索笔记时每词可能返回约 20 篇；数量受平台接口影响。采回后，到“待回复列表 → 小红书”筛选用户。',
  dy: '按关键词搜索视频。采回后，到“待回复列表 → 抖音”筛选用户。',
}

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
  // 小红书入库动作(store.xhs 的 dict 格式与 B 站不同)
  const x = message.match(/xhs note comment:\{'comment_id': '[^']+'.*?'content': '(.{0,24})/)
  if (x) return `入库评论 ${x[1]}…`
  const xn = message.match(/xhs note: \{'note_id': '[^']+'.*?'title': '(.{0,30})/)
  if (xn) return `入库笔记《${xn[1]}…》`
  const v = message.match(/Bilibili video: (\d+).*?title: (.{0,30})/)
  if (v) return `入库视频《${v[2]}…》`
  // 去掉 logger 前缀噪声
  return message.replace(/^.*?\(\w+\.py:\d+\)\s*-\s*/, '').slice(0, 120)
}

export default function CollectPanel() {
  const [params] = useSearchParams()
  const [platform, setPlatform] = useState(() => PLATFORMS.some(p => p.key === params.get('platform')) ? params.get('platform')! : 'bili')
  const [keywords, setKeywords] = useState('')
  const [maxNotes, setMaxNotes] = useState(3)
  const [maxComments, setMaxComments] = useState(50)
  const [fullComments, setFullComments] = useState(false)
  const [status, setStatus] = useState<CrawlerStatus | null>(null)
  const [logs, setLogs] = useState<CrawlerLog[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [connectionError, setConnectionError] = useState('')
  const [now, setNow] = useState(() => Date.now())
  const logBoxRef = useRef<HTMLPreElement>(null)
  const wasRunning = useRef(false)

  const refresh = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([api.crawlerStatusFresh(), api.crawlerLogs(30)])
      setConnectionError('')
      setStatus(s)
      setLogs(l.logs ?? [])
      setNow(Date.now())
      // 任务结束(运行→空闲)时广播:「本地已采数据」面板据此自动刷新(新数据已落盘)
      const nowRunning = s?.status === 'running' || s?.status === 'stopping'
      if (wasRunning.current && !nowRunning) {
        window.dispatchEvent(new Event('vca:local-data-updated'))
      }
      wasRunning.current = nowRunning
    } catch {
      setConnectionError('暂时连接不到采集服务。请确认启动窗口仍然开着；恢复连接后这里会自动更新。')
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
    const normalized = normalizeKeywords(keywords)
    if (!normalized) { setNotice('请先输入至少一个关键词。'); return }
    if (/https?:\/\//i.test(normalized)) { setNotice('这里需要填写搜索词，例如“视频剪辑教程”，请不要粘贴网址。'); return }
    if (!Number.isInteger(maxNotes) || maxNotes < 1 || maxNotes > 50000 || (!fullComments && (!Number.isInteger(maxComments) || maxComments < 1 || maxComments > 50000))) { setNotice('采集数量请填写 1 到 50,000 之间的整数。'); return }
    setBusy(true)
    setNotice('')
    try {
      await api.crawlerStart({
        platform,
        crawler_type: 'search',
        keywords: normalized,
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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="font-semibold">你想收集哪方面的评论？</h2><p className="mt-1 text-sm leading-6 text-stone-500">填写关键词即可开始。无需先配置 AI。</p></div>
        <span role="status" className={clsx('rounded-full px-3 py-1 text-xs font-medium', running ? 'bg-sky-100 text-sky-700' : 'bg-stone-100 text-stone-600')}>
          {connectionError ? '连接中断' : !status ? '正在连接' : status.status === 'running' ? '正在采集' : status.status === 'stopping' ? '正在停止' : status.status === 'error' ? '需要处理' : '可以开始'}
        </span>
      </div>
      {connectionError && <p role="alert" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">{connectionError}</p>}
      <form className="space-y-5" onSubmit={event => { event.preventDefault(); if (!running && !busy && status && !connectionError) void start() }}>
        <fieldset disabled={running || busy} className="grid gap-4 sm:grid-cols-[160px_1fr]">
          <Field label="1. 选择平台"><select className={inputClass} value={platform} onChange={event => setPlatform(event.target.value)}>{PLATFORMS.map(item => <option key={item.key} value={item.key}>{item.label}</option>)}</select></Field>
          <Field label="2. 输入搜索关键词" hint="多个词可用中文逗号、英文逗号或换行分隔；第一次用一个词即可。"><textarea rows={2} className={inputClass} value={keywords} onChange={event => setKeywords(event.target.value)} placeholder="例如：视频剪辑教程" /></Field>
        </fieldset>
        <p className="text-sm leading-6 text-stone-500">{PLATFORM_HINTS[platform] ?? '按关键词搜索内容，再收集评论。实际数量以平台返回为准。'}</p>
        <fieldset disabled={running || busy} className="space-y-3"><legend className="mb-2 text-sm font-medium">3. 这次采多少？</legend>
          <div className="grid gap-3 sm:grid-cols-2">{[
            { notes: 3, comments: 50, title: '先试一下（推荐）', hint: '目标：3 个视频 / 笔记，每条内容最多 50 条评论' },
            { notes: 10, comments: 100, title: '多采一些', hint: '目标：10 个视频 / 笔记，每条内容最多 100 条评论' },
          ].map(preset => <label key={preset.notes} className={clsx('flex cursor-pointer items-start gap-3 rounded-xl border p-4', !fullComments && maxNotes === preset.notes && maxComments === preset.comments ? 'border-orange-300 bg-orange-50' : 'border-stone-200')}>
            <input type="radio" name="collection-size" className="mt-1" checked={!fullComments && maxNotes === preset.notes && maxComments === preset.comments} onChange={() => { setMaxNotes(preset.notes); setMaxComments(preset.comments); setFullComments(false) }} />
            <span><span className="block text-sm font-medium">{preset.title}</span><span className="mt-1 block text-xs leading-6 text-stone-500">{preset.hint}</span></span>
          </label>)}</div>
          <details className="rounded-xl bg-stone-50 p-4"><summary className="cursor-pointer text-sm text-stone-600">自定义数量（熟悉后再调整）</summary><div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field label="视频 / 笔记数量上限"><input type="number" min={1} max={50000} step={1} className={inputClass} value={maxNotes} onChange={event => setMaxNotes(Number(event.target.value))} /></Field>
            <Field label="每条内容的评论上限"><input type="number" min={1} max={50000} step={1} disabled={fullComments} className={inputClass} value={maxComments} onChange={event => setMaxComments(Number(event.target.value))} /></Field>
            <label className="flex items-center gap-2 text-sm text-stone-600 sm:col-span-2"><input type="checkbox" checked={fullComments} onChange={event => setFullComments(event.target.checked)} />尝试采集全部评论（可能耗时较长，仍受平台限制）</label>
          </div></details>
        </fieldset>
        <p className="text-xs leading-6 text-stone-500">采集期间请保持启动窗口和登录浏览器打开。平台可能需要扫码或验证，访问间隔由工具控制。</p>
        <div className="flex flex-wrap items-center gap-3">{running ? <button type="button" onClick={() => void stop()} disabled={busy || status?.status === 'stopping'} className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-40"><Square size={15} />{status?.status === 'stopping' ? '正在停止…' : '停止采集'}</button> : <button type="submit" disabled={busy || !keywords.trim() || !!connectionError || !status} className="inline-flex items-center gap-2 rounded-lg bg-(--brand) px-5 py-2.5 text-sm font-medium text-white disabled:opacity-40">{busy ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}{busy ? '正在启动…' : '开始采集评论'}</button>}<Link to="/help" className="text-sm text-stone-500 underline">不确定怎么填？</Link></div>
      </form>
      {notice && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{notice}</p>}

      {/* 进度区:运行中或刚跑完都显示 */}
      {status && (running || crawled > 0 || status.finished_at || status.status === 'error') && (
        <div
          className={clsx(
            'rounded-xl border px-4 py-3 space-y-2',
            maybeStuck ? 'border-amber-200 bg-amber-50' : 'border-stone-200 bg-stone-50',
          )}
        >
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <span className="flex items-center gap-1.5 font-medium text-stone-700">
              {running && <Activity size={14} className="animate-pulse text-sky-600" />}
              {status?.platform && (
                <span className="rounded-full bg-stone-200 px-2 py-0.5 text-xs text-stone-600">
                  {PLATFORM_LABELS[status.platform] ?? status.platform}
                </span>
              )}
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
                {status.result_title || (status.result_kind === 'error' || status.result_kind === 'blocked' ? '采集未完成' : '本次采集已结束')}{status.result_message ? `:${status.result_message}` : ''}
              </span>
            )}
          </div>
          {status.error_hint && <p className="text-sm text-amber-800">下一步：{status.error_hint}</p>}
          {(status.retry_after_seconds ?? 0) > 0 && <p className="text-sm text-amber-800">读取状态时剩余等待约 {Math.ceil(status.retry_after_seconds! / 60)} 分钟，请等待后再试。</p>}
          {!running && crawled > 0 && <Link to={`/reply-list?platform=${status.platform || platform}`} className="inline-block text-sm font-medium text-(--brand) underline">下一步：筛选待回复列表 →</Link>}
          {status.error_message && (
            <p className="text-xs text-red-500">错误:{status.error_message}</p>
          )}
        </div>
      )}

      {/* 实时日志:运行时常驻显示 */}
      {(running || logs.length > 0) && (
        <details>
          <summary className="cursor-pointer text-sm text-stone-500">查看运行详情（排查问题时展开）</summary>
          <div className="my-2 text-xs text-stone-400">最近 30 条记录</div>
          <pre
            ref={logBoxRef}
            className="h-40 overflow-y-auto rounded-lg bg-stone-900 px-3 py-2 text-[11px] leading-relaxed text-stone-300 whitespace-pre-wrap"
          >
            {logs.length === 0
              ? '等待日志…'
              : logs.map((l) => `[${l.timestamp}] ${readableLog(l.message)}`).join('\n')}
          </pre>
        </details>
      )}
    </section>
  )
}
