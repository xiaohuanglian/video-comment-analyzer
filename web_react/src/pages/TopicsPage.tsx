import { useCallback, useEffect, useState } from 'react'
import {
  Lightbulb,
  Loader2,
  Sparkles,
  Trash2,
  PenLine,
  Rocket,
  Copy,
  Check,
  LayoutGrid,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import clsx from 'clsx'
import { api, type Topic, type TopicBoard, type PlanResult, type BoostVideoResult } from '../lib/api'

export default function TopicsPage() {
  const [tab, setTab] = useState<'plan' | 'mine' | 'boost'>('plan')

  return (
    <div className="mx-auto max-w-5xl px-6 py-6 space-y-4">
      <header>
        <h1 className="text-lg font-semibold">选题中心</h1>
        <p className="text-xs text-stone-400">
          三条路:规划会(战略层,你拍板)· 评论区选题(从反馈里长)· 最强视频(博采众长成稿)
        </p>
      </header>

      <div className="flex gap-2">
        {(
          [
            { key: 'plan', label: '规划会', icon: LayoutGrid },
            { key: 'mine', label: '评论区选题', icon: Lightbulb },
            { key: 'boost', label: '最强视频', icon: Rocket },
          ] as const
        ).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={clsx(
              'flex items-center gap-1.5 rounded-lg border px-3.5 py-1.5 text-sm transition-colors',
              tab === t.key
                ? 'border-(--brand) bg-orange-50 text-(--brand)'
                : 'border-stone-200 text-stone-500 hover:border-stone-300',
            )}
          >
            <t.icon size={14} /> {t.label}
          </button>
        ))}
      </div>

      {tab === 'plan' ? <Planning /> : tab === 'mine' ? <MinedTopics /> : <BoostVideo />}
    </div>
  )
}

/* ---------------- 规划会 ---------------- */

const SOURCE_BADGE: Record<string, { label: string; cls: string }> = {
  user_seed: { label: '🌱你的想法', cls: 'bg-emerald-100 text-emerald-700' },
  comment_signal: { label: '💬评论区', cls: 'bg-sky-100 text-sky-700' },
  ai_suggest: { label: '🤖AI补', cls: 'bg-violet-100 text-violet-700' },
}

