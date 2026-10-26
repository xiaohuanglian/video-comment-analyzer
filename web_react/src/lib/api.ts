// 后端 API 客户端 —— 对接现有 FastAPI (127.0.0.1:8766)

export interface AutomationCandidate {
  id: string
  comment_id: string
  video_id: string
  video_title: string
  video_url: string
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
  enabled: boolean
  config: Record<string, unknown>
  funnel: {
    pending_review: number
    approved: number
    sent: number
    failed: number
    rejected: number
  }
  stats: Record<string, number>
  cycle: { running: boolean; last_run_at: string; last_summary: string; last_error: string }
  sender: {
    can_send: boolean
    wait_reason: string
    cookie_cached: boolean
    account?: { uname?: string; mid?: number; level?: number }
    login_flow?: { running: boolean; message: string }
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

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${text.slice(0, 200)}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  automationStatus: () => req<AutomationStatus>('/automation/status'),
  candidates: (status = 'pending_review', limit = 60) =>
    req<AutomationCandidate[]>(`/automation/candidates?status=${status}&limit=${limit}`),
  approve: (id: string, draft: string) =>
    req<{ ok: boolean; item: AutomationCandidate; warnings: string[] }>(
      `/automation/candidates/${id}/approve`,
      { method: 'POST', body: JSON.stringify({ draft }) },
    ),
  reject: (id: string) =>
    req<{ ok: boolean }>(`/automation/candidates/${id}/reject`, { method: 'POST' }),
  bulkRejectRules: () =>
    req<{ ok: boolean; rejected: number }>('/automation/candidates/bulk-reject', {
      method: 'POST',
    }),
  bulkApproveLlm: () =>
    req<{ ok: boolean; approved: number; skipped_no_draft: number; skipped_similar: number }>(
      '/automation/candidates/bulk-approve',
      { method: 'POST' },
    ),
  biliLogin: () =>
    req<{ ok: boolean; message: string }>('/automation/bili-login', { method: 'POST' }),
  retract: (id: string) =>
    req<{ ok: boolean }>(`/automation/candidates/${id}/retract`, { method: 'POST' }),
  redraft: (id: string) =>
    req<{ ok: boolean; item: AutomationCandidate }>(`/automation/candidates/${id}/draft`, {
      method: 'POST',
    }),
  collectNow: () => req('/automation/collect-now', { method: 'POST' }),
  screenCollected: (max_candidates = 50, auto_draft = true) =>
    req<{ ok: boolean; message: string }>('/automation/screen-collected', {
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
    req<{ body: string; changes: string[] }>('/writer/humanize', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  writerDelete: (id: string) => req(`/writer/${id}`, { method: 'DELETE' }),

  automationConfigUpdate: (patch: Record<string, unknown>) =>
    req('/automation/config', { method: 'POST', body: JSON.stringify(patch) }),
}
