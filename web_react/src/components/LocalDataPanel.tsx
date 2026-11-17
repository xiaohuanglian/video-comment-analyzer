import { useCallback, useEffect, useState } from 'react'
import { Database, RefreshCw, Loader2 } from 'lucide-react'
import clsx from 'clsx'
import { api, type LocalDataBatch, type LocalDataSummary } from '../lib/api'

const PLATFORM_LABELS: Record<string, string> = {
  xhs: '小红书',
  bili: 'B 站',
  dy: '抖音',
  ks: '快手',
  wb: '微博',
  zhihu: '知乎',
}

const PLATFORM_ORDER = ['xhs', 'bili', 'dy', 'ks', 'wb', 'zhihu']

const SOURCE_LABELS: Record<string, string> = {
  manual: '手动批量',
  automation: '自动化',
}

const PLATFORM_PILL: Record<string, string> = {
  xhs: 'bg-red-50 text-red-600',
  bili: 'bg-sky-50 text-sky-600',
}

function platformLabel(p: string): string {
  return PLATFORM_LABELS[p] ?? p
}

/** 平台汇总行数上限:太老的批次不值得占屏 */
const MAX_BATCH_ROWS = 10

export default function LocalDataPanel() {
  const [data, setData] = useState<LocalDataSummary | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      setData(await api.crawlerLocalData())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // 采集任务结束(落盘完成)时自动刷新,不用手动点
  useEffect(() => {
    const handler = () => void refresh()
    window.addEventListener('vca:local-data-updated', handler)
    return () => window.removeEventListener('vca:local-data-updated', handler)
  }, [refresh])

  const platforms = data?.platforms ?? {}
  const orderedPlatforms = [
    ...PLATFORM_ORDER.filter((p) => platforms[p]),
    ...Object.keys(platforms).filter((p) => !PLATFORM_ORDER.includes(p)),
  ]
  const batches = data?.batches ?? []
  // 最新一批小红书:把笔记标题亮出来,让"采回了什么"看得见
  const latestXhs = batches.find((b: LocalDataBatch) => b.platform === 'xhs')

  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-stone-700">
          <Database size={14} className="text-stone-400" />
          本地已采数据
          <span className="ml-1 text-xs font-normal text-stone-400">
            数据保存在本机；三平台用户筛选统一在“待回复列表”
          </span>
        </h2>
        <button
          onClick={refresh}
          disabled={busy}
          className="flex items-center gap-1 rounded-lg border border-stone-200 px-2.5 py-1 text-xs text-stone-500 hover:bg-stone-50 disabled:opacity-40"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          刷新
        </button>
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}

      {Object.keys(platforms).length === 0 && !busy && (
        <p className="text-xs text-stone-400">还没有评论。在上方输入一个关键词，点击“开始采集评论”。</p>
      )}

      {orderedPlatforms.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {orderedPlatforms.map((p) => {
            const s = platforms[p]
            const unit = p === 'xhs' ? '篇笔记' : '个视频'
            return (
              <div
                key={p}
                className="rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-sm"
              >
                <span
                  className={clsx(
                    'mr-2 rounded-full px-2 py-0.5 text-xs font-medium',
                    PLATFORM_PILL[p] ?? 'bg-stone-200 text-stone-600',
                  )}
                >
                  {platformLabel(p)}
                </span>
                <span className="font-medium text-stone-700">
                  {(s.contents ?? 0).toLocaleString()} {unit}
                </span>
                <span className="text-stone-400"> / </span>
                <span className="font-medium text-(--brand)">
                  {(s.comments ?? 0).toLocaleString()}
                </span>
                <span className="text-stone-500"> 条评论</span>
                <span className="ml-1 text-xs text-stone-400">
                  ({s.batches ?? 0} 批)
                </span>
              </div>
            )
          })}
        </div>
      )}

      {batches.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-stone-100 text-stone-400">
                <th className="py-1.5 pr-3 font-normal">日期</th>
                <th className="py-1.5 pr-3 font-normal">来源</th>
                <th className="py-1.5 pr-3 font-normal">平台</th>
                <th className="py-1.5 pr-3 font-normal">笔记/视频</th>
                <th className="py-1.5 font-normal">评论</th>
              </tr>
            </thead>
            <tbody>
              {batches.slice(0, MAX_BATCH_ROWS).map((b) => (
                <tr key={`${b.date}-${b.source}-${b.platform}`} className="border-b border-stone-50">
                  <td className="py-1.5 pr-3 text-stone-600">{b.date}</td>
                  <td className="py-1.5 pr-3 text-stone-500">
                    {SOURCE_LABELS[b.source] ?? b.source}
                  </td>
                  <td className="py-1.5 pr-3">
                    <span
                      className={clsx(
                        'rounded-full px-2 py-0.5 text-[11px]',
                        PLATFORM_PILL[b.platform] ?? 'bg-stone-100 text-stone-500',
                      )}
                    >
                      {platformLabel(b.platform)}
                    </span>
                  </td>
                  <td className="py-1.5 pr-3 text-stone-600">{b.contents}</td>
                  <td className="py-1.5 font-medium text-stone-700">
                    {b.comments.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {batches.length > MAX_BATCH_ROWS && (
            <p className="mt-1 text-[11px] text-stone-400">
              只列最近 {MAX_BATCH_ROWS} 批,共 {batches.length} 批
            </p>
          )}
        </div>
      )}

      {latestXhs && latestXhs.titles.length > 0 && (
        <div className="rounded-xl border border-red-100 bg-red-50/40 px-3 py-2">
          <div className="text-xs font-medium text-stone-600">
            最新小红书批次({latestXhs.date},{SOURCE_LABELS[latestXhs.source] ?? latestXhs.source}
            ,{latestXhs.contents} 篇)采到的笔记:
          </div>
          <ul className="mt-1 space-y-0.5">
            {latestXhs.titles.map((t, i) => (
              <li key={i} className="text-xs text-stone-500">
                · {t}
                {t.length >= 24 ? '…' : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
