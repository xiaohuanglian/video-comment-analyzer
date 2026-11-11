// 后端 API 客户端 —— 对接现有 FastAPI (127.0.0.1:8766)

export interface AutomationCandidate {
  id: string
  comment_id: string
  video_id: string
  video_title: string
  video_url: string
  comment_url?: string
  platform?: string
  commenter: string
  comment_text: string
  like_count: number
  age_hours: number
  signal: string
  tier: 'A' | 'B' | string
  worth?: number
  intent?: string
  lane?: 'help' | 'engage' | string
  match_reason?: string
  screened_by?: string
  persona?: string
  sub_replies?: string[]
  sub_reply_count?: number
  reply_like_count?: number
  reply_rcount?: number
  engagement_at?: string
  engagement_note?: string
  reply_sub_preview?: string[]
  draft: string
  lint_warnings: string[]
  draft_source: string
  status: 'pending_review' | 'approved' | 'sent' | 'failed' | 'rejected' | 'sending'
  created_at: string
  decided_at?: string
  sent_at?: string
  send_error?: string
  attempts: number
  note?: string
}

export interface AutomationStatus {
  platform?: string
  enabled: boolean
  config: Record<string, unknown>
  funnel: {
    pending_review: number
    approved: number
    /** 正在发送中；>0 且长时间不动说明有卡死条目 */
    sending?: number
    sent: number
    failed: number
    rejected: number
  }
  stats: Record<string, number>
  cycle: { running: boolean; last_run_at: string; last_summary: string; last_error: string }
  sender: {
    can_send: boolean
    wait_reason: string
    cookie_cached: boolean | null
    account?: { uname?: string; mid?: number; level?: number }
    login_flow?: { running: boolean; message: string }
    pause_until?: string
    pause_reason?: string
    [k: string]: unknown
  }
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  ts: number
}

export interface CrawlerStatus {
  status: 'idle' | 'running' | 'stopping' | 'error'
  platform?: string | null
  crawler_type?: string | null
  started_at?: string | null
  finished_at?: string | null
  error_message?: string | null
  comments_crawled?: number | null
  comments_target?: number | null
  progress_updated_at?: string | null
  result_kind?: string | null
  result_title?: string | null
  result_message?: string | null
}

export interface CrawlerLog {
  id: number
  timestamp: string
  level: string
  message: string
}

export interface CrawlerStartPayload {
  platform: string
  crawler_type: 'search' | 'detail' | 'creator'
  keywords?: string
  specified_ids?: string
  max_notes_count?: number
  max_comments_count?: number
  enable_sub_comments?: boolean
  headless?: boolean
}

/** 本地已采数据盘点(采集页「本地已采数据」概览) */
export interface LocalDataBatch {
  date: string
  source: 'manual' | 'automation'
  platform: string
  contents: number
  comments: number
  titles: string[]
}

export interface LocalDataSummary {
  platforms: Record<string, { comments: number; contents: number; batches: number }>
  batches: LocalDataBatch[]
}

export interface Topic {
  id: string
  ts: number
  video_id?: string
  video_title?: string
  video_url?: string
  comment_count?: number
  title: string
  signal?: string
  target_reader?: string
  core_tension?: string
  angle?: string
  material_entry?: string
  viral_score?: number
  evergreen_score?: number
  source?: string
  application_domain?: string
  problem_type?: string
  origin_note?: string
  status?: string
}

export interface TopicBoard {
  total: number
  domains: string[]
  problem_types: string[]
  grid: Record<string, Record<string, number>>
  status: Record<string, number>
  recent_drafts: string[]
  has_strategy: boolean
}

export interface PlanTopic {
  title: string
  source: string
  application_domain: string
  problem_type: string
  origin_note: string
  why: string
}

export interface PlanResult {
  board_summary: string
  topics: PlanTopic[]
}

export interface Strategy {
  niche?: string
  target_audience?: string
  monetization?: string
  tone_rules?: string[]
  forbidden?: string[]
  reference_styles?: string[]
  goal?: string
  evidence?: string
  updated_at?: string
  exists?: boolean
}

export interface CostEntry {
  ts: number
  date: string
  feature: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  duration_ms: number
  ok: boolean
  error?: string
}

export interface CostBucket {
  calls: number
  ok_calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost: number
}

export interface CostSummary {
  pricing: { input_per_1m: number; output_per_1m: number; configured: boolean }
  total: CostBucket & { first_ts?: number | null }
  today: CostBucket
  by_feature: (CostBucket & { feature: string })[]
  by_model: (CostBucket & { model: string })[]
}

export interface BoostVideoResult {
  topic_title: string
  bili_refs: string[]
  auto_found?: { title: string; channel: string; view_count: number; url: string }[]
  link_refs: { url: string; title: string; ok: boolean }[]
  reference_review: { source: string; take: string }[]
  titles: string[]
  script: string
  why_strong: string
}

