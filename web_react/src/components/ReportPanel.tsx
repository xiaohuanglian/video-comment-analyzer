import { useCallback, useEffect, useState } from 'react'
import { BarChart3, Loader2, History, Trash2, GitMerge } from 'lucide-react'
import clsx from 'clsx'
import { api, type CommentReport, type ReportSummary } from '../lib/api'

const HEAT_COLOR: Record<string, string> = {
  高: 'bg-red-100 text-red-600',
  中高: 'bg-orange-100 text-orange-600',
  中: 'bg-amber-100 text-amber-600',
  低: 'bg-stone-100 text-stone-500',
}

export default function ReportPanel() {
  const [history, setHistory] = useState<ReportSummary[]>([])
  const [current, setCurrent] = useState<CommentReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [keywords, setKeywords] = useState('')

  const refreshList = useCallback(() => {
    api
      .commentsReports()
      .then((h) => {
        setHistory(h)
        // 没选中时默认打开最新一份
        setCurrent((c) => {
          if (c || h.length === 0) return c
          void api.commentsReport(h[0].id).then(setCurrent).catch(() => {})
          return null
        })
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    refreshList()
  }, [refreshList])

  const run = async (fusion: boolean) => {
    setBusy(true)
    setError('')
    try {
      const r = await api.commentsAnalyze(fusion ? undefined : latestDate(), keywords)
      setCurrent(r)
      refreshList()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const latestDate = (): string | undefined => {
    const batch = history.find((h) => h.scope !== '全量')
    return batch?.scope
  }

  const open = async (id: string) => {
    try {
      setCurrent(await api.commentsReport(id))
    } catch {
      /* ignore */
    }
  }

  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-stone-700">
          采集数据分析
          <span className="ml-2 text-xs font-normal text-stone-400">
            每次分析都存档,可随时回看;新分析自动融合既往结论
          </span>
        </h2>
        <div className="flex items-center gap-2">
          <input
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
            placeholder="本批关键词(存档备注,可空)"
            className="w-40 rounded-lg border border-stone-200 px-2.5 py-1.5 text-xs outline-none focus:border-(--brand)"
          />
          <button
            onClick={() => void run(false)}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-3 py-1.5 text-xs text-white hover:opacity-90 disabled:opacity-40"
          >
            {busy ? <Loader2 size={13} className="animate-spin" /> : <BarChart3 size={13} />}
            分析最近一批
          </button>
          <button
            onClick={() => void run(true)}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-lg border border-(--brand) px-3 py-1.5 text-xs text-(--brand) hover:bg-orange-50 disabled:opacity-40"
          >
            <GitMerge size={13} /> 融合分析(全库)
          </button>
        </div>
      </div>
      {error && <p className="text-xs text-red-500">{error}</p>}

      <div className="flex gap-4">
        {/* 历史列表 */}
        <aside className="w-56 shrink-0 space-y-1.5">
          <div className="flex items-center gap-1 text-xs font-medium text-stone-400">
            <History size={12} /> 历史报告({history.length})
          </div>
          {history.length === 0 && <p className="text-xs text-stone-300">还没有分析过</p>}
          {history.map((h) => (
            <div
              key={h.id}
              className={clsx(
                'group flex cursor-pointer flex-col rounded-lg border px-2.5 py-2 transition-colors',
                current?.id === h.id
                  ? 'border-(--brand) bg-orange-50'
                  : 'border-stone-200 hover:border-stone-300',
              )}
              onClick={() => void open(h.id)}
            >
              <div className="flex items-center gap-1.5 text-xs text-stone-500">
                <span className="font-medium text-stone-700">{h.scope}</span>
                <span>{new Date(h.ts * 1000).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })}</span>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    void api.commentsReportDelete(h.id).then(() => {
                      if (current?.id === h.id) setCurrent(null)
                      refreshList()
                    })
                  }}
                  className="ml-auto hidden text-stone-300 hover:text-red-400 group-hover:block"
                >
                  <Trash2 size={12} />
                </button>
              </div>
              <div className="text-[11px] text-stone-400">
                {h.total_comments} 条 · {h.theme_count} 主题 · {h.topic_count} 选题
              </div>
              {h.keywords && <div className="truncate text-[11px] text-stone-400">🏷{h.keywords}</div>}
            </div>
          ))}
        </aside>

        {/* 报告正文 */}
        <div className="min-w-0 flex-1">
          {!current ? (
            <p className="py-12 text-center text-sm text-stone-400">
              左边选一份报告,或点「分析最近一批」
            </p>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3 text-xs text-stone-400">
                <span>
                  {current.scope} · {current.total_comments} 条评论 / {current.total_videos} 个视频 ·{' '}
                  {new Date(current.ts * 1000).toLocaleString('zh-CN')}
                </span>
                {current.carry_over && (
                  <span className="rounded bg-violet-50 px-2 py-0.5 text-violet-600">
                    融合既往:{current.carry_over}
                  </span>
                )}
              </div>

              <Block title="这批人是谁">
                <p className="text-sm text-stone-700">{current.audience}</p>
              </Block>

              <Block title="痛点主题">
                <div className="space-y-1.5">
                  {current.pain_themes.map((t, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <span
                        className={clsx(
                          'mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-xs',
                          HEAT_COLOR[t.heat] ?? HEAT_COLOR['中'],
                        )}
                      >
                        {t.heat}
                      </span>
                      <p className="text-sm text-stone-700">
                        <span className="font-medium">{t.theme}</span>
                        <span className="text-stone-400"> — {t.evidence}</span>
                      </p>
                    </div>
                  ))}
                </div>
              </Block>

              <Block title="回复机会">
                <div className="grid gap-2 md:grid-cols-2">
                  {current.reply_opportunities.map((t, i) => (
                    <div key={i} className="rounded-lg bg-stone-50 px-3 py-2">
                      <div className="text-sm font-medium text-stone-700">{t.target}</div>
                      <div className="text-xs text-stone-500">{t.why}</div>
                      {t.example && <div className="mt-1 text-xs text-stone-400">例:{t.example}</div>}
                    </div>
                  ))}
                </div>
              </Block>

              <Block title="选题线索">
                <div className="space-y-1">
                  {current.topic_hints.map((t, i) => (
                    <div key={i} className="flex items-center gap-2 text-sm">
                      <span className="w-8 shrink-0 rounded bg-orange-100 px-1.5 py-0.5 text-center text-xs text-(--brand)">
                        {t.score}分
                      </span>
                      <span className="font-medium text-stone-700">{t.title}</span>
                      <span className="truncate text-xs text-stone-400">{t.signal}</span>
                    </div>
                  ))}
                </div>
              </Block>

              <Block title="建议行动">
                <ol className="space-y-1">
                  {current.dos.map((d, i) => (
                    <li key={i} className="text-sm text-stone-700">
                      {i + 1}. {d}
                    </li>
                  ))}
                </ol>
              </Block>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-stone-400">{title}</div>
      {children}
    </div>
  )
}
