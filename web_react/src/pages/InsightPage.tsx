import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowDownToLine,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  Layers,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  Square,
  Table2,
  Wand2,
} from 'lucide-react'
import clsx from 'clsx'
import { Link } from 'react-router-dom'
import {
  api,
  type InsightPricing,
  type InsightProfile,
  type InsightResultsItem,
  type InsightRunDetail,
  type InsightRunSummary,
  type InsightSourceFile,
  type InsightSourceGroup,
  type InsightTheme,
} from '../lib/api'
import { formatCount } from '../lib/format'

/**
 * 评论洞察。
 *
 * 后端 `/api/analysis/*` 提供任务、主题与报告数据，这里把它们组织成
 * 「选语料 → 建任务 → 开始分析 → 看报告」的完整路径。
 *

 *
 * 这一版把「做分析」和「看结果」分开：
 *   左：语料树（搜索/折叠/全选可见/已选汇总）
 *   右：任务工作区（进度与费用 → 指标卡 → 开放主题 → 结果表 → 决策报告 → 中文解读）
 *
 * 红线不变：分析必须手动点击开始，不做任何自动触发；报告与主题的成本都显示给用户。
 */

const LIMIT_OPTIONS = [
  { value: 100, label: '100 条' },
  { value: 1000, label: '1K' },
  { value: 10000, label: '10K' },
  { value: 0, label: '全部' },
]

const INTENT_LABELS_DEFAULT: Record<string, string> = {
  gratitude_recognition: '感谢与认可',
  check_in: '签到',
  result_feedback: '结果反馈',
  question: '提问',
  difficulty_help_request: '困难求助',
  complaint: '不满',
  other_valid: '其他有效',
  invalid_or_unclear: '无效/不明',
}

const SINGLE_VIDEO_LABELS: Record<string, string> = {
  video_sufficient: '现有视频已足够',
  one_reply_sufficient: '一次回复可解决',
  personalized_judgment_needed: '需结合个人情况',
  realtime_observation_needed: '需实时观察',
  unclear: '暂无法判断',
}

const PRODUCT_FIT_LABELS: Record<string, string> = {
  high: '高度契合',
  medium: '部分契合',
  low: '不契合',
  unclear: '不明',
}

const THEME_RELATION_LABELS: Record<string, string> = {
  supports_existing: '支持已有假设',
  extends_existing: '补充已有假设',
  new_hypothesis: '新假设',
  contradicts_existing: '与已有假设冲突',
  unrelated: '与现有假设无关',
}

/** 指标卡：字段顺序就是阅读顺序（先规模、再行为、最后机会） */
const OVERVIEW_METRICS: { key: string; label: string; hint?: string }[] = [
  { key: 'total_analyzed', label: '已分析' },
  { key: 'valid_comments', label: '有效评论' },
  { key: 'unique_users', label: '独立用户' },
  { key: 'trained_users', label: '有过行动的用户' },
  { key: 'difficulty_count', label: '遇到具体困难' },
  { key: 'question_count', label: '提出疑问' },
  { key: 'gratitude_signal_count', label: '表达感谢' },
  { key: 'check_in_count', label: '签到打卡' },
  { key: 'result_feedback_count', label: '反馈使用结果' },
  { key: 'personalized_needed_count', label: '需要针对性回答' },
  { key: 'realtime_needed_count', label: '需要看到实际过程' },
  { key: 'product_fit_high_count', label: '与内容/产品高度契合' },
  { key: 'research_matched_user_count', label: '命中目标人群' },
  { key: 'contactable_homepage_count', label: '可找到主页' },
]

const SIGNAL_LABELS_DEFAULT: Record<string, string> = {}

/**
 * 汇总里的分布字段不是纯数字，而是 {count, coverage_pct}（例如 single_video_stats、
 * signal_coverage）。直接当数字渲染会得到 [object Object] / NaN%，所以统一在这里取。
 */
function metricOf(value: unknown): { count: number; coverage_pct?: number } {
  if (typeof value === 'number') return { count: value }
  if (value && typeof value === 'object') {
    const rec = value as Record<string, unknown>
    const count = Number(rec.count ?? 0)
    const pct = rec.coverage_pct ?? rec.coverage ?? rec.percentage
    return {
      count: Number.isFinite(count) ? count : 0,
      coverage_pct: typeof pct === 'number' ? pct : undefined,
    }
  }
  return { count: 0 }
}

/**
 * 百分比字段统一成百分数再渲染。
 * 后端 summary 里的 primary_intent_percentages / *_coverage 一律是 0–100（例如
 * result_feedback = 0.98 表示 0.98%）。2026-11-13 这里曾把「≤1 视为 0–1 小数」去乘 100，
 * 结果 0.98% 被显示成 98%，和旁边 11 条的计数完全对不上——别再加这种猜测。
 */