export interface Draft {
  id: string
  ts: number
  format: 'xhs' | 'koubo'
  topic_title: string
  title: string
  body: string
  tags: string[]
  shots: string[]
  /** 发布前质检单（生成时自动附带，改稿后可调 /writer/check 复检） */
  quality?: ContentQuality
}

export type QualitySeverity = 'high' | 'medium' | 'low'

export interface QualityIssue {
  code: string
  severity: QualitySeverity
  message: string
  excerpt: string
  suggestion: string
}

export interface LlmReview {
  verdict?: string
  scroll_risk?: { excerpt?: string; why?: string; fix?: string }[]
  weak_parts?: { excerpt?: string; missing?: string }[]
  keep?: string[]
}

/** 发布前质检单：纯代码判定，给分数与可溯源命中片段，不拦截发布 */
export interface ContentQuality {
  version: string
  platform: string
  platform_label: string
  score: number
  blocking: boolean
  checks: string[]
  issues: QualityIssue[]
  metrics: Record<string, number | boolean>
  llm_review?: LlmReview | null
}

/** 稿件体检：一批稿件的质检汇总（飞轮的学习环节） */
export interface QualitySummary {
  count: number
  avg_score: number
  blocking: number
  blocking_rate: number
  buckets: Record<string, number>
  by_platform: Record<string, { count: number; avg_score: number }>
  top_issues: { code: string; label: string; count: number }[]
  trend: number[]
  generated_at?: number
}

/** 表现数据（人手动回填）。null = 还没拿到，0 = 确实是 0，两者不能混 */
export interface PublishMetrics {
  views: number | null
  likes: number | null
  comments: number | null
  saves: number | null
  shares: number | null
  follows: number | null
}

/** 一条已发布作品（本工作台不发布，只登记人自己发的） */
export interface PublishRecord {
  id: string
  created_at: number
  updated_at: number
  published_at: string
  platform: string
  title: string
  url: string
  draft_id: string
  topic_id: string
  topic_title: string
  quality_score: number | null
  quality_blocking: boolean | null
  quality_codes: string[]
  metrics: PublishMetrics
  notes: string
}

export interface PublishBrief {
  id: string
  title: string
  platform: string
  published_at: string
  quality_score: number | null
  views: number
  interaction_rate: number
  url: string
}

export interface PublishBucket {
  key: string
  label: string
  count: number
  avg_views: number
  avg_interaction_rate: number
}

/** 质检分 vs 实际表现的对账 */
export interface PublishAnalysis {
  total_records: number
  with_metrics: number
  pending_backfill: number
  buckets: Record<string, PublishBucket>
  by_platform: Record<string, { count: number; avg_views: number; avg_interaction_rate: number }>
  correlation: {
    n: number
    ready: boolean
    needed: number
    pearson_log_views: number | null
    note: string
  }
  top_views: PublishBrief[]
  bottom_views: PublishBrief[]
  top_interaction: PublishBrief[]
}

export interface UnregisteredDraft {
  id: string
  title: string
  format: string
  topic_title: string
  ts: number
  quality_score: number | null
  quality_blocking: boolean | null
}

export interface ReportSummary {
  id: string
  ts: number
  scope: string
  total_comments: number
  total_videos: number
  audience: string
  theme_count: number
  topic_count: number
  keywords?: string
}

export interface CommentReport {
  id: string
  ts: number
  scope: string
  keywords?: string
  total_comments: number
  total_videos: number
  top_videos: { title: string; comments: number }[]
  audience: string
  pain_themes: { theme: string; evidence: string; heat: string }[]
  reply_opportunities: { target: string; why: string; example: string }[]
  topic_hints: { title: string; signal: string; score: number }[]
  dos: string[]
  carry_over?: string
  raw?: string
  exists?: boolean
}

const BASE = '/api'

/** 后端统一错误信封里的字段（见 api/services/error_handlers.py） */
export interface ApiError extends Error {
  status: number
  /** 机器可读错误码，如 BAD_INPUT / NEED_LOGIN / RATE_LIMITED */
  code?: string
  /** 可执行建议 */
  hint?: string
  /** 限流/冷却时还需等待的秒数 */
  retryAfterSeconds?: number | null
}

/**
 * 把后端的错误体解析成人能看懂的一句话。
 *
 * 背景（2026-11-11）：后端把 HTTPException / 校验错误 / 未捕获异常
 * 统一成 `{ ok: false, error: { code, message, hint, retry_after_seconds } }`。
 * 前端原先只会抛 `${status} ${statusText}: ${原始 JSON 文本}`，
 * 用户看到的是 200 个字符的 JSON——等于没提示。
 */
