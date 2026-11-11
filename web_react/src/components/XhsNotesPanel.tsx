import { useCallback, useEffect, useMemo, useState } from 'react'
import { ExternalLink, FileText, Loader2, RefreshCw, Search } from 'lucide-react'
import clsx from 'clsx'
import { api, type XhsNoteItem, type XhsNotesResponse } from '../lib/api'
import { formatCount } from '../lib/format'

/**
 * 小红书关键词笔记列表（只有笔记、没有评论）。
 *
 * 为什么单独一块：这批数据是 scripts/xhs_keyword_notes.py 用搜索接口采的
 * 「关键词下有哪些帖子」，后端在 /api/crawler/xhs-notes。它不进洞察页的评论来源，
 * 也不该混进「本地已采数据」的评论批次里——那是一套完全不同的原料。
 *
 * 这块要回答的就一件事：我刚采回来的是些什么帖子，互动怎么样，能不能点开看。
 */

const TYPE_LABELS: Record<string, string> = {
  video: '视频',
  normal: '图文',
}

const SORTS: { key: string; label: string }[] = [
  { key: 'liked', label: '按点赞' },
  { key: 'keyword', label: '按采集顺序' },
]

export default function XhsNotesPanel() {
  const [data, setData] = useState<XhsNotesResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState('liked')
  const [batch, setBatch] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      setData(await api.xhsNotes({ batch, q: query, sort }))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [batch, query, sort])

  useEffect(() => {
    void load()
  }, [load])

  // 输入防抖：每敲一个字就发一次请求没必要，300ms 足够
  useEffect(() => {
    const timer = setTimeout(() => setQuery(draft.trim()), 300)
    return () => clearTimeout(timer)
  }, [draft])

  const items = data?.items ?? []
  const keywordCounts = useMemo(
    () => Object.entries(data?.keyword_counts ?? {}),
    [data?.keyword_counts],
  )
  // 直接算，不 useMemo：列表最多 500 行，为一次加法挂依赖反而会因 items 每次新建而失效
  const totalLiked = items.reduce((sum, it) => sum + it.liked, 0)

  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-stone-700">
          <FileText size={14} className="text-stone-400" />
          小红书笔记列表
          <span className="ml-1 text-xs font-normal text-stone-400">
            关键词搜索结果,只有帖子没有评论;点标题跳原帖
          </span>
        </h2>
        <button
          onClick={() => void load()}
          disabled={busy}
          className="flex items-center gap-1 rounded-lg border border-stone-200 px-2.5 py-1 text-xs text-stone-500 hover:bg-stone-50 disabled:opacity-40"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          刷新
        </button>
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}

      {data && data.batches.length > 1 && (
        <div className="flex items-center gap-2 text-xs text-stone-500">
          <span>批次</span>
          <select
            value={batch || data.batch}
            onChange={(e) => setBatch(e.target.value)}
            className="rounded-lg border border-stone-200 px-2 py-1 text-xs"
          >
            {data.batches.map((b) => (
              <option key={b.batch} value={b.batch}>
                {b.batch}({b.total} 条)
              </option>
            ))}
          </select>
        </div>
      )}

      {data && data.batches.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex flex-1 min-w-[200px] items-center gap-1.5 rounded-lg border border-stone-200 px-2.5 py-1.5">
            <Search size={12} className="text-stone-400" />
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="搜标题 / 作者 / 关键词"
              className="w-full bg-transparent text-xs outline-none placeholder:text-stone-300"
            />
          </label>
          <div className="flex overflow-hidden rounded-lg border border-stone-200">
            {SORTS.map((s) => (
              <button
                key={s.key}
                onClick={() => setSort(s.key)}
                className={clsx(
                  'px-2.5 py-1.5 text-xs',
                  sort === s.key ? 'bg-stone-800 text-white' : 'text-stone-500 hover:bg-stone-50',
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {keywordCounts.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {keywordCounts.map(([kw, count]) => (
            <button
              key={kw}
              onClick={() => {
                setDraft(kw)
                setQuery(kw)
              }}
              className={clsx(
                'rounded-full px-2 py-0.5 text-[11px]',
                query === kw
                  ? 'bg-red-100 text-red-600'
                  : 'bg-stone-100 text-stone-500 hover:bg-stone-200',
              )}
            >
              {kw} {count}
            </button>
          ))}
          {query && (
            <button
              onClick={() => {
                setDraft('')
                setQuery('')
              }}
              className="rounded-full px-2 py-0.5 text-[11px] text-stone-400 underline"
            >
              清除筛选
            </button>
          )}
        </div>
      )}

      {!busy && data && data.batches.length === 0 && (
        <p className="text-xs text-stone-400">
          还没有关键词笔记。跑一次{' '}
          <code className="rounded bg-stone-100 px-1">
            uv run python scripts/xhs_keyword_notes.py --keyword 关键词
          </code>{' '}
          就会出现在这里。
        </p>
      )}

      {items.length > 0 && (
        <>
          <p className="text-[11px] text-stone-400">
            共 {data?.total ?? 0} 条{query ? `(筛选「${query}」后)` : ''},当前列表点赞合计{' '}
            {formatCount(totalLiked)}
          </p>
          {/* 窄窗口（比如内置浏览器面板）下横向滚动，避免标题被挤成竖排 */}
          <div className="max-h-[560px] overflow-auto">
            <table className="w-full min-w-[760px] text-left text-xs">
              <thead className="sticky top-0 bg-white">
                <tr className="border-b border-stone-100 text-stone-400">
                  <th className="py-1.5 pr-3 font-normal">标题</th>
                  <th className="py-1.5 pr-3 font-normal">作者</th>
                  <th className="py-1.5 pr-3 text-right font-normal">赞</th>
                  <th className="py-1.5 pr-3 text-right font-normal">藏</th>
                  <th className="py-1.5 pr-3 text-right font-normal">评</th>
                  <th className="py-1.5 pr-3 font-normal">类型</th>
                  <th className="py-1.5 font-normal">关键词</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it: XhsNoteItem) => (
                  <tr key={it.note_id} className="border-b border-stone-50 hover:bg-stone-50/60">
                    <td className="py-1.5 pr-3">
                      {it.url ? (
                        <a
                          href={it.url}
                          target="_blank"
                          rel="noreferrer"
                          className="group flex items-center gap-1 text-stone-700 hover:text-red-600"
                          title="在新标签页打开原帖"
                        >
                          <span className="line-clamp-1">{it.title || '(无标题)'}</span>
                          <ExternalLink
                            size={11}
                            className="shrink-0 text-stone-300 group-hover:text-red-500"
                          />
                        </a>
                      ) : (
                        <span className="text-stone-600">{it.title || '(无标题)'}</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap py-1.5 pr-3 text-stone-500">{it.author || '—'}</td>
                    <td className="py-1.5 pr-3 text-right font-medium text-stone-700">
                      {formatCount(it.liked)}
                    </td>
                    <td className="py-1.5 pr-3 text-right text-stone-500">
                      {formatCount(it.collected)}
                    </td>
                    <td className="py-1.5 pr-3 text-right text-stone-500">
                      {formatCount(it.comments)}
                    </td>
                    <td className="py-1.5 pr-3">
                      <span
                        className={clsx(
                          'rounded-full px-1.5 py-0.5 text-[11px]',
                          it.note_type === 'video'
                            ? 'bg-sky-50 text-sky-600'
                            : 'bg-stone-100 text-stone-500',
                        )}
                      >
                        {TYPE_LABELS[it.note_type] ?? it.note_type ?? '—'}
                      </span>
                    </td>
                    <td className="whitespace-nowrap py-1.5 text-stone-400">{it.keyword || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