function percentOf(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

type TabKey = 'overview' | 'themes' | 'results' | 'report' | 'narrative'

/** 报告 markdown 的轻量渲染：标题/表格/列表/引用/加粗，够用且不引依赖 */
function renderMarkdown(md: string) {
  const lines = md.split(/\r?\n/)
  const blocks: React.ReactNode[] = []
  let table: string[][] = []
  let list: string[] = []
  let key = 0

  const flushTable = () => {
    if (table.length === 0) return
    const [head, ...rows] = table
    blocks.push(
      <div key={`t${key++}`} className="my-2 overflow-x-auto">
        <table className="w-full border-collapse text-[11px]">
          <thead>
            <tr className="bg-stone-50 text-left text-stone-500">
              {head.map((cell, i) => (
                <th key={i} className="border border-stone-200 px-2 py-1 font-medium">
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td key={ci} className="border border-stone-200 px-2 py-1 text-stone-700">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>,
    )
    table = []
  }

  const flushList = () => {
    if (list.length === 0) return
    blocks.push(
      <ul key={`l${key++}`} className="my-1 list-disc space-y-0.5 pl-5 text-[11px] text-stone-700">
        {list.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>,
    )
    list = []
  }

  const inline = (text: string) =>
    text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith('**') && part.endsWith('**') ? (
        <strong key={i} className="font-semibold text-stone-800">
          {part.slice(2, -2)}
        </strong>
      ) : (
        <span key={i}>{part}</span>
      ),
    )

  for (const raw of lines) {
    const line = raw.trimEnd()
    if (line.startsWith('|')) {
      flushList()
      const cells = line.replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim())
      if (cells.every((c) => /^:?-{2,}:?$/.test(c))) continue
      table.push(cells)
      continue
    }
    flushTable()
    if (/^\s*[-*]\s+/.test(line)) {
      list.push(line.replace(/^\s*[-*]\s+/, ''))
      continue
    }
    flushList()
    if (!line.trim()) {
      blocks.push(<div key={`b${key++}`} className="h-1.5" />)
    } else if (line.startsWith('### ')) {
      blocks.push(
        <h4 key={`h${key++}`} className="mt-3 text-xs font-semibold text-stone-800">
          {inline(line.slice(4))}
        </h4>,
      )
    } else if (line.startsWith('## ')) {
      blocks.push(
        <h3 key={`h${key++}`} className="mt-4 border-b border-stone-100 pb-1 text-sm font-semibold text-stone-800">
          {inline(line.slice(3))}
        </h3>,
      )
    } else if (line.startsWith('# ')) {
      blocks.push(
        <h2 key={`h${key++}`} className="text-base font-semibold text-stone-900">
          {inline(line.slice(2))}
        </h2>,
      )
    } else if (line.startsWith('> ')) {
      blocks.push(
        <blockquote
          key={`q${key++}`}
          className="my-1 border-l-2 border-stone-300 bg-stone-50 px-2 py-1 text-[11px] text-stone-500"
        >
          {inline(line.slice(2))}
        </blockquote>,
      )
    } else {
      blocks.push(
        <p key={`p${key++}`} className="my-1 text-[11px] leading-relaxed text-stone-700">
          {inline(line)}
        </p>,
      )
    }
  }
  flushTable()
  flushList()
  return blocks
}

function downloadHref(path: string) {
  return `/api/data/download/${path.split('/').map(encodeURIComponent).join('/')}`
}

export default function InsightPage() {
  const [sources, setSources] = useState<InsightSourceGroup[]>([])
  const [runs, setRuns] = useState<InsightRunSummary[]>([])
  const [profiles, setProfiles] = useState<InsightProfile[]>([])
  const [pricing, setPricing] = useState<InsightPricing | null>(null)

  const [selected, setSelected] = useState<string[]>([])
  const [limit, setLimit] = useState(100)
  const [profileId, setProfileId] = useState('default')
  const [profileTouched, setProfileTouched] = useState(false)
  // 服务端当前生效的档案（与下拉里选的那份区分开：下拉可以是「我想用哪份」）
  const [activeProfileId, setActiveProfileId] = useState('')
  const [useMock, setUseMock] = useState(false)

  const [query, setQuery] = useState('')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [taskName, setTaskName] = useState('')

  const [activeRun, setActiveRun] = useState<string>('')
  const [detail, setDetail] = useState<InsightRunDetail | null>(null)
  const [tab, setTab] = useState<TabKey>('overview')
  const [themes, setThemes] = useState<InsightTheme[]>([])
  const [themeProgress, setThemeProgress] = useState<Record<string, unknown> | null>(null)
  const [results, setResults] = useState<InsightResultsItem[]>([])
  const [resultsTotal, setResultsTotal] = useState(0)
  const [resultsPage, setResultsPage] = useState(1)
  const [resultFilters, setResultFilters] = useState({ primary_intent: '', single_video_relation: '', product_fit: '', keyword: '' })
  const [report, setReport] = useState('')
  const [narrative, setNarrative] = useState('')
  // 采集页「历史报告」（B 站/YouTube 对标报告）是另一套产物，和洞察任务无关。
  // 计数放在这里只是为了解释「任务历史怎么只有两条」。
  const [legacyReportCount, setLegacyReportCount] = useState<number | null>(null)

  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  // 刚建好的任务：notice 里直接给一个「现在开始分析」的动作，
  // 否则用户勾完语料建完任务，还得自己猜分析按钮在右栏任务卡里。
  const [pendingAnalyzeRun, setPendingAnalyzeRun] = useState('')
  // 模型网关状态：真实分析要能拿到 key（入参 → 环境变量 → 设置页保存的配置）。
  // 前端不收集 key，所以这里只判断「服务端到底有没有配」，提前把失败挡在点击之前。
  const [modelReady, setModelReady] = useState<boolean | null>(null)
  const [modelMasked, setModelMasked] = useState('')
  const pollRef = useRef<number | null>(null)

  const load = useCallback(async () => {
    try {
      const [src, runList, prof, price] = await Promise.all([
        api.insightSources(),
        api.insightRuns(),
        api.insightProfiles(),
        api.insightPricing(),
      ])
      void api
        .commentsReports()
        .then((list) => setLegacyReportCount(list.length))
        .catch(() => setLegacyReportCount(null))
      void api
        .modelSettingsGet()
        .then((m) => {
          setModelReady(m.configured)
          setModelMasked(m.api_key_masked)
        })
        .catch(() => setModelReady(null))
      setSources(src.groups ?? [])
      setRuns(runList.runs ?? [])
      setProfiles(prof.profiles ?? [])
      setPricing(price)
      // 档案下拉必须落在「当前生效档案」上，否则永远停在内置 default（=未配置）
      setActiveProfileId(prof.active_profile_id ?? '')
      setProfileId((prev) => {
        if (profileTouched) return prev
        const active = prof.active_profile_id ?? ''
        if (active && (prof.profiles ?? []).some((p) => p.profile_id === active)) return active
        const firstConfigured = (prof.profiles ?? []).find((p) => p.is_configured)
        return firstConfigured?.profile_id ?? prev
      })
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [profileTouched])

  useEffect(() => {
    void load()
  }, [load])

  const activeProfile = useMemo(
    () => profiles.find((p) => p.profile_id === profileId) ?? null,
    [profiles, profileId],
  )

  const fileIndex = useMemo(() => {
    const map = new Map<string, InsightSourceFile>()
    for (const group of sources) {
      for (const creator of group.creators ?? []) {
        for (const file of creator.files ?? []) map.set(file.path, file)
      }
    }
    return map
  }, [sources])

  /**
   * 哪些语料已经分析过 —— 反查每个 run 的 config.file_paths。
   * 没有这个映射，17 份语料看起来一模一样，用户不知道「勾选」和「看结果」是两件事。
   */
  const analyzedFiles = useMemo(() => {
    const map = new Map<string, { runId: string; runName: string; createdAt: string }>()
    for (const run of runs) {
      for (const path of run.file_paths ?? []) {
        const prev = map.get(path)
        const createdAt = run.created_at ?? ''
        if (!prev || createdAt > prev.createdAt) {
          map.set(path, { runId: run.run_id, runName: run.name ?? run.run_id, createdAt })
        }
      }
    }
    return map
  }, [runs])

  const totalSelectedComments = useMemo(() => {
    let total = 0
    for (const path of selected) total += fileIndex.get(path)?.comment_count ?? 0
    return total
  }, [fileIndex, selected])

  const filteredGroups = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return sources
    return sources
      .map((group) => {
        const creators = (group.creators ?? [])
          .map((creator) => {
            const files = (creator.files ?? []).filter((file) =>
              `${file.path} ${file.name ?? ''} ${file.video_label ?? ''} ${creator.creator}`
                .toLowerCase()
                .includes(q),
            )
            return { ...creator, files }
          })
          .filter((creator) => creator.files.length > 0)
        return {
          ...group,
          creators,
          file_count: creators.reduce((n, c) => n + c.files.length, 0),
          comment_count: creators.reduce(
            (n, c) => n + c.files.reduce((m, f) => m + (f.comment_count ?? 0), 0),
            0,
          ),
        }
      })
      .filter((group) => group.creators.length > 0)
  }, [query, sources])

  const visiblePaths = useMemo(
    () => filteredGroups.flatMap((g) => (g.creators ?? []).flatMap((c) => (c.files ?? []).map((f) => f.path))),
    [filteredGroups],
  )
  const allVisibleSelected = visiblePaths.length > 0 && visiblePaths.every((p) => selected.includes(p))

  const toggle = (path: string) => {
    setSelected((prev) => (prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]))
  }
  const selectVisible = () => {
    setSelected((prev) => Array.from(new Set([...prev, ...visiblePaths])))
  }
  const clearSelection = () => setSelected([])

  const summarizeSources = useMemo(() => {
    const files = sources.reduce((n, g) => n + (g.file_count ?? 0), 0)
    const comments = sources.reduce((n, g) => n + (g.comment_count ?? 0), 0)
    return { files, comments }
  }, [sources])

  // ---- 任务工作区 ----

  const loadDetail = useCallback(async (runId: string) => {
    if (!runId) return
    try {
      const d = await api.insightRun(runId)
      setDetail(d)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  const loadResults = useCallback(
    async (runId: string, page: number, filters = resultFilters) => {
      if (!runId) return
      try {
        const res = await api.insightResults(runId, {
          page,
          page_size: 20,
          keyword: filters.keyword,
          primary_intent: filters.primary_intent,
          single_video_relation: filters.single_video_relation,
          product_fit: filters.product_fit,
          intent_valid: filters.primary_intent ? 'true' : undefined,
        })
        setResults(res.items ?? [])
        setResultsTotal(res.total ?? 0)
        setResultsPage(page)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    },
    [resultFilters],
  )

  const loadThemes = useCallback(async (runId: string) => {
    if (!runId) return
    try {
      const res = await api.insightThemes(runId)
      setThemes(res.themes ?? [])
      setThemeProgress((res.cluster_progress as Record<string, unknown>) ?? null)
    } catch {
      // 还没归并过时返回 404/空，不打断页面
    }
  }, [])

  const loadReport = useCallback(async (runId: string) => {
    if (!runId) return
    try {
      const res = await api.insightReport(runId)
      setReport(res.markdown || '')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  const loadNarrative = useCallback(async (runId: string) => {
    if (!runId) return
    try {
      const res = await api.insightNarrative(runId)
      setNarrative(res.text || '')
    } catch {
      // 未生成过就是空
    }
  }, [])

  const selectRun = useCallback(
    async (runId: string) => {
      setActiveRun(runId)
      setReport('')
      setNarrative('')
      setThemes([])
      setThemeProgress(null)
      await loadDetail(runId)
      await Promise.all([loadThemes(runId), loadReport(runId), loadNarrative(runId), loadResults(runId, 1)])
    },
    [loadDetail, loadNarrative, loadReport, loadResults, loadThemes],
  )

  // 选中任务后，任务在跑就轮询详情（进度/费用），跑完再拉一次主题与报告
  useEffect(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
    if (!activeRun) return
    const progress = (detail?.progress ?? {}) as Record<string, unknown>
    const running = Boolean(detail?.is_running) || ['running', 'cancelling'].includes(String(progress.status ?? ''))
    if (!running) return
    pollRef.current = window.setInterval(() => {
      void loadDetail(activeRun)
    }, 2500)
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [activeRun, detail?.is_running, detail?.progress, loadDetail])

  // 打开页面时默认选中最近一个任务，直接看到仪表盘
  useEffect(() => {
    if (activeRun || runs.length === 0) return
    void selectRun(runs[0].run_id)
  }, [activeRun, runs, selectRun])

  const refreshActive = async () => {
    if (!activeRun) return
    await Promise.all([
      loadDetail(activeRun),
      loadThemes(activeRun),
      loadReport(activeRun),
      loadNarrative(activeRun),
      loadResults(activeRun, resultsPage),
    ])
  }

  const createRun = async () => {
    if (selected.length === 0) {
      setError('先勾选至少一个评论文件')
      return
    }
    if (!profileId) {
      setError('还没有可用档案：先去「设置 → 项目档案」填一份，或点右上角新建')
      return
    }
    setBusy('create')
    setError('')
    try {
      const res = await api.insightCreateRun({
        name: taskName.trim() || `评论洞察 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
        file_paths: selected,
        analysis_limit: limit,
        use_mock: useMock,
        profile_id: profileId,
      })
      setTaskName('')
      await load()
      await selectRun(res.run_id)
      setPendingAnalyzeRun(res.run_id)
      setNotice('任务已创建。下一步：点右边这个按钮开始跑分析（不会自动跑）。')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const startAnalyze = async (runId: string, forceReanalyze = false) => {
    setBusy(`analyze:${runId}`)
    setError('')
    setPendingAnalyzeRun('')
    try {
      const res = await api.insightAnalyze(runId, {
        use_mock: useMock,
        limit: limit || undefined,
        force_reanalyze: forceReanalyze || undefined,
      })
      const maybe = res as { needs_confirmation?: boolean; message?: string }
      if (maybe.needs_confirmation) {
        setNotice(maybe.message ?? '这批评论较多，需要再次确认')
        setBusy('')
        return
      }
      setNotice('分析已在后台启动。')
      await load()
      await loadDetail(runId)
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
      await loadDetail(runId)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const clusterThemes = async (runId: string) => {
    setBusy(`cluster:${runId}`)
    setError('')
    try {
      await api.insightCluster(runId, { use_mock: useMock })
      setNotice('开放主题归并已启动，完成后这里会自动刷新。')
      setTab('themes')
      await loadThemes(runId)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const generateNarrative = async (runId: string) => {
    setBusy(`narrative:${runId}`)
    setError('')
    try {
      const res = await api.insightNarrativeGenerate(runId, { use_mock: useMock })
      setNarrative(res.text || '')
      setTab('narrative')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const progress = (detail?.progress ?? {}) as Record<string, unknown>
  const summary = (detail?.summary ?? {}) as Record<string, unknown>
  const exportPaths = (detail?.export_paths ?? {}) as Record<string, string>
  // 标签优先级：本次任务汇总里落盘的中文映射（最贴近当次分析用的档案）> 当前档案 > 内置默认。
  // 只看当前档案会出错：用户后来切换了档案，历史任务就会显示成英文键。
  const intentLabels: Record<string, string> = {
    ...INTENT_LABELS_DEFAULT,
    ...((activeProfile?.intents as Record<string, string>) ?? {}),
    ...((summary.intent_labels as Record<string, string>) ?? {}),
  }
  const signalLabels: Record<string, string> = {
    ...SIGNAL_LABELS_DEFAULT,
    ...((activeProfile?.signals as Record<string, string>) ?? {}),
    ...((summary.signal_labels as Record<string, string>) ?? {}),
  }

  const totalRecords = Number(progress.total_records ?? detail?.total_records ?? 0)
  const completed = Number(progress.completed ?? detail?.completed ?? 0)
  const failed = Number(progress.failed ?? 0)
  const pct = totalRecords > 0 ? Math.min(100, Math.round((completed / totalRecords) * 100)) : 0
  const runStatus = String(progress.status ?? detail?.status ?? '')
  const isRunning = Boolean(detail?.is_running) || runStatus === 'running' || runStatus === 'cancelling'

  const tabs: { key: TabKey; label: string; icon: typeof FileText; count?: number }[] = [
    { key: 'overview', label: '仪表盘', icon: Layers },
    { key: 'themes', label: '开放主题', icon: Sparkles, count: themes.length },
    { key: 'results', label: '评论明细', icon: Table2, count: resultsTotal },
    { key: 'report', label: '决策报告', icon: FileText },
    { key: 'narrative', label: '中文解读', icon: Wand2 },
  ]

  return (
    <div className="mx-auto max-w-[1400px] px-5 py-5 space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">评论洞察</h1>
          <p className="text-xs text-stone-400">
            微批次证据抽取 → 代码校验 → 数据集研究 → 可读报告。AI 只发现，结论由人确认。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void load()}
            className="flex items-center gap-1.5 rounded-lg border border-stone-200 px-3 py-1.5 text-xs text-stone-600 hover:border-(--brand)"
          >
            <RefreshCw size={13} /> 刷新
          </button>
        </div>
      </header>

      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span className="break-all">{error}</span>
        </div>
      )}
      {notice && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
          <span>{notice}</span>
          <div className="flex items-center gap-2">
            {pendingAnalyzeRun && (
              <button
                onClick={() => void startAnalyze(pendingAnalyzeRun, false)}
                disabled={busy === `analyze:${pendingAnalyzeRun}`}
                className="flex items-center gap-1 rounded-md bg-(--brand) px-2.5 py-1 text-[11px] font-medium text-white disabled:opacity-50"
              >
                {busy === `analyze:${pendingAnalyzeRun}` ? (
                  <Loader2 size={11} className="animate-spin" />
                ) : (
                  <Play size={11} />
                )}
                现在开始分析
              </button>
            )}
            <button
              onClick={() => {
                setNotice('')
                setPendingAnalyzeRun('')
              }}
              className="text-emerald-600 hover:text-emerald-800"
            >
              知道了
            </button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        {/* ---------- 左：语料 + 配置 ---------- */}
        <div className="space-y-4">
          <section className="rounded-2xl border border-stone-200 bg-white shadow-sm">
            <div className="space-y-2 border-b border-stone-100 p-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">
                  评论语料
                  <span className="ml-2 text-[11px] font-normal text-stone-400">
                    {summarizeSources.files} 文件 · {formatCount(summarizeSources.comments)} 条
                  </span>
                </h2>
                <div className="flex items-center gap-2 text-[11px]">
                  <button
                    onClick={allVisibleSelected ? clearSelection : selectVisible}
                    className="text-stone-500 hover:text-(--brand)"
                  >
                    {allVisibleSelected ? '取消全选' : '全选可见'}
                  </button>
                  {selected.length > 0 && (
                    <button onClick={clearSelection} className="text-stone-400 hover:text-stone-600">
                      清空
                    </button>
                  )}
                </div>
              </div>
              <div className="relative">
                <Search size={13} className="absolute left-2.5 top-2 text-stone-300" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="搜索视频 / 文件 / 博主"
                  className="w-full rounded-lg border border-stone-200 py-1.5 pl-8 pr-2 text-xs outline-none focus:border-(--brand)"
                />
              </div>
              <p className="text-[11px] text-stone-400">
                已选 {selected.length} 个文件 · 约 {formatCount(totalSelectedComments)} 条评论
              </p>
              <p className="text-[11px] leading-relaxed text-stone-400">
                勾选 = 作为<strong className="font-medium text-stone-500">下一次</strong>
                分析的输入（新建任务）。带「已分析」的文件已经有跑完的任务，点左下角任务历史直接看结果，
                不用重跑。
              </p>
            </div>

            <div className="max-h-[26rem] overflow-y-auto p-2">
              {sources.length === 0 && (
                <p className="py-8 text-center text-xs text-stone-400">
                  还没有可分析的评论。先去「采集」页爬一批。
                </p>
              )}
              {sources.length > 0 && filteredGroups.length === 0 && (
                <p className="py-8 text-center text-xs text-stone-400">没有匹配「{query}」的语料</p>
              )}
              {filteredGroups.map((group) => (
                <div key={group.category} className="mb-1">
                  <div className="flex items-center gap-1 px-1 py-1 text-[11px] font-medium text-stone-500">
                    <span className="rounded bg-stone-100 px-1.5 py-0.5">{group.category}</span>
                    <span className="font-normal text-stone-400">
                      {group.file_count} 文件 / {formatCount(group.comment_count)} 条
                    </span>
                  </div>
                  {(group.creators ?? []).map((creator) => {
                    const ck = `${group.category}::${creator.creator}`
                    const isCollapsed = collapsed[ck]
                    return (
                      <div key={ck} className="mb-0.5">
                        <button
                          onClick={() => setCollapsed((prev) => ({ ...prev, [ck]: !prev[ck] }))}
                          className="flex w-full items-center gap-1 rounded-md px-1.5 py-1 text-left text-[11px] text-stone-600 hover:bg-stone-50"
                        >
                          {isCollapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
                          <span className="min-w-0 flex-1 truncate" title={creator.creator}>
                            {creator.creator}
                          </span>
                          <span className="shrink-0 text-stone-400">
                            {creator.file_count} 文件 / {formatCount(creator.comment_count)}
                          </span>
                        </button>
                        {!isCollapsed && (
                          <div className="ml-4 space-y-0.5 border-l border-stone-100 pl-2">
                            {(creator.files ?? []).map((file) => {
                              const on = selected.includes(file.path)
                              const analyzed = analyzedFiles.get(file.path)
                              return (
                                <button
                                  key={file.path}
                                  onClick={() => toggle(file.path)}
                                  title={file.path}
                                  className={clsx(
                                    'flex w-full items-center gap-1.5 rounded-md border px-2 py-1 text-left text-[11px] transition-colors',
                                    on
                                      ? 'border-(--brand) bg-orange-50 text-(--brand)'
                                      : 'border-transparent text-stone-600 hover:border-stone-200 hover:bg-stone-50',
                                  )}
                                >
                                  <span
                                    className={clsx(
                                      'h-3 w-3 shrink-0 rounded-sm border',
                                      on ? 'border-(--brand) bg-(--brand)' : 'border-stone-300',
                                    )}
                                  />
                                  <span className="min-w-0 flex-1 truncate">
                                    {file.name ?? file.path.split('/').pop()}
                                  </span>
                                  {analyzed && (
                                    <span
                                      className="shrink-0 rounded bg-emerald-50 px-1 py-0.5 text-[10px] text-emerald-700"
                                      title={`已分析：${analyzed.runName}`}
                                    >
                                      已分析
                                    </span>
                                  )}
                                  <span className="shrink-0 text-stone-400">
                                    {formatCount(file.comment_count ?? 0)}
                                  </span>
                                </button>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              ))}
            </div>
          </section>

          <section className="space-y-3 rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
            <h2 className="text-sm font-semibold">新建任务</h2>
            <label className="block space-y-1 text-[11px]">
              <span className="text-stone-500">任务名（可空）</span>
              <input
                value={taskName}
                onChange={(e) => setTaskName(e.target.value)}
                placeholder="例如：AI 博主 Xuan 酱 · 11 月批次"
                className="w-full rounded-lg border border-stone-200 px-2 py-1.5 text-xs outline-none focus:border-(--brand)"
              />
            </label>
            <div className="grid grid-cols-2 gap-3 text-[11px]">
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
                <span className="text-stone-500">项目档案</span>
                <select
                  value={profileId}
                  onChange={(e) => {
                    setProfileTouched(true)
                    setProfileId(e.target.value)
                  }}
                  className="w-full rounded-lg border border-stone-200 px-2 py-1.5"
                >
                  {profiles.map((p) => {
                    // 显示 id：档案名（如「AI 创业者」）不带 id，用户会以为
                    // youvibe 那份档案不存在（2026-11-13 反馈）。
                    const label = p.name && p.name !== p.profile_id ? `${p.name} · ${p.profile_id}` : p.profile_id
                    return (
                      <option key={p.profile_id} value={p.profile_id}>
                        {label}
                        {p.profile_id === activeProfileId ? '（当前生效）' : ''}
                        {p.is_configured ? '' : '（未配置）'}
                      </option>
                    )
                  })}
                </select>
              </label>
            </div>
            {activeProfile && !activeProfile.is_configured && (
              <p className="rounded-lg bg-amber-50 px-2 py-1.5 text-[11px] text-amber-700">
                这份档案还没填产品/人群/研究目标，分类维度会是通用占位。去「设置 → 项目档案」补齐后再跑，结论才可用。
              </p>
            )}
            <label className="flex items-center gap-2 text-[11px] text-stone-600">
              <input type="checkbox" checked={useMock} onChange={(e) => setUseMock(e.target.checked)} />
              演示模式（不调用模型，仅走通流程；结果不可用于决策）
            </label>
            {pricing && (
              <p className="text-[11px] text-stone-400">
                模型 {pricing.model_name} · 计价 {pricing.input_price}/{pricing.output_price}{' '}
                {pricing.currency}（每千 token，见设置页）
              </p>
            )}
            {!useMock && modelReady === false && (
              <p className="rounded-lg bg-amber-50 px-2 py-1.5 text-[11px] text-amber-700">
                还没配模型网关，现在点「开始分析」会被拦下。去「设置 → 模型网关」填一次
                base_url / 模型 / API Key（存服务端，前端不保存），或先勾上面的演示模式。
              </p>
            )}
            {!useMock && modelReady === true && (
              <p className="text-[11px] text-stone-400">
                网关已配置{modelMasked ? `（${modelMasked}）` : ''}，点「开始分析」即可用服务端存的 key 跑。
              </p>
            )}
            <button
              onClick={() => void createRun()}
              disabled={busy === 'create' || selected.length === 0}
              className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-(--brand) px-3 py-2 text-xs font-medium text-white disabled:opacity-40"
            >
              {busy === 'create' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
              {selected.length === 0 ? '先在上面勾选语料' : '创建分析任务'}
            </button>
            <p className="text-center text-[11px] text-stone-400">创建后仍需手动点「开始分析」，不会自动跑。</p>
          </section>

          <section className="space-y-1 rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
            <h2 className="mb-1 text-sm font-semibold">
              任务历史
              <span className="ml-2 text-[11px] font-normal text-stone-400">{runs.length} 个</span>
            </h2>
            {runs.length === 0 && <p className="py-3 text-center text-xs text-stone-400">还没有分析任务</p>}
            <p className="pb-1 text-[11px] leading-relaxed text-stone-400">
              这里只列「洞察任务」（选了语料、真的跑过 AI 分析的那批）。历史上只跑过{' '}
              {runs.length} 次，所以只有这么多条 —— 不是漏列。
              {legacyReportCount != null && legacyReportCount > 0 && (
                <>
                  {' '}
                  另外那 {legacyReportCount} 份「对标评论报告」是采集页的产物，在{' '}
                  <Link to="/collect" className="text-(--brand) hover:underline">
                    采集页底部「历史报告」
                  </Link>{' '}
                  里。
                </>
              )}
            </p>
            {runs.map((run) => (
              <button
                key={run.run_id}
                onClick={() => void selectRun(run.run_id)}
                className={clsx(
                  'flex w-full items-center gap-2 rounded-lg border px-2 py-1.5 text-left transition-colors',
                  activeRun === run.run_id
                    ? 'border-(--brand) bg-orange-50/50'
                    : 'border-transparent hover:border-stone-200 hover:bg-stone-50',
                )}
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[11px] font-medium text-stone-700">
                    {run.name ?? run.run_id}
                  </div>
                  <div className="text-[10px] text-stone-400">
                    {run.total_records ?? 0} 条 · 完成 {run.completed ?? 0}
                    {run.status ? ` · ${run.status}` : ''}
                  </div>
                </div>
                {run.run_id === activeRun && <ChevronRight size={12} className="text-(--brand)" />}
              </button>
            ))}
          </section>
        </div>

        {/* ---------- 右：任务工作区 ---------- */}
        <div className="space-y-4">
          {!activeRun && (
            <section className="rounded-2xl border border-dashed border-stone-300 bg-white p-10 text-center text-xs text-stone-400">
              左边挑一批评论、建个任务，这里会出现进度、指标、主题、明细与报告。
            </section>
          )}

          {activeRun && (
            <>
              <section className="space-y-3 rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h2 className="truncate text-sm font-semibold">{detail?.name ?? activeRun}</h2>
                    <p className="text-[11px] text-stone-400">
                      {runStatus || '未开始'} · {completed}/{totalRecords || '?'} 条
                      {failed > 0 && ` · 失败 ${failed}`}
                      {(detail?.use_mock as boolean) && ' · 演示数据'}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <button
                      onClick={() => void startAnalyze(activeRun, isRunning)}
                      disabled={busy === `analyze:${activeRun}` || isRunning}
                      title={isRunning ? '正在分析中' : '重新跑一遍（会覆盖已有分析结果）'}
                      className="flex items-center gap-1 rounded-md bg-(--brand) px-2.5 py-1 text-[11px] text-white disabled:opacity-40"
                    >
                      {busy === `analyze:${activeRun}` ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : (
                        <Play size={11} />
                      )}
                      {completed > 0 ? '重新分析' : '开始分析'}
                    </button>
                    {isRunning && (
                      <button
                        onClick={() => void cancelRun(activeRun)}
                        className="flex items-center gap-1 rounded-md border border-stone-200 px-2.5 py-1 text-[11px] text-stone-600 hover:border-red-300 hover:text-red-500"
                      >
                        <Square size={11} /> 停止
                      </button>
                    )}
                    <button
                      onClick={() => void clusterThemes(activeRun)}
                      disabled={busy === `cluster:${activeRun}`}
                      title="把零散信号归并成可读的开放主题（会调用模型并产生费用）"
                      className="flex items-center gap-1 rounded-md border border-stone-200 px-2.5 py-1 text-[11px] text-stone-600 hover:border-(--brand)"
                    >
                      {busy === `cluster:${activeRun}` ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : (
                        <Layers size={11} />
                      )}
                      主题归并
                    </button>
                    <button
                      onClick={() => void refreshActive()}
                      className="flex items-center gap-1 rounded-md border border-stone-200 px-2.5 py-1 text-[11px] text-stone-600 hover:border-(--brand)"
                    >
                      <RefreshCw size={11} /> 刷新
                    </button>
                  </div>
                </div>

                <div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-stone-100">
                    <div
                      className={clsx('h-full rounded-full transition-all', isRunning ? 'bg-(--brand)' : 'bg-emerald-500')}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-[10px] text-stone-400">
                    <span>
                      {pct}%{progress.eta_seconds ? ` · 预计还需 ${Math.ceil(Number(progress.eta_seconds) / 60)} 分钟` : ''}
                      {progress.current_source_label ? ` · ${String(progress.current_source_label)}` : ''}
                    </span>
                    <span>
                      已用 {Number(progress.actual_cost ?? 0).toFixed(3)}{' '}
                      {String((detail?.pricing as Record<string, unknown>)?.currency ?? 'CNY')} · 预估{' '}
                      {Number(progress.estimated_cost ?? 0).toFixed(3)}
                    </span>
                  </div>
                </div>

                {(exportPaths.results_csv || exportPaths.report_md) && (
                  <div className="flex flex-wrap items-center gap-2 border-t border-stone-100 pt-2 text-[11px]">
                    <span className="text-stone-400">导出</span>
                    {exportPaths.results_csv && (
                      <a
                        href={downloadHref(exportPaths.results_csv)}
                        className="flex items-center gap-1 text-stone-600 hover:text-(--brand)"
                      >
                        <ArrowDownToLine size={11} /> 分析结果 CSV
                      </a>
                    )}
                    {exportPaths.report_md && (
                      <a
                        href={downloadHref(exportPaths.report_md)}
                        className="flex items-center gap-1 text-stone-600 hover:text-(--brand)"
                      >
                        <ArrowDownToLine size={11} /> 洞察报告 MD
                      </a>
                    )}
                    {exportPaths.candidates_csv && (
                      <a
                        href={downloadHref(exportPaths.candidates_csv)}
                        className="flex items-center gap-1 text-stone-600 hover:text-(--brand)"
                      >
                        <ArrowDownToLine size={11} /> 候选用户 CSV
                      </a>
                    )}
                  </div>
                )}
              </section>

              <div className="flex flex-wrap items-center gap-1 rounded-xl border border-stone-200 bg-white p-1 text-[11px] shadow-sm">
                {tabs.map(({ key, label, icon: Icon, count }) => (
                  <button
                    key={key}
                    onClick={() => setTab(key)}
                    className={clsx(
                      'flex items-center gap-1 rounded-lg px-2.5 py-1.5 transition-colors',
                      tab === key ? 'bg-orange-50 font-medium text-(--brand)' : 'text-stone-600 hover:bg-stone-50',
                    )}
                  >
                    <Icon size={12} /> {label}
                    {typeof count === 'number' && count > 0 && (
                      <span className="text-stone-400">{count}</span>
                    )}
                  </button>
                ))}
              </div>

              {tab === 'overview' && (
                <section className="space-y-3">
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {OVERVIEW_METRICS.map(({ key, label }) => (
                      <div key={key} className="rounded-xl border border-stone-200 bg-white p-2.5 shadow-sm">
                        <div className="text-[10px] text-stone-400">{label}</div>
                        <div className="text-lg font-semibold text-stone-800">
                          {formatCount(Number(summary[key] ?? 0))}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <div className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
                      <h3 className="mb-2 text-xs font-semibold text-stone-700">主要沟通目的</h3>
                      {Object.keys((summary.primary_intent_counts as Record<string, number>) ?? {}).length === 0 && (
                        <p className="text-[11px] text-stone-400">还没有分析结果。</p>
                      )}
                      {Object.entries((summary.primary_intent_counts as Record<string, number>) ?? {})
                        .sort((a, b) => b[1] - a[1])
                        .map(([k, v]) => {
                          const pcts = (summary.primary_intent_percentages as Record<string, unknown>) ?? {}
                          const shot = percentOf(pcts[k])
                          return (
                            <div key={k} className="mb-1.5">
                              <div className="flex justify-between text-[11px] text-stone-600">
                                <span>{intentLabels[k] ?? k}</span>
                                <span className="text-stone-400">
                                  {formatCount(v)} · {shot.toFixed(1)}%
                                </span>
                              </div>
                              <div className="h-1 overflow-hidden rounded-full bg-stone-100">
                                <div
                                  className="h-full"
                                  style={{ width: `${Math.min(100, shot)}%`, backgroundColor: 'var(--brand)', opacity: 0.6 }}
                                />
                              </div>
                            </div>
                          )
                        })}
                    </div>

                    <div className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
                      <h3 className="mb-2 text-xs font-semibold text-stone-700">一次回复能解决吗</h3>
                      <div className="space-y-1">
                        {Object.entries((summary.single_video_stats as Record<string, unknown>) ?? {})
                          .map(([k, v]) => [k, metricOf(v)] as const)
                          .sort((a, b) => b[1].count - a[1].count)
                          .map(([k, v]) => (
                            <div key={k} className="flex items-center justify-between text-[11px] text-stone-600">
                              <span>{SINGLE_VIDEO_LABELS[k] ?? k}</span>
                              <span className="shrink-0 text-stone-400">
                                {formatCount(v.count)}
                                {v.coverage_pct !== undefined ? ` · ${v.coverage_pct.toFixed(1)}%` : ''}
                              </span>
                            </div>
                          ))}
                      </div>
                      <h3 className="mb-1 mt-3 text-xs font-semibold text-stone-700">与产品/内容契合度</h3>
                      <div className="space-y-1">
                        {Object.entries((summary.product_fit_counts as Record<string, number>) ?? {}).map(([k, v]) => (
                          <div key={k} className="flex items-center justify-between text-[11px] text-stone-600">
                            <span>{PRODUCT_FIT_LABELS[k] ?? k}</span>
                            <span className="text-stone-400">{formatCount(v)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
                    <h3 className="mb-2 text-xs font-semibold text-stone-700">信息信号覆盖率</h3>
                    <p className="mb-2 text-[10px] text-stone-400">同一评论可含多个信号，覆盖率之和可能超过 100%。</p>
                    <div className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
                      {Object.entries((summary.signal_counts as Record<string, number>) ?? {})
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 20)
                        .map(([k, v]) => {
                          const cov = metricOf(((summary.signal_coverage as Record<string, unknown>) ?? {})[k])
                          return (
                            <div key={k} className="flex items-center justify-between text-[11px] text-stone-600">
                              <span className="truncate">{signalLabels[k] ?? k}</span>
                              <span className="shrink-0 text-stone-400">
                                {formatCount(v)}
                                {cov.coverage_pct !== undefined ? ` · ${cov.coverage_pct.toFixed(1)}%` : ''}
                              </span>
                            </div>
                          )
                        })}
                    </div>
                  </div>
                </section>
              )}

              {tab === 'themes' && (
                <section className="space-y-2">
                  {themeProgress && (
                    <div className="rounded-xl border border-stone-200 bg-white px-3 py-2 text-[11px] text-stone-500 shadow-sm">
                      {String(themeProgress.message ?? '')}
                      {typeof themeProgress.progress_pct === 'number' && (
                        <span className="ml-2 text-stone-400">{themeProgress.progress_pct}%</span>
                      )}
                    </div>
                  )}
                  {themes.length === 0 && (
                    <div className="rounded-2xl border border-dashed border-stone-300 bg-white p-8 text-center text-xs text-stone-400">
                      还没有开放主题。评论分析跑完后点上方「主题归并」，把零散信号归并成可读主题。
                    </div>
                  )}
                  {themes.map((theme) => (
                    <div key={theme.theme_id} className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <h3 className="text-sm font-semibold text-stone-800">{theme.theme_name}</h3>
                        <div className="flex items-center gap-1.5 text-[10px]">
                          {theme.theme_type && (
                            <span className="rounded bg-stone-100 px-1.5 py-0.5 text-stone-500">{theme.theme_type}</span>
                          )}
                          {theme.relation_to_existing_hypotheses && (
                            <span className="rounded bg-orange-50 px-1.5 py-0.5 text-(--brand)">
                              {THEME_RELATION_LABELS[theme.relation_to_existing_hypotheses] ??
                                theme.relation_to_existing_hypotheses}
                            </span>
                          )}
                        </div>
                      </div>
                      {theme.definition && <p className="mt-1 text-[11px] leading-relaxed text-stone-600">{theme.definition}</p>}
                      <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-stone-400">
                        <span>{theme.stats?.comment_count ?? 0} 条</span>
                        <span>{theme.stats?.unique_user_count ?? 0} 名用户</span>
                        <span>{theme.stats?.video_count ?? 0} 个视频</span>
                        {theme.confidence !== undefined && <span>置信 {(theme.confidence * 100).toFixed(0)}%</span>}
                      </div>
                      {theme.implication && (
                        <p className="mt-2 rounded-lg bg-stone-50 px-2 py-1.5 text-[11px] text-stone-600">
                          含义：{theme.implication}
                        </p>
                      )}
                      {(theme.representative_quotes ?? []).length > 0 && (
                        <ul className="mt-2 space-y-1">
                          {(theme.representative_quotes ?? []).slice(0, 5).map((q, i) => (
                            <li key={i} className="border-l-2 border-stone-200 pl-2 text-[11px] text-stone-500">
                              {q}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </section>
              )}

              {tab === 'results' && (
                <section className="space-y-2">
                  <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-stone-200 bg-white p-2 text-[11px] shadow-sm">
                    <input
                      value={resultFilters.keyword}
                      onChange={(e) => setResultFilters((f) => ({ ...f, keyword: e.target.value }))}
                      placeholder="搜索评论 / 用户"
                      className="w-40 rounded-lg border border-stone-200 px-2 py-1 outline-none focus:border-(--brand)"
                    />
                    <select
                      value={resultFilters.primary_intent}
                      onChange={(e) => setResultFilters((f) => ({ ...f, primary_intent: e.target.value }))}
                      className="rounded-lg border border-stone-200 px-2 py-1"
                    >
                      <option value="">全部目的</option>
                      {Object.entries(intentLabels).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                    <select
                      value={resultFilters.single_video_relation}
                      onChange={(e) => setResultFilters((f) => ({ ...f, single_video_relation: e.target.value }))}
                      className="rounded-lg border border-stone-200 px-2 py-1"
                    >
                      <option value="">一次回复能否解决</option>
                      {Object.entries(SINGLE_VIDEO_LABELS).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                    <select
                      value={resultFilters.product_fit}
                      onChange={(e) => setResultFilters((f) => ({ ...f, product_fit: e.target.value }))}
                      className="rounded-lg border border-stone-200 px-2 py-1"
                    >
                      <option value="">全部契合度</option>
                      {Object.entries(PRODUCT_FIT_LABELS).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => void loadResults(activeRun, 1)}
                      className="rounded-lg bg-stone-800 px-2.5 py-1 text-white"
                    >
                      筛选
                    </button>
                    <span className="ml-auto text-stone-400">共 {formatCount(resultsTotal)} 条</span>
                  </div>

                  <div className="overflow-x-auto rounded-2xl border border-stone-200 bg-white shadow-sm">
                    <table className="w-full border-collapse text-[11px]">
                      <thead>
                        <tr className="bg-stone-50 text-left text-stone-500">
                          <th className="px-2 py-1.5 font-medium">评论</th>
                          <th className="px-2 py-1.5 font-medium">用户</th>
                          <th className="px-2 py-1.5 font-medium">目的</th>
                          <th className="px-2 py-1.5 font-medium">一次回复</th>
                          <th className="px-2 py-1.5 font-medium">契合</th>
                        </tr>
                      </thead>
                      <tbody>
                        {results.map((item) => (
                          <tr key={item.record_id} className="border-t border-stone-100 align-top">
                            <td className="max-w-md px-2 py-1.5 text-stone-700">
                              <div className="line-clamp-3 whitespace-pre-wrap break-words">
                                {item.source?.comment_text ?? ''}
                              </div>
                              {item.source?.comment_url && (
                                <a
                                  href={item.source.comment_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="mt-0.5 inline-flex items-center gap-0.5 text-[10px] text-stone-400 hover:text-(--brand)"
                                >
                                  <ExternalLink size={9} /> 原评论
                                </a>
                              )}
                            </td>
                            <td className="px-2 py-1.5 text-stone-600">
                              {item.source?.user_homepage_url ? (
                                <a
                                  href={item.source.user_homepage_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="hover:text-(--brand)"
                                >
                                  {item.source?.username ?? ''}
                                </a>
                              ) : (
                                item.source?.username ?? ''
                              )}
                              <div className="text-[10px] text-stone-400">{formatCount(item.source?.like_count ?? 0)} 赞</div>
                            </td>
                            <td className="px-2 py-1.5 text-stone-600">
                              {intentLabels[item.analysis?.primary_intent ?? ''] ?? item.analysis?.primary_intent ?? ''}
                            </td>
                            <td className="px-2 py-1.5 text-stone-600">
                              {SINGLE_VIDEO_LABELS[item.analysis?.single_video_relation ?? ''] ?? ''}
                            </td>
                            <td className="px-2 py-1.5 text-stone-600">
                              {PRODUCT_FIT_LABELS[item.analysis?.product_fit ?? ''] ?? ''}
                            </td>
                          </tr>
                        ))}
                        {results.length === 0 && (
                          <tr>
                            <td colSpan={5} className="px-2 py-8 text-center text-stone-400">
                              没有匹配的评论
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>

                  <div className="flex items-center justify-between text-[11px] text-stone-400">
                    <button
                      disabled={resultsPage <= 1}
                      onClick={() => void loadResults(activeRun, resultsPage - 1)}
                      className="rounded-lg border border-stone-200 px-2 py-1 disabled:opacity-40"
                    >
                      上一页
                    </button>
                    <span>
                      第 {resultsPage} / {Math.max(1, Math.ceil(resultsTotal / 20))} 页
                    </span>
                    <button
                      disabled={resultsPage >= Math.ceil(resultsTotal / 20)}
                      onClick={() => void loadResults(activeRun, resultsPage + 1)}
                      className="rounded-lg border border-stone-200 px-2 py-1 disabled:opacity-40"
                    >
                      下一页
                    </button>
                  </div>
                </section>
              )}

              {tab === 'report' && (
                <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-sm font-semibold">决策报告</h3>
                    <button
                      onClick={() => void loadReport(activeRun)}
                      className="text-[11px] text-stone-500 hover:text-(--brand)"
                    >
                      重新读取
                    </button>
                  </div>
                  {report ? (
                    <div className="max-h-[42rem] overflow-y-auto pr-1">{renderMarkdown(report)}</div>
                  ) : (
                    <p className="py-8 text-center text-xs text-stone-400">
                      还没有可读报告。分析跑完（必要时先做主题归并）再回来。
                    </p>
                  )}
                </section>
              )}

              {tab === 'narrative' && (
                <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-sm font-semibold">中文解读</h3>
                    <button
                      onClick={() => void generateNarrative(activeRun)}
                      disabled={busy === `narrative:${activeRun}`}
                      className="flex items-center gap-1 rounded-lg border border-stone-200 px-2.5 py-1 text-[11px] text-stone-600 hover:border-(--brand) disabled:opacity-40"
                    >
                      {busy === `narrative:${activeRun}` ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : (
                        <Wand2 size={11} />
                      )}
                      {narrative ? '重新生成' : '生成解读'}
                    </button>
                  </div>
                  {narrative ? (
                    <div className="space-y-1 whitespace-pre-wrap text-[12px] leading-relaxed text-stone-700">
                      {narrative}
                    </div>
                  ) : (
                    <p className="py-8 text-center text-xs text-stone-400">
                      用一句话把这份数据讲清楚。生成会调用模型，按 token 计费。
                    </p>
                  )}
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