export function describeError(status: number, statusText: string, raw: string): ApiError {
  let message = `${status} ${statusText}`
  let code: string | undefined
  let hint: string | undefined
  let retryAfterSeconds: number | null | undefined

  if (raw) {
    try {
      const body = JSON.parse(raw)
      const envelope = body?.error
      if (envelope && typeof envelope === 'object') {
        message = String(envelope.message || message)
        code = typeof envelope.code === 'string' ? envelope.code : undefined
        hint = typeof envelope.hint === 'string' ? envelope.hint : undefined
        retryAfterSeconds = envelope.retry_after_seconds ?? undefined
      } else if (typeof body?.detail === 'string') {
        message = body.detail
      }
    } catch {
      // 非 JSON（如网关返回 HTML）：退回状态码 + 截断文本
      message = `${status} ${statusText}: ${raw.slice(0, 200)}`
    }
  }

  const error = new Error(hint ? `${message}（${hint}）` : message) as ApiError
  error.status = status
  error.code = code
  error.hint = hint
  error.retryAfterSeconds = retryAfterSeconds
  return error
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw describeError(res.status, res.statusText, text)
  }
  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// 创作中台（creator-buddy 方法论 + 标题工坊 + 交付物）
// ---------------------------------------------------------------------------

export interface StudioSkill {
  id: string
  name: string
  description: string
  platform: string
  platform_label: string
  stage: string
  rel_path: string
  tags: string[]
}

export interface StudioTitleItem {
  text: string
  method: string
  hook: string
  score: number
  length: number
  breakdown: Record<string, number>
  notes: string[]
  risk: { level: 'low' | 'medium' | 'high'; flags: string[]; blocking: string[] }
  duplicate_of: string | null
  disqualified: boolean
  disqualify_reason: string
}

export interface StudioTitlePack {
  platform: string
  platform_label: string
  count: number
  valid_count: number
  items: StudioTitleItem[]
  methods_covered: string[]
  method_count: number
  diversity_ok: boolean
  recommendations: Record<string, { text: string; method: string; score: number }>
}

export interface StudioDraft {
  text: string
  platform: string
  rounds: { round: number; chars: number; blocking: string[]; issue_count: number }[]
  passed: boolean
  remaining_blocking: string[]
  issues: { code: string; excerpt: string }[]
  chars: number
}

export interface StudioDeliverable {
  format: string
  html?: string
  pages?: number
  shots?: {
    index: number
    start_s: number
    duration_s: number
    role: string
    text: string
    visual: string
  }[]
  total_duration_label?: string
  prompt?: string
  note?: string
  error?: string
}

export interface StudioRun {
  id: string
  created_at: string
  format: string
  format_label: string
  topic: string
  style_slug: string
  skill_id: string
  title: string
  titles: StudioTitlePack | null
  titles_error: string
  draft: StudioDraft
  deliverable: StudioDeliverable
}

export interface StudioContext {
  audience: string
  forbidden_claims: string
  persona: string
  tone: string
  styles: { slug: string; chars: number }[]
  formats: Record<string, { label: string; quality: string; deliver: string }>
  platforms: Record<string, string>
}
export interface YouTubeTarget {
  channel: string
  source: string
  video_count: number
  selected: { id: string; title: string; views: number; url: string }[]
}

export interface YouTubeJob {
  id: string
  status: 'running' | 'done' | 'error'
  started_at: string
  finished_at: string
  params: { limit: number; channels: string[]; max_comments: number; sort: string }
  progress: { done: number; total: number; current: string; rows: number }
  result: Record<string, unknown> | null
  error: string
}

export interface YouTubeSummary {
  total_comments: number
  out_dir: string
  channels: {
    channel: string
    comments: number
    videos: number
    csv: string
    top_liked: { content: string; like_count: number }[]
  }[]
}

export type AutomationPlatform = 'bili' | 'xhs' | 'dy'

const p = (platform: AutomationPlatform) => `&platform=${platform}`


// ---------------------------------------------------------------------------
// 评论洞察（/api/analysis/*）
//
// 2026-11-11：这套后端一直存在（47 条路由），但 React 面板从未接入——
// 旧的 web_static/insight.js 在移除旧前端时被删掉了，UI 没跟着重建。
// 这里补齐最小可用的一套类型与调用。
// ---------------------------------------------------------------------------

export interface InsightSourceFile {
  path: string
  name?: string
  comment_count?: number
  category?: string
  creator?: string
  folder?: string
  platform_hint?: string
  video_label?: string
  size?: number
  modified_at?: number
}

export interface InsightSourceGroup {
  category: string
  file_count: number
  comment_count: number
  creators: { creator: string; files: InsightSourceFile[]; file_count: number; comment_count: number }[]
}

export interface InsightRunSummary {
  run_id: string
  name?: string
  total_records?: number
  created_at?: string
  status?: string
  completed?: number
  failed?: number
  analysis_limit?: number
  use_mock?: boolean
  profile_id?: string
}

