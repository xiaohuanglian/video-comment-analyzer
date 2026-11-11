import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Loader2, Play, RefreshCw, Square, FileText, Sparkles } from 'lucide-react'
import clsx from 'clsx'
import {
  api,
  type InsightPricing,
  type InsightProfile,
  type InsightRunSummary,
  type InsightSourceGroup,
} from '../lib/api'

/**
 * 评论洞察。
 *
 * 背景（2026-11-11 修复）：这套后端（`/api/analysis/*`，47 条路由、
 * ~16k 行）一直存在且有完整测试，但 React 面板从未接入——旧前端
 * `web_static/insight.js` 在 2026-10-23 移除旧面板时被删掉，UI 没跟着重建。
 * 结果是 README 教用户在「评论洞察」面板配置模型并开始分析，而那个面板
 * 根本不存在。这里补回最小可用路径：
 *   选语料 → 建任务 → 启动分析 → 看报告。
 *
 * 红线不变：分析必须手动点击开始，不做任何自动触发。
 */

const LIMIT_OPTIONS = [
  { value: 100, label: '100 条' },
  { value: 1000, label: '1K' },
  { value: 10000, label: '10K' },
  { value: 0, label: '全部' },
]

export default function InsightPage() {
  const [sources, setSources] = useState<InsightSourceGroup[]>([])
  const [runs, setRuns] = useState<InsightRunSummary[]>([])
  const [profiles, setProfiles] = useState<InsightProfile[]>([])
  const [pricing, setPricing] = useState<InsightPricing | null>(null)

  const [selected, setSelected] = useState<string[]>([])
  const [limit, setLimit] = useState(100)
  const [profileId, setProfileId] = useState('default')
  const [useMock, setUseMock] = useState(false)

  const [activeRun, setActiveRun] = useState<string>('')
  const [report, setReport] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const [src, runList, prof, price] = await Promise.all([
        api.insightSources(),
        api.insightRuns(),
        api.insightProfiles(),
        api.insightPricing(),
      ])
      setSources(src.groups ?? [])
      setRuns(runList.runs ?? [])
      setProfiles(prof.profiles ?? [])
      setPricing(price)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const totalSelectedComments = useMemo(() => {
    const wanted = new Set(selected)
    let total = 0
    for (const group of sources) {
      for (const creator of group.creators ?? []) {
        for (const file of creator.files ?? []) {
          if (wanted.has(file.path)) total += file.comment_count ?? 0
        }
      }
    }
    return total
  }, [sources, selected])

  const toggle = (path: string) => {
    setSelected((prev) => (prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]))
  }

  const createRun = async () => {
    if (selected.length === 0) {
      setError('先勾选至少一个评论文件')
      return
    }
    setBusy('create')
    setError('')
    try {
      const res = await api.insightCreateRun({
        name: `评论洞察 ${new Date().toLocaleDateString('zh-CN')}`,
        file_paths: selected,
        analysis_limit: limit,
        use_mock: useMock,
        profile_id: profileId,
      })
      setActiveRun(res.run_id)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const startAnalyze = async (runId: string) => {
    setBusy(`analyze:${runId}`)
    setError('')
    try {
      await api.insightAnalyze(runId, { use_mock: useMock, limit: limit || undefined })
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const cancelRun = async (runId: string) => {
    setBusy(`cancel:${runId}`)
    try {
      await api.insightCancel(runId)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const openReport = async (runId: string) => {
    setBusy(`report:${runId}`)
    setError('')
    try {
      const res = await api.insightReport(runId)
      setActiveRun(runId)
      setReport(res.markdown || '')
      if (!res.markdown) {
        setError(res.waiting_for_open_themes ? '这个任务还没有可读报告：先把主题归并跑完' : '暂无报告内容')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-6 space-y-4">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold">评论洞察</h1>
          <p className="text-xs text-stone-400">
            微批次证据抽取 → 代码校验 → 数据集研究 → 可读报告。AI 只发现，结论由人确认。
          </p>
        </div>
        <button
          onClick={() => void load()}
          className="flex items-center gap-1.5 rounded-lg border border-stone-200 px-3 py-1.5 text-xs text-stone-600 hover:border-(--brand)"
        >
          <RefreshCw size={13} /> 刷新
        </button>
      </header>

      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span className="break-all">{error}</span>
        </div>
      )}

      {/* 1. 选语料 */}
      <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">
            1. 选择评论语料
            <span className="ml-2 text-xs font-normal text-stone-400">
              已选 {selected.length} 个文件 · 约 {totalSelectedComments.toLocaleString()} 条评论
            </span>
          </h2>
          {selected.length > 0 && (
            <button onClick={() => setSelected([])} className="text-xs text-stone-400 hover:text-stone-600">
              清空
            </button>
          )}
        </div>

        {sources.length === 0 && (
          <p className="py-6 text-center text-xs text-stone-400">
            还没有可分析的评论。先去「采集」页爬一批。
          </p>
        )}

        <div className="max-h-72 space-y-3 overflow-y-auto">
          {sources.map((group) => (
            <div key={group.category}>
              <div className="mb-1 text-xs font-medium text-stone-500">
                {group.category}
                <span className="ml-2 font-normal text-stone-400">
                  {group.file_count} 文件 / {group.comment_count.toLocaleString()} 条
                </span>
              </div>
              {(group.creators ?? []).map((creator) => (
                <div key={creator.creator} className="mb-1 rounded-lg border border-stone-100 p-2">
                  <div className="mb-1 text-xs text-stone-500">{creator.creator}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {(creator.files ?? []).map((file) => {
                      const on = selected.includes(file.path)
                      return (
                        <button
                          key={file.path}
                          onClick={() => toggle(file.path)}
                          className={clsx(
                            'rounded-md border px-2 py-1 text-[11px] transition-colors',
                            on
                              ? 'border-(--brand) bg-orange-50 text-(--brand)'
                              : 'border-stone-200 text-stone-600 hover:border-stone-300',
                          )}
                          title={file.path}
                        >
                          {file.name ?? file.path.split('/').pop()}
                          <span className="ml-1 text-stone-400">{file.comment_count ?? 0}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>

      {/* 2. 配置并建任务 */}
      <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-3">
        <h2 className="text-sm font-semibold">2. 配置</h2>
        <div className="grid grid-cols-2 gap-3 text-xs">
          <label className="space-y-1">
            <span className="text-stone-500">分析数量</span>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="w-full rounded-lg border border-stone-200 px-2 py-1.5"
            >
              {LIMIT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-stone-500">项目档案（决定分类维度）</span>
            <select
              value={profileId}
              onChange={(e) => setProfileId(e.target.value)}
              className="w-full rounded-lg border border-stone-200 px-2 py-1.5"
            >
              {profiles.map((p) => (
                <option key={p.profile_id} value={p.profile_id}>
                  {p.name ?? p.profile_id}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="flex items-center gap-2 text-xs text-stone-600">
          <input type="checkbox" checked={useMock} onChange={(e) => setUseMock(e.target.checked)} />
          演示模式（不调用模型，仅走通流程；结果不可用于决策）
        </label>

        {pricing && (
          <p className="text-[11px] text-stone-400">
            模型 {pricing.model_name} · 计价 {pricing.input_price}/{pricing.output_price}{' '}
            {pricing.currency}（每千 token 级，见设置页）
          </p>
        )}

        <button
          onClick={() => void createRun()}
          disabled={busy === 'create' || selected.length === 0}
          className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
        >
          {busy === 'create' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
          创建分析任务
        </button>
      </section>

      {/* 3. 任务列表 */}
      <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-2">
        <h2 className="text-sm font-semibold">
          3. 任务与报告
          <span className="ml-2 text-xs font-normal text-stone-400">{runs.length} 个</span>
        </h2>
        {runs.length === 0 && <p className="py-6 text-center text-xs text-stone-400">还没有分析任务</p>}
        {runs.map((run) => (
          <div
            key={run.run_id}
            className={clsx(
              'flex items-center gap-3 rounded-xl border px-3 py-2',
              activeRun === run.run_id ? 'border-(--brand)' : 'border-stone-200',
            )}
          >
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium text-stone-700">{run.name ?? run.run_id}</div>
              <div className="text-[11px] text-stone-400">
                {run.total_records ?? 0} 条 · 已完成 {run.completed ?? 0}
                {(run.failed ?? 0) > 0 && ` · 失败 ${run.failed}`}
                {run.status ? ` · ${run.status}` : ''}
                {run.use_mock ? ' · 演示' : ''}
              </div>
            </div>
            <button
              onClick={() => void startAnalyze(run.run_id)}
              disabled={busy === `analyze:${run.run_id}`}
              className="flex items-center gap-1 rounded-md border border-stone-200 px-2 py-1 text-[11px] text-stone-600 hover:border-(--brand) disabled:opacity-40"
            >
              {busy === `analyze:${run.run_id}` ? (
                <Loader2 size={11} className="animate-spin" />
              ) : (
                <Play size={11} />
              )}
              开始分析
            </button>
            <button
              onClick={() => void cancelRun(run.run_id)}
              disabled={busy === `cancel:${run.run_id}`}
              className="flex items-center gap-1 rounded-md border border-stone-200 px-2 py-1 text-[11px] text-stone-600 hover:border-red-300 hover:text-red-500 disabled:opacity-40"
            >
              <Square size={11} /> 停止
            </button>
            <button
              onClick={() => void openReport(run.run_id)}
              disabled={busy === `report:${run.run_id}`}
              className="flex items-center gap-1 rounded-md border border-stone-200 px-2 py-1 text-[11px] text-stone-600 hover:border-(--brand) disabled:opacity-40"
            >
              {busy === `report:${run.run_id}` ? (
                <Loader2 size={11} className="animate-spin" />
              ) : (
                <FileText size={11} />
              )}
              看报告
            </button>
          </div>
        ))}
      </section>

      {report && (
        <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="mb-2 text-sm font-semibold">报告</h2>
          <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-stone-50 p-3 text-[11px] leading-relaxed text-stone-700">
            {report}
          </pre>
        </section>
      )}
    </div>
  )
}