function Planning() {
  const [board, setBoard] = useState<TopicBoard | null>(null)
  const [seed, setSeed] = useState('')
  const [busy, setBusy] = useState(false)
  const [plan, setPlan] = useState<PlanResult | null>(null)
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [library, setLibrary] = useState<Topic[]>([])
  const [libPick, setLibPick] = useState<Set<string>>(new Set())
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const [b, l] = await Promise.all([api.topicBoard(), api.topicsList()])
      setBoard(b)
      setLibrary(l)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const runPlan = async () => {
    setBusy(true)
    setError('')
    setMsg('')
    try {
      const p = await api.topicPlan(seed)
      setPlan(p)
      setPicked(new Set(p.topics.map((_, i) => i)))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const savePicked = async () => {
    if (!plan) return
    const chosen = plan.topics.filter((_, i) => picked.has(i))
    if (!chosen.length) return
    try {
      const res = await api.topicBatchAdd(chosen)
      setMsg(
        `入库 ${res.inserted} 条(跳过重复 ${res.skipped.length} 条)。哪条不要?在下方选题库里勾选删除。`,
      )
      setPlan(null)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const deletePicked = async () => {
    const ids = [...libPick]
    if (!ids.length) return
    try {
      await api.topicBatchDelete(ids)
      setLibPick(new Set())
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="space-y-4">
      {/* 盘面 */}
      {board && (
        <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-3">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-semibold">选题盘面</h2>
            <span className="text-xs text-stone-400">
              库里 {board.total} 条 · 待写 {board.status.planned ?? 0} · 已写{' '}
              {board.status.drafted ?? 0}
              {!board.has_strategy && ' · ⚠️ 还没做账号定位,去「设置」补一下更准'}
            </span>
          </div>
          {board.total > 0 ? (
            <div className="overflow-x-auto">
              <table className="text-xs">
                <thead>
                  <tr>
                    <th className="px-2 py-1 text-left font-medium text-stone-400">应用域＼类型</th>
                    {board.problem_types.map((p) => (
                      <th key={p} className="px-2 py-1 font-medium text-stone-400">
                        {p}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[...board.domains, '未标域'].map((d) => {
                    const row = board.grid[d]
                    if (!row) return null
                    return (
                      <tr key={d}>
                        <td className="px-2 py-1 whitespace-nowrap text-stone-600">{d}</td>
                        {board.problem_types.map((p) => {
                          const n = row[p] ?? 0
                          return (
                            <td key={p} className="px-1 py-0.5">
                              <span
                                className={clsx(
                                  'inline-block min-w-8 rounded px-2 py-1 text-center',
                                  n === 0
                                    ? 'bg-stone-50 text-stone-300'
                                    : n < 2
                                      ? 'bg-orange-100 text-(--brand)'
                                      : 'bg-emerald-100 text-emerald-700',
                                )}
                              >
                                {n || '·'}
                              </span>
                            </td>
                          )
                        })}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-stone-400">库还空着,开一场规划会铺第一批。</p>
          )}
          {board.recent_drafts.length > 0 && (
            <p className="text-xs text-stone-400">
              最近已写(避重复):{board.recent_drafts.slice(0, 5).join('、')}
            </p>
          )}
        </section>
      )}

      {/* 种子想法 */}
      <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-3">
        <h2 className="text-sm font-semibold">
          规划会
          <span className="ml-2 text-xs font-normal text-stone-400">
            你出想法(可空)→ AI 按定位+真实评论补缺口 → 你拍板入库
          </span>
        </h2>
        <textarea
          value={seed}
          onChange={(e) => setSeed(e.target.value)}
          rows={3}
          placeholder="最近想讲点啥?都可以丢给我:想表达的观点、刷到的对标、不吐不快的点、真实案例……没有想法也可以直接开会"
          className="w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
        />
        <button
          onClick={runPlan}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-40"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <LayoutGrid size={14} />}
          {busy ? '规划中(盘面+真痛点+网格,约1分钟)…' : '开一场规划会'}
        </button>
        {error && <p className="text-sm text-red-500">{error}</p>}
        {msg && (
          <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{msg}</p>
        )}
      </section>

      {/* 规划产出:待拍板 */}
      {plan && (
        <section className="rounded-2xl border border-(--brand) bg-white p-4 shadow-sm space-y-3">
          <p className="rounded-lg bg-stone-50 px-3 py-2 text-sm text-stone-600">
            {plan.board_summary}
          </p>
          <div className="space-y-1.5">
            {plan.topics.map((t, i) => {
              const badge = SOURCE_BADGE[t.source] ?? SOURCE_BADGE.ai_suggest
              return (
                <label
                  key={i}
                  className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-stone-200 px-3 py-2 hover:border-(--brand)"
                >
                  <input
                    type="checkbox"
                    checked={picked.has(i)}
                    onChange={(e) => {
                      const next = new Set(picked)
                      if (e.target.checked) next.add(i)
                      else next.delete(i)
                      setPicked(next)
                    }}
                    className="mt-1"
                  />
                  <div className="flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-sm font-medium text-stone-800">{t.title}</span>
                      <span className={clsx('rounded px-1.5 py-0.5 text-xs', badge.cls)}>
                        {badge.label}
                      </span>
                      <span className="rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-500">
                        {t.application_domain}·{t.problem_type}
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs text-stone-400">
                      {t.origin_note}
                      {t.why ? ` — ${t.why}` : ''}
                    </p>
                  </div>
                </label>
              )
            })}
          </div>
          <button
            onClick={savePicked}
            disabled={picked.size === 0}
            className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-40"
          >
            <Check size={14} /> 入库所选({picked.size} 条)
          </button>
        </section>
      )}

      {/* 选题库(入库后剪) */}
      {library.length > 0 && (
        <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">
              选题库({library.length} 条)
              <span className="ml-2 text-xs font-normal text-stone-400">
                勾选不要的可批量删
              </span>
            </h2>
            {libPick.size > 0 && (
              <button
                onClick={deletePicked}
                className="flex items-center gap-1 rounded-lg border border-red-200 px-2.5 py-1 text-xs text-red-500 hover:bg-red-50"
              >
                <Trash2 size={12} /> 删除所选({libPick.size})
              </button>
            )}
          </div>
          <div className="space-y-1">
            {library.map((t) => (
              <label key={t.id} className="flex cursor-pointer items-center gap-2.5 px-1 py-1">
                <input
                  type="checkbox"
                  checked={libPick.has(t.id)}
                  onChange={(e) => {
                    const next = new Set(libPick)
                    if (e.target.checked) next.add(t.id)
                    else next.delete(t.id)
                    setLibPick(next)
                  }}
                />
                <span className="flex-1 truncate text-sm text-stone-700">{t.title}</span>
                {t.application_domain && (
                  <span className="rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-500">
                    {t.application_domain}·{t.problem_type}
                  </span>
                )}
                {t.source && (
                  <span
                    className={clsx(
                      'rounded px-1.5 py-0.5 text-xs',
                      (SOURCE_BADGE[t.source] ?? SOURCE_BADGE.ai_suggest).cls,
                    )}
                  >
                    {(SOURCE_BADGE[t.source] ?? SOURCE_BADGE.ai_suggest).label}
                  </span>
                )}
                <span
                  className={clsx(
                    'rounded px-1.5 py-0.5 text-xs',
                    t.status === 'drafted'
                      ? 'bg-emerald-50 text-emerald-600'
                      : t.status === 'published'
                        ? 'bg-sky-50 text-sky-600'
                        : 'bg-stone-50 text-stone-400',
                  )}
                >
                  {t.status === 'drafted' ? '已写' : t.status === 'published' ? '已发' : '待写'}
                </span>
              </label>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

/* ---------------- 评论区选题 ---------------- */

function MinedTopics() {
  const [topics, setTopics] = useState<Topic[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const refresh = useCallback(() => {
    api
      .topicsList()
      .then(setTopics)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  useEffect(refresh, [refresh])

  const generate = async () => {
    setBusy(true)
    setError('')
    try {
      await api.topicGenerate()
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const toWriter = (t: Topic) => {
    const ctx = `评论信号:${t.signal}\n核心矛盾:${t.core_tension}\n角度:${t.angle}\n目标读者:${t.target_reader}`
    navigate('/writer', { state: { topic_title: t.title, topic_context: ctx } })
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-stone-400">
          从已采集评论区挖信号(追问/反驳/补充/情绪/行动意图/作者互动),写稿时已自带用户情绪与反馈
        </p>
        <button
          onClick={generate}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-40"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
          {busy ? '挖掘中…' : '挖一个选题'}
        </button>
      </div>

      {error && <p className="text-sm text-red-500">{error}</p>}

      {topics.length === 0 && !busy && (
        <p className="py-14 text-center text-sm text-stone-400">
          还没有选题。先去「采集」页采一批评论,再点右上角挖掘;或去「规划会」批量铺。
        </p>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        {topics.map((t) => (
          <article
            key={t.id}
            className="space-y-2.5 rounded-2xl border border-stone-200 bg-white p-4 shadow-sm"
          >
            <div className="flex items-start justify-between gap-2">
              <h2 className="text-sm font-semibold text-stone-800">{t.title}</h2>
              <button
                onClick={() => void api.topicDelete(t.id).then(refresh)}
                className="shrink-0 text-stone-300 hover:text-red-400"
              >
                <Trash2 size={14} />
              </button>
            </div>
            {t.signal && <Field label="评论信号" v={t.signal} accent />}
            {t.core_tension && <Field label="核心矛盾" v={t.core_tension} />}
            {t.target_reader && <Field label="目标读者" v={t.target_reader} />}
            {t.angle && <Field label="写作角度" v={t.angle} />}
            <div className="flex flex-wrap gap-1.5">
              {t.viral_score ? (
                <span className="rounded bg-orange-100 px-1.5 py-0.5 text-xs text-(--brand)">
                  爆款 {t.viral_score}/10
                </span>
              ) : null}
              {t.evergreen_score ? (
                <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-xs text-emerald-700">
                  长青 {t.evergreen_score}/10
                </span>
              ) : null}
              {t.application_domain && (
                <span className="rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-500">
                  {t.application_domain}·{t.problem_type}
                </span>
              )}
            </div>
            {t.video_url && (
              <div className="flex items-center justify-between border-t border-stone-100 pt-2.5">
                <a
                  href={t.video_url}
                  target="_blank"
                  rel="noreferrer"
                  className="max-w-52 truncate text-xs text-stone-400 hover:text-(--brand)"
                >
                  来源:{t.video_title}({t.comment_count} 条评论)
                </a>
                <button
                  onClick={() => toWriter(t)}
                  className="flex shrink-0 items-center gap-1 rounded-lg border border-stone-200 px-2.5 py-1 text-xs text-stone-600 hover:border-(--brand) hover:text-(--brand)"
                >
                  <PenLine size={12} /> 去写稿
                </button>
              </div>
            )}
          </article>
        ))}
      </div>
    </div>
  )
}

/* ---------------- 最强视频 ---------------- */

function BoostVideo() {
  const [topic, setTopic] = useState('')
  const [links, setLinks] = useState('')
  const [style, setStyle] = useState('')
  const [autoSearch, setAutoSearch] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<BoostVideoResult | null>(null)
  const [copied, setCopied] = useState(false)

  const run = async () => {
    if (!topic.trim() || busy) return
    setBusy(true)
    setError('')
    setResult(null)
    try {
      const list = links
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean)
      setResult(await api.topicBoostVideo(topic, list, style, autoSearch))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const copyScript = async () => {
    if (!result) return
    await navigator.clipboard.writeText(
      `${result.titles[0] ?? result.topic_title}\n\n${result.script}`,
    )
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="space-y-4">
      <section className="space-y-3 rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
        <p className="text-xs text-stone-400">
          适合:做的人不多、但做了都拿到成绩的选题。AI
          博采众长(国内已采集数据 + 自动搜 YouTube),融合优点、去掉缺点,产出可直接开拍的稿子。
        </p>
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="选题,如:AI视频运镜调度入门"
          className="w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
        />
        <textarea
          value={links}
          onChange={(e) => setLinks(e.target.value)}
          placeholder="指定参考链接(可选,每行一个,支持 YouTube / B 站)。不贴也行——工具会自己去 YouTube 搜"
          rows={3}
          className="w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
        />
        <input
          value={style}
          onChange={(e) => setStyle(e.target.value)}
          placeholder="个人风格覆盖(可选;留空用「设置」里的账号定位)"
          className="w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
        />
        <label className="flex items-center gap-1.5 text-xs text-stone-500">
          <input type="checkbox" checked={autoSearch} onChange={(e) => setAutoSearch(e.target.checked)} />
          自动去 YouTube 搜国外优质参考(推荐)
        </label>
        <button
          onClick={run}
          disabled={busy || !topic.trim()}
          className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-40"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Rocket size={14} />}
          {busy ? '博采众长中(抓素材+写稿,可能要1-2分钟)…' : '打造最强视频'}
        </button>
        {error && <p className="text-sm text-red-500">{error}</p>}
      </section>

      {result && (
        <>
          <section className="space-y-2 rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
            <div className="text-xs font-medium text-stone-400">参考了这些同类内容</div>
            <ul className="space-y-1">
              {result.reference_review.map((r, i) => (
                <li key={i} className="text-sm text-stone-600">
                  <span className="text-(--brand)">{r.source}</span> — {r.take}
                </li>
              ))}
            </ul>
            {(result.bili_refs.length > 0 || (result.auto_found ?? []).length > 0) && (
              <p className="text-xs text-stone-400">
                素材:B站 {[...result.bili_refs].slice(0, 3).join('、')}
                {(result.auto_found ?? []).map(
                  (v) => ` · 🔍《${v.title}》${v.view_count ? `${(v.view_count / 10000).toFixed(1)}万播放` : ''}`,
                )}
              </p>
            )}
          </section>

          <section className="space-y-3 rounded-2xl border border-(--brand) bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <div className="text-xs font-medium text-stone-400">备选标题</div>
              <button
                onClick={copyScript}
                className="flex items-center gap-1 text-xs text-stone-400 hover:text-(--brand)"
              >
                {copied ? <Check size={13} /> : <Copy size={13} />}
                {copied ? '已复制' : '复制稿子'}
              </button>
            </div>
            <ol className="space-y-1">
              {result.titles.map((t, i) => (
                <li key={i} className="text-sm font-medium text-stone-700">
                  {i + 1}. {t}
                </li>
              ))}
            </ol>
            <div className="border-t border-stone-100 pt-3">
              <div className="mb-1 text-xs font-medium text-stone-400">口播稿</div>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-stone-700">
                {result.script}
              </p>
            </div>
            {result.why_strong && (
              <p className="rounded-lg bg-orange-50 px-3 py-2 text-xs text-(--brand)">
                强在哪:{result.why_strong}
              </p>
            )}
          </section>
        </>
      )}
    </div>
  )
}

function Field({ label, v, accent = false }: { label: string; v: string; accent?: boolean }) {
  if (!v) return null
  return (
    <p className="text-xs leading-relaxed">
      <span className="text-stone-400">{label}:</span>
      <span className={accent ? 'text-(--brand)' : 'text-stone-600'}>{v}</span>
    </p>
  )
}