export interface InsightPricing {
  model_name: string
  base_url: string
  input_price: number
  output_price: number
  currency: string
  provider_label?: string
}

export interface InsightProfile {
  profile_id: string
  name?: string
  is_builtin?: boolean
  [k: string]: unknown
}

export interface InsightCreateRunPayload {
  name?: string
  file_paths: string[]
  analysis_limit?: number
  use_mock?: boolean
  research_targets?: string
  profile_id?: string
  model?: { model_name?: string; base_url?: string; budget_limit?: number }
}

export interface InsightRunDetail extends InsightRunSummary {
  progress?: Record<string, unknown>
  config?: Record<string, unknown>
  estimate?: Record<string, unknown>
}

export interface InsightReport {
  run_id: string
  markdown?: string
  research?: Record<string, unknown>
  has_report?: boolean
  waiting_for_open_themes?: boolean
}


// ---------------------------------------------------------------------------
// 切场景（/api/topics/scenario/*）
//
// 回答的是「除了我想到的那几个场景，还有哪些地方能打」。
// 六个轴：身份/困境/替代/触发/否认/邻近——不从产品功能反推，从用户生活情境出发。
// ---------------------------------------------------------------------------

export interface ScenarioAxis {
  key: string
  label: string
  description: string
}

export interface Scenario {
  name: string
  axis: string
  axis_label: string
  /** 具体触发情境（When & Why），写得像一个人的真实瞬间 */
  trigger: string
  pain: string
  /** 我们的产品在这里具体提供什么 */
  entry: string
  /** 可直接粘进搜索框的用户原话 */
  keywords: string[]
  platforms: string[]
  why_underused: string
  /** 低/中/高 + 一句理由；诚实评估比乐观更有用 */
  competitor_density: string
  /** 以下全部由代码回算，模型不许报数字 */
  hits: number | null
  users: number | null
  videos: number | null
  sample_quotes: string[]
  /** 有信号 / 弱信号 / 无信号 */
  verdict: string
}

export interface ScenarioPlanResult {
  positioning: string
  audience: string
  axes: ScenarioAxis[]
  scenarios: Scenario[]
  warnings: string[]
  verified: boolean
  message: string
}

export interface ScenarioVerifyResult {
  scenarios: Scenario[]
  stats: {
    total: number
    with_signal?: number
    weak_signal?: number
    no_signal?: number
    verified: number
    axis_coverage?: Record<string, number>
    warnings?: string[]
  }
  corpus_size: number
}

