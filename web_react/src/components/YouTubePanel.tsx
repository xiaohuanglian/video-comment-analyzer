import { useCallback, useEffect, useState } from 'react'
import { MonitorPlay, Loader2, Play, Download, CheckCircle2, AlertCircle, RefreshCw, FileText } from 'lucide-react'
import clsx from 'clsx'
import { api, type CommentReport, type YouTubeJob, type YouTubeSummary, type YouTubeTarget } from '../lib/api'

const SORTS = [
  { key: 'newest', label: '按时间（能采满）' },
  { key: 'top', label: '按热度（约 1400 条会截断）' },
] as const

export default function YouTubePanel() {
  const [targets, setTargets] = useState<YouTubeTarget[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [limit, setLimit] = useState(3)
  const [maxComments, setMaxComments] = useState(2000)
  const [sort, setSort] = useState<'top' | 'newest'>('newest')
  const [job, setJob] = useState<YouTubeJob | null>(null)
  const [summary, setSummary] = useState<YouTubeSummary | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reportBusy, setReportBusy] = useState(false)
  const [report, setReport] = useState<CommentReport | null>(null)
  const [reportError, setReportError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const [t, s] = await Promise.all([api.youtubeTargets(limit), api.youtubeSummary()])
      setTargets(t.targets)
      setSummary(s)
    } catch {
      /* 后端未启动时静默 */
    }
  }, [limit])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // 页面打开时接上仍在跑的任务（换页/刷新不丢进度）
  useEffect(() => {
    api
      .youtubeJobs(1)
      .then((jobs) => {
        const running = jobs[0]
        if (running?.status === 'running') {
          setJob(running)
          setBusy(true)
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!job || job.status !== 'running') return
    const timer = setInterval(async () => {
      try {
        const next = await api.youtubeJob(job.id)
        setJob(next)
        if (next.status !== 'running') {
          setBusy(false)
          void refresh()
        }
      } catch {
        /* 单次轮询失败忽略 */
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [job, refresh])

  const toggle = (channel: string) => {
    setSelected((prev) =>
      prev.includes(channel) ? prev.filter((c) => c !== channel) : [...prev, channel],
    )
  }

  const start = async () => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const created = await api.youtubeCollect({
        limit,
        max_comments: maxComments,
        sort,
        channels: selected,
      })
      setJob(created)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  const generateReport = async () => {
    if (reportBusy) return
    setReportBusy(true)
    setReportError('')
    try {
      const r = await api.youtubeReport({ channels: selected })
      setReport(r)
      window.dispatchEvent(new CustomEvent('vca:reports-updated'))
    } catch (e) {
      setReportError(e instanceof Error ? e.message : String(e))
    } finally {
      setReportBusy(false)
    }
  }

  const progress = job?.progress
  const percent = progress && progress.total > 0 ? Math.min(100, Math.round((progress.done / progress.total) * 100)) : 0

  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-stone-700">
          <MonitorPlay size={15} className="mr-1 inline-block -translate-y-px text-red-500" />
          YouTube 评论采集
          <span className="ml-2 text-xs font-normal text-stone-400">
            对标频道自动取播放 Top N 视频；零 API key
          </span>
        </h2>
        <div className="flex items-center gap-2 text-xs">
          {summary && (
            <span className="rounded-full bg-stone-100 px-2.5 py-0.5 text-stone-500">
              本地已有 {summary.total_comments.toLocaleString()} 条
            </span>
          )}
          <button
            type="button"
            onClick={() => void refresh()}
            className="inline-flex items-center gap-1 rounded-lg border border-stone-200 px-2 py-1 text-stone-500 hover:bg-stone-50"
          >
            <RefreshCw size={12} /> 刷新
          </button>
        </div>
      </div>

      {/* 频道选择 */}
      <div className="flex flex-wrap gap-2">
        {targets.length === 0 && (
          <p className="text-xs text-stone-400">没找到对标频道（需要 data/bench/youtube 或 data/creators 里已有视频清单）</p>
        )}
        {targets.map((t) => {
          const on = selected.includes(t.channel)
          return (
            <button
              key={t.channel}
              type="button"
              onClick={() => toggle(t.channel)}
              className={clsx(
                'rounded-xl border px-2.5 py-1.5 text-left text-xs transition-colors',
                on
                  ? 'border-orange-300 bg-orange-50 text-(--brand)'
                  : 'border-stone-200 text-stone-600 hover:bg-stone-50',
              )}
            >
              <span className="font-medium">{t.channel}</span>
              <span className="ml-1.5 text-stone-400">{t.video_count} 条视频</span>
            </button>
          )
        })}
      </div>
      <p className="text-[11px] text-stone-400">
        不选 = 全部频道；已选 {selected.length || '全部'}
      </p>

      {/* 参数 */}
      <div className="flex flex-wrap items-center gap-3 text-xs text-stone-500">
        <label className="inline-flex items-center gap-1.5">
          每频道视频数
          <input
            type="number"
            min={1}
            max={10}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value) || 3)}
            disabled={busy}
            className="w-14 rounded-lg border border-stone-200 px-1.5 py-1 text-xs"
          />
        </label>
        <label className="inline-flex items-center gap-1.5">
          每视频条数
          <input
            type="number"
            min={50}
            max={5000}
            step={100}
            value={maxComments}
            onChange={(e) => setMaxComments(Number(e.target.value) || 500)}
            disabled={busy}
            className="w-20 rounded-lg border border-stone-200 px-1.5 py-1 text-xs"
          />
        </label>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as 'top' | 'newest')}
          disabled={busy}
          className="rounded-lg border border-stone-200 bg-white px-2 py-1 text-xs outline-none focus:border-(--brand)"
        >
          {SORTS.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
        <span className="ml-auto" />
        <button
          type="button"
          onClick={start}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-xl bg-(--brand) px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
          {busy ? '采集中…' : '开始采集'}
        </button>
        <button
          type="button"
          onClick={generateReport}
          disabled={reportBusy || (summary?.total_comments ?? 0) === 0}
          className="inline-flex items-center gap-1.5 rounded-xl border border-stone-300 px-3 py-1.5 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:opacity-40"
          title="用已采评论生成一份对标报告，写进下方历史报告"
        >
          {reportBusy ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />}
          {reportBusy ? '生成报告…' : '生成对标报告'}
        </button>
      </div>

      {error && (
        <p className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>
      )}

      {/* 进度 */}
      {job && (
        <div className="rounded-xl border border-stone-200 bg-stone-50/60 px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-2 text-xs text-stone-600">
            {job.status === 'running' ? (
              <Loader2 size={13} className="animate-spin text-sky-600" />
            ) : job.status === 'done' ? (
              <CheckCircle2 size={13} className="text-emerald-600" />
            ) : (
              <AlertCircle size={13} className="text-red-500" />
            )}
            <span className="font-medium">
              {job.status === 'running' ? '采集中' : job.status === 'done' ? '已完成' : '失败'}
            </span>
            {progress && (
              <span className="text-stone-400">
                {progress.done}/{progress.total || '?'} 条视频 · 本次 {progress.rows.toLocaleString()} 条评论
              </span>
            )}
            {job.finished_at && <span className="text-stone-400">· {job.finished_at}</span>}
          </div>
          {progress && progress.total > 0 && (
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-stone-200">
              <div
                className={clsx('h-full rounded-full transition-all', job.status === 'error' ? 'bg-red-400' : 'bg-sky-500')}
                style={{ width: `${percent}%` }}
              />
            </div>
          )}
          {progress?.current && job.status === 'running' && (
            <div className="mt-1 truncate text-[11px] text-stone-400">当前：{progress.current}</div>
          )}
          {job.error && <p className="mt-1 text-[11px] text-red-500">{job.error}</p>}
        </div>
      )}


      {(report || reportError) && (
        <div className="rounded-xl border border-stone-200 bg-white px-3 py-2.5">
          {reportError ? (
            <p className="text-xs text-red-600">{reportError}</p>
          ) : (
            report && (
              <>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <FileText size={13} className="text-(--brand)" />
                  <span className="font-medium text-stone-700">对标报告已生成</span>
                  <span className="text-stone-400">
                    {report.total_comments.toLocaleString()} 条 / {report.total_videos} 视频
                  </span>
                  <span className="ml-auto text-stone-400">已加入下方「历史报告」</span>
                </div>
                {report.audience && (
                  <p className="mt-1.5 text-xs leading-relaxed text-stone-600">{report.audience}</p>
                )}
                {report.pain_themes.length > 0 && (
                  <ul className="mt-1.5 space-y-1">
                    {report.pain_themes.slice(0, 4).map((t, i) => (
                      <li key={i} className="text-xs text-stone-600">
                        <span className="mr-1 rounded bg-stone-100 px-1 py-0.5 text-stone-500">{t.heat}</span>
                        {t.theme}
                        {t.evidence && <span className="ml-1 text-stone-400">「{t.evidence}」</span>}
                      </li>
                    ))}
                  </ul>
                )}
                {report.topic_hints.length > 0 && (
                  <p className="mt-1.5 text-xs text-stone-600">
                    选题：{report.topic_hints.slice(0, 3).map((t) => t.title).join(' / ')}
                  </p>
                )}
              </>
            )
          )}
        </div>
      )}
      {/* 已采数据 */}
      {summary && summary.channels.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-stone-200">
          <table className="w-full text-left text-xs">
            <thead className="bg-stone-50 text-stone-400">
              <tr>
                <th className="px-3 py-1.5 font-normal">频道</th>
                <th className="px-2 py-1.5 font-normal">评论</th>
                <th className="px-2 py-1.5 font-normal">视频</th>
                <th className="px-2 py-1.5 font-normal">最高赞</th>
                <th className="px-3 py-1.5 font-normal" />
              </tr>
            </thead>
            <tbody className="text-stone-700">
              {summary.channels.map((c) => (
                <tr key={c.channel} className="border-t border-stone-100">
                  <td className="px-3 py-1.5 font-medium">{c.channel}</td>
                  <td className="px-2 py-1.5">{c.comments.toLocaleString()}</td>
                  <td className="px-2 py-1.5 text-stone-500">{c.videos}</td>
                  <td className="max-w-[16rem] truncate px-2 py-1.5 text-stone-500">
                    {c.top_liked[0]?.content ?? '—'}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <a
                      href={`/api/youtube/comments/download?channel=${encodeURIComponent(c.channel)}`}
                      className="inline-flex items-center gap-1 text-stone-500 hover:text-(--brand)"
                    >
                      <Download size={12} /> CSV
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