export const api = {
  automationStatus: (platform: AutomationPlatform = 'bili') =>
    req<AutomationStatus>(`/automation/status?platform=${platform}`),
  candidates: (status = 'pending_review', limit = 60, platform: AutomationPlatform = 'bili') =>
    req<AutomationCandidate[]>(`/automation/candidates?status=${status}&limit=${limit}${p(platform)}`),
  approve: (id: string, draft: string, platform: AutomationPlatform = 'bili') =>
    req<{ ok: boolean; item: AutomationCandidate; warnings: string[] }>(
      `/automation/candidates/${id}/approve?platform=${platform}`,
      { method: 'POST', body: JSON.stringify({ draft }) },
    ),
  reject: (id: string, platform: AutomationPlatform = 'bili') =>
    req<{ ok: boolean }>(`/automation/candidates/${id}/reject?platform=${platform}`, { method: 'POST' }),
  bulkRejectRules: (platform: AutomationPlatform = 'bili') =>
    req<{ ok: boolean; rejected: number }>(`/automation/candidates/bulk-reject?platform=${platform}`, {
      method: 'POST',
    }),
  refreshEngagement: (platform: AutomationPlatform = 'bili') =>
    req<{ ok: boolean; updated: number; with_activity: { id: string; like: number; rcount: number; subs: string[] }[] }>(
      `/automation/candidates/refresh-engagement?platform=${platform}`,
      { method: 'POST' },
    ),
  candidateHumanTouch: (id: string, platform: AutomationPlatform = 'bili') =>
    req<{ ok: boolean; item_id: string; report: string }>(
      `/automation/candidates/${id}/human-touch?platform=${platform}`,
      { method: 'POST' },
    ),
  bulkApproveLlm: (platform: AutomationPlatform = 'bili') =>
    req<{ ok: boolean; approved: number; skipped_no_draft: number; skipped_similar: number }>(
      `/automation/candidates/bulk-approve?platform=${platform}`,
      { method: 'POST' },
    ),
  biliLogin: () =>
    req<{ ok: boolean; message: string }>('/automation/bili-login', { method: 'POST' }),
  senderResume: (platform: AutomationPlatform = 'bili') =>
    req<{ ok: boolean; message: string }>(`/automation/sender-resume?platform=${platform}`, { method: 'POST' }),
  retract: (id: string, platform: AutomationPlatform = 'bili') =>
    req<{ ok: boolean }>(`/automation/candidates/${id}/retract?platform=${platform}`, { method: 'POST' }),
  redraft: (id: string, platform: AutomationPlatform = 'bili') =>
    req<{ ok: boolean; item: AutomationCandidate }>(`/automation/candidates/${id}/draft?platform=${platform}`, {
      method: 'POST',
    }),
  collectNow: (platform: AutomationPlatform = 'bili', mode: 'list' | 'search' | '' = '') =>
    req(`/automation/collect-now?platform=${platform}${mode ? `&mode=${mode}` : ''}`, { method: 'POST' }),
  screenCollected: (max_candidates = 50, auto_draft = true, platform: AutomationPlatform = 'bili') =>
    req<{ ok: boolean; message: string }>(`/automation/screen-collected?platform=${platform}`, {
      method: 'POST',
      body: JSON.stringify({ max_candidates, auto_draft }),
    }),

  chatHistory: () => req<ChatMessage[]>('/chat/history'),
  chatSend: (text: string) =>
    req<ChatMessage>('/chat/send', { method: 'POST', body: JSON.stringify({ text }) }),
  chatClear: () => req<{ ok: boolean }>('/chat/clear', { method: 'POST' }),

  crawlerStatus: () => req<CrawlerStatus>('/crawler/status'),
  crawlerStart: (payload: CrawlerStartPayload) =>
    req('/crawler/start', { method: 'POST', body: JSON.stringify(payload) }),
  crawlerStop: () => req('/crawler/stop', { method: 'POST' }),
  crawlerStatusFresh: () => req<CrawlerStatus>('/crawler/status?refresh_progress=true'),
  crawlerLogs: (limit = 30) =>
    req<{ logs: CrawlerLog[] }>(`/crawler/logs?limit=${limit}`),
  crawlerLocalData: () => req<LocalDataSummary>('/crawler/local-data'),

  topicsList: () => req<Topic[]>('/topics/list'),
  topicBoard: () => req<TopicBoard>('/topics/board'),
  topicPlan: (seed_ideas: string) =>
    req<PlanResult>('/topics/plan', { method: 'POST', body: JSON.stringify({ seed_ideas }) }),
  topicBatchAdd: (topics: PlanTopic[]) =>
    req<{ inserted: number; skipped: string[]; total: number }>('/topics/batch', {
      method: 'POST',
      body: JSON.stringify({ topics }),
    }),
  topicBatchDelete: (ids: string[]) =>
    req<{ ok: boolean; total: number }>('/topics/batch-delete', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  strategyGet: () => req<Strategy>('/strategy'),
  strategySave: (s: Partial<Strategy>) =>
    req<Strategy>('/strategy', { method: 'PUT', body: JSON.stringify(s) }),
  costsSummary: () => req<CostSummary>('/costs/summary'),
  costsLedger: (limit = 20) => req<CostEntry[]>(`/costs/ledger?limit=${limit}`),
  // ---- 模型网关配置（服务端持久化，脱敏返回）----
  modelSettingsGet: () =>
    req<{ configured: boolean; base_url: string; model_name: string; api_key_masked: string }>(
      '/growth/settings/model',
    ),
  modelSettingsSave: (payload: { base_url?: string; model_name?: string; api_key?: string }) =>
    req<{ configured: boolean; base_url: string; model_name: string; api_key_masked: string }>(
      '/growth/settings/model',
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  modelSettingsTest: (payload: { base_url?: string; model_name?: string; api_key?: string } = {}) =>
    req<{ ok: boolean; error?: string; reply?: string }>('/growth/settings/model/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  modelSettingsClear: () => req<Record<string, unknown>>('/growth/settings/model', { method: 'DELETE' }),


  wechatLibrary: () => req<unknown[]>('/wechat/library'),
  wechatDelete: (id: string) => req(`/wechat/library/${id}`, { method: 'DELETE' }),
  wechatArticle: (url: string) =>
    req<unknown>('/wechat/article', { method: 'POST', body: JSON.stringify({ url }) }),
  wechatCollection: (url: string) =>
    req<unknown>('/wechat/collection', { method: 'POST', body: JSON.stringify({ url }) }),
  wechatTask: () => req<unknown>('/wechat/task'),
  topicGenerate: (video_id?: string) =>
    req<Topic>('/topics/generate', { method: 'POST', body: JSON.stringify({ video_id }) }),
  topicDelete: (id: string) => req(`/topics/${id}`, { method: 'DELETE' }),
  topicBoostVideo: (
    topic_title: string,
    competitor_links: string[],
    personal_style = '',
    auto_search = true,
  ) =>
    req<BoostVideoResult>('/topics/boost-video', {
      method: 'POST',
      body: JSON.stringify({ topic_title, competitor_links, personal_style, auto_search }),
    }),

  commentsAnalyze: (date?: string, keywords?: string) =>
    req<CommentReport>('/comments/analyze', {
      method: 'POST',
      body: JSON.stringify({ date, keywords }),
    }),
  commentsReports: () => req<ReportSummary[]>('/comments/reports'),
  commentsReport: (id: string) => req<CommentReport>(`/comments/reports/${id}`),
  commentsReportDelete: (id: string) => req(`/comments/reports/${id}`, { method: 'DELETE' }),

  youvibeQuery: (queries: { name: string; endpoint: string; params?: Record<string, unknown> }[]) =>
    req<Record<string, unknown>>('/youvibe/query', {
      method: 'POST',
      body: JSON.stringify({ queries }),
    }),

  writerList: () => req<Draft[]>('/writer/list'),
  writerGenerate: (
    topic_title: string,
    topic_context: string,
    format: 'xhs' | 'koubo' | 'skeleton',
    style = 'checklist',
  ) =>
    req<Draft>('/writer/generate', {
      method: 'POST',
      body: JSON.stringify({ topic_title, topic_context, format, style }),
    }),
  writerHumanize: (text: string) =>
    req<{ body: string; changes: string[]; quality?: ContentQuality }>('/writer/humanize', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  writerCheck: (title: string, body: string, format: string) =>
    req<ContentQuality>('/writer/check', {
      method: 'POST',
      body: JSON.stringify({ title, body, format }),
    }),
  writerCritic: (title: string, body: string, format: string) =>
    req<LlmReview>('/writer/critic', {
      method: 'POST',
      body: JSON.stringify({ title, body, format }),
    }),
  writerQualitySummary: (limit = 50) =>
    req<QualitySummary>(`/writer/quality/summary?limit=${limit}`),

  publishRecords: () => req<PublishRecord[]>('/publish/records'),
  publishDrafts: () => req<UnregisteredDraft[]>('/publish/drafts'),
  publishAnalysis: () => req<PublishAnalysis>('/publish/analysis'),
  // ---- 评论洞察 ----
  insightSources: () =>
    req<{ groups?: InsightSourceGroup[]; total_files?: number; total_comments?: number }>(
      '/analysis/sources',
    ),
  insightRuns: () => req<{ runs: InsightRunSummary[] }>('/analysis/runs'),
  insightProfiles: () => req<{ profiles: InsightProfile[] }>('/analysis/profiles'),
  insightPricing: () => req<InsightPricing>('/analysis/pricing'),
  insightCreateRun: (payload: InsightCreateRunPayload) =>
    req<{ run_id: string; reused?: boolean; total_records?: number }>('/analysis/runs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  insightRun: (runId: string) => req<InsightRunDetail>(`/analysis/runs/${runId}`),
  insightAnalyze: (runId: string, payload: Record<string, unknown> = {}) =>
    req<Record<string, unknown>>(`/analysis/runs/${runId}/analyze`, {
      method: 'POST',
      body: JSON.stringify({ background: true, ...payload }),
    }),
  insightReport: (runId: string) => req<InsightReport>(`/analysis/runs/${runId}/research-report`),
  insightCancel: (runId: string) =>
    req<Record<string, unknown>>(`/analysis/runs/${runId}/cancel`, { method: 'POST' }),
  insightRetryFailed: (runId: string, payload: Record<string, unknown> = {}) =>
    req<Record<string, unknown>>(`/analysis/runs/${runId}/retry-failed`, {
      method: 'POST',
      body: JSON.stringify({ background: true, ...payload }),
    }),
  insightNarrative: (runId: string) =>
    req<{ narrative?: string; error?: string }>(`/analysis/runs/${runId}/insight-narrative`),
  publishCreate: (body: Record<string, unknown>) =>
    req<PublishRecord>('/publish/records', { method: 'POST', body: JSON.stringify(body) }),
  publishUpdate: (id: string, body: Record<string, unknown>) =>
    req<PublishRecord>(`/publish/records/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  publishDelete: (id: string) => req(`/publish/records/${id}`, { method: 'DELETE' }),
  writerDelete: (id: string) => req(`/writer/${id}`, { method: 'DELETE' }),

  automationConfigUpdate: (patch: Record<string, unknown>, platform: AutomationPlatform = 'bili') =>
    req(`/automation/config?platform=${platform}`, { method: 'POST', body: JSON.stringify(patch) }),
  studioSkills: (platform = '', stage = '', q = '') =>
    req<{ items: StudioSkill[]; stages: { stage: string; count: number }[]; stats: { total: number; by_platform: Record<string, number> } }>(
      `/studio/skills?platform=${encodeURIComponent(platform)}&stage=${encodeURIComponent(stage)}&q=${encodeURIComponent(q)}`,
    ),
  studioContext: () => req<StudioContext>('/studio/context'),
  studioTitles: (payload: {
    topic: string
    body?: string
    platform: string
    count?: number
  }) =>
    req<StudioTitlePack>('/studio/titles', { method: 'POST', body: JSON.stringify(payload) }),
  studioReviewTitles: (payload: {
    candidates: { text: string; method?: string }[]
    topic?: string
    body?: string
    platform: string
  }) =>
    req<StudioTitlePack>('/studio/titles/review', { method: 'POST', body: JSON.stringify(payload) }),
  studioCheckTitle: (payload: { text: string; platform: string; body?: string }) =>
    req<{
      ok: boolean
      length: number
      limit: number
      score: number
      risk: { level: string; flags: string[]; blocking: string[] }
      notes: string[]
    }>('/studio/titles/check', { method: 'POST', body: JSON.stringify(payload) }),
  studioDeliver: (payload: {
    format: 'wechat' | 'xhs' | 'storyboard' | 'cover'
    title?: string
    body?: string
    tags?: string[]
    style?: string
  }) => req<StudioDeliverable>('/studio/deliver', { method: 'POST', body: JSON.stringify(payload) }),
  studioCoverCheck: (path: string, platform = 'wechat') =>
    req<Record<string, unknown>>('/studio/cover/check', {
      method: 'POST',
      body: JSON.stringify({ path, platform }),
    }),
  studioPipeline: (payload: {
    topic: string
    format: 'wechat' | 'xhs' | 'video'
    style_slug?: string
    material?: string
    title?: string
    count?: number
    with_titles?: boolean
    deliverable?: string
    skill_id?: string
  }) => req<StudioRun>('/studio/pipeline', { method: 'POST', body: JSON.stringify(payload) }),
  studioRuns: (limit = 20) => req<StudioRun[]>(`/studio/runs?limit=${limit}`),
  // 三源选题：评论痛点 / 洗稿台 / 事件（api/routers/topics.py 新增接口）
  // 轻量数据指纹：选题中心用它判断「数据有没有变」，不变就不重拉、不重算

  // ---- 切场景 ----
  scenarioPlan: (payload: {
    positioning?: string
    audience?: string
    value?: string
    existing_hint?: string
    limit?: number
  }) =>
    req<ScenarioPlanResult>('/topics/scenario/plan', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  scenarioVerify: (scenarios: Scenario[]) =>
    req<ScenarioVerifyResult>('/topics/scenario/verify', {
      method: 'POST',
      body: JSON.stringify({ scenarios }),
    }),
  scenarioAdopt: (scenarios: Scenario[]) =>
    req<{ ok: boolean; target_scenarios: unknown[] }>('/topics/scenario/adopt', {
      method: 'POST',
      body: JSON.stringify({ scenarios }),
    }),

  topicVersion: () =>
    req<{
      version: string
      topics: { count: number }
      corpus: { files: number; signature: string }
      youtube_corpus: { files: number; signature: string }
    }>('/topics/version'),
  topicDemand: (mode: 'llm' | 'rules' = 'llm', limit = 8, source: 'bili' | 'youtube' = 'bili') =>
    req<TopicDemandResult>(
      `/topics/demand?mode=${mode}&limit=${limit}&source=${source}`,
    ),
  topicFromDemand: (payload: TopicDemandInput) =>
    req<TopicWriteResult>('/topics/from-demand', { method: 'POST', body: JSON.stringify(payload) }),
  topicFromEvent: (payload: {
    material: string
    personal_style?: string
    application_domain?: string
    create_topics?: boolean
  }) =>
    req<TopicFromEventResult>('/topics/from-event', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  /** manual_text：拿不到字幕时直接粘贴的参考正文/口播稿（≤20000 字），传了就不必给 links */
  topicRewritePlan: (payload: {
    topic_title?: string
    links: string[]
    personal_style?: string
    manual_text?: string
  }) =>
    req<RewritePlan>('/topics/rewrite/plan', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  topicRewriteDraft: (payload: {
    plan: RewritePlan | Record<string, unknown>
    links: string[]
    personal_style?: string
  }) =>
    req<TopicRewriteDraftResult>('/topics/rewrite/draft', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  /** 一键直出：内部先出方案再成稿，方案只留痕不挡路（约 2-3 分钟） */
  /** manual_text 同 topicRewritePlan：没有链接也能出稿 */
  topicRewriteOnce: (payload: {
    topic_title?: string
    links: string[]
    personal_style?: string
    manual_text?: string
  }) =>
    req<TopicRewriteOnceResult>('/topics/rewrite/once', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  topicPatchStatus: (id: string, status: TopicStatus) =>
    req<Topic>(`/topics/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  topicStats: () => req<TopicStats>('/topics/stats'),
  youtubeTargets: (limit = 3) => req<{ targets: YouTubeTarget[] }>(`/youtube/comments/targets?limit=${limit}`),
  youtubeCollect: (payload: {
    limit?: number
    channels?: string[]
    max_comments?: number
    sort?: 'top' | 'newest'
  }) => req<YouTubeJob>('/youtube/comments/collect', { method: 'POST', body: JSON.stringify(payload) }),
  youtubeJob: (id: string) => req<YouTubeJob>(`/youtube/comments/jobs/${id}`),
  youtubeJobs: (limit = 10) => req<YouTubeJob[]>(`/youtube/comments/jobs?limit=${limit}`),
  youtubeSummary: () => req<YouTubeSummary>('/youtube/comments/summary'),
  youtubeReport: (payload: { channels?: string[]; keywords?: string }) =>
    req<CommentReport>('/youtube/comments/report', { method: 'POST', body: JSON.stringify(payload) }),
}

// ---------------------------------------------------------------------------
// 三源选题的类型（评论驱动 / 洗稿驱动 / 事件驱动）
//   数字全部由后端用真实评论统计，模型只负责分组与起名。
// ---------------------------------------------------------------------------

export type TopicStatus = 'planned' | 'drafting' | 'drafted' | 'published' | 'dropped'

/** 一条证据评论（原文，不加工） */
export interface DemandEvidence {
  text: string
  likes: number
  video_title: string
}

/** 一个「一群人反复没被满足的需求」簇 */
export interface DemandCluster {
  theme: string
  need: string
  problem_type: string
  users: number
  videos: number
  comments: number
  likes: number
  score: number
  /** 只有 mode=llm 分组时才有 */
  why_worth_writing?: string
  video_titles: string[]
  evidence: DemandEvidence[]
  signals?: Record<string, number>
  phrases?: string[]
  source?: string
}

export interface DemandCorpus {
  comments: number
  videos: number
  /** 求资料/求网盘这类已被剔除的条数 */
  resource_asks: number
  candidates: number
  /** 这份结果基于哪一版评论语料；与 /topics/version 的 corpus.signature 比对即可判断是否过期 */
  signature?: string
}

export interface TopicDemandResult {
  mode: 'llm' | 'rules' | 'empty'
  /** 语料来源：bili = 自己受众的 B 站评论；youtube = 对标频道英文评论 */
  source?: 'bili' | 'youtube'
  corpus: DemandCorpus
  /** mode=rules 且带此字段 = 模型分组失败已降级 */
  fallback_reason?: string
  clusters: DemandCluster[]
}

/** 入库请求：需求数字与证据原样带过去，方便日后复核 */
export interface TopicDemandInput {
  theme: string
  need?: string
  problem_type?: string
  application_domain?: string
  why_worth_writing?: string
  users: number
  videos: number
  comments: number
  likes: number
  evidence: DemandEvidence[]
}

export interface TopicWriteResult {
  inserted: number
  skipped: string[]
  total: number
  topic?: Topic
}

/** 事件卡里的一条事实（claim 可回溯到原文摘录 evidence） */
export interface EventFact {
  claim: string
  evidence: string
}

export interface EventAngle {
  title: string
  problem_type: string
  why: string
}

export interface EventCard {
  facts: EventFact[]
  stance: string
  why_now: string
  audience: string
  angles: EventAngle[]
  format: string
  /** 事实对不上原文的地方，要用小字提醒人 */
  grounding_problems: string[]
}

export interface TopicFromEventResult {
  card: EventCard
  topics: Topic[]
  inserted: number
  skipped: string[]
}

export interface RewriteSource {
  url: string
  platform: string
  title: string
  chars: number
  error: string
}

/** 洗稿第一步：拆解参考 + 差异化方案（还没落库，等人拍板） */
export interface RewritePlan {
  topic_title: string
  reference_digest: string[]
  keep: string[]
  drop: string[]
  your_angle: string
  differentiation: string[]
  outline: string[]
  originality_risk: string
  go_no_go: string
  sources: RewriteSource[]
}

export interface RewriteDraft {
  title: string
  titles: string[]
  body: string
  self_check: string
}

export interface TopicRewriteDraftResult {
  draft: RewriteDraft
  topic: Topic
  inserted: number
  draft_record: Record<string, unknown> | null
  /** 撞了库里同名选题：成稿已存草稿箱，但没动旧选题的状态 */
  duplicate_warning?: string
}

export interface TopicStats {
  total: number
  by_source: Record<string, number>
  by_status: Record<string, number>
  missing_origin: number
}

/** 一键直出：一次调用跑完方案 + 成稿；方案照样返回，供事后回溯 */
export interface TopicRewriteOnceResult {
  draft: RewriteDraft
  plan: RewritePlan
  topic: Topic
  draft_record: Record<string, unknown> | null
  /** 非空就提示人看一眼（后端目前放的是 go/no-go 结论原文） */
  warning: string
  /** 撞了库里同名选题：成稿已存草稿箱，但没动旧选题的状态 */
  duplicate_warning?: string

}
