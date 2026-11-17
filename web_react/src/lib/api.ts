// 后端 API 客户端 —— 对接现有 FastAPI (127.0.0.1:8766)
export interface ReplyAttachment {
    attachment_id: string;
    extension: string;
    mime_type: string;
    size: number;
    width: number;
    height: number;
    original_name: string;
}
export interface AutomationCandidate {
    id: string;
    comment_id: string;
    profile_id?: string;
    attachments?: ReplyAttachment[];
    need_quote?: string;
    matched_offering?: string;
    profile_name?: string;
    reply_goal?: string;
    reply_mode?: 'recommend' | 'trust';
    product_source_outdated?: boolean;
    campaign_key?: string;
    profile_snapshot?: Record<string, unknown>;
    draft_review?: {
        status: string;
        reason?: string;
        strategy?: string;
        need_quote?: string;
        matched_offering?: string;
        bridge_reason?: string;
    };
    marketing_audit?: {
        profile_name: string;
        decision: string;
        reason: string;
        issues?: string[];
        suggested_reply?: string;
    };
    video_id: string;
    video_title: string;
    video_url: string;
    comment_url?: string;
    platform?: string;
    commenter: string;
    comment_text: string;
    like_count: number;
    age_hours: number;
    signal: string;
    tier: 'A' | 'B' | string;
    worth?: number;
    intent?: string;
    lane?: 'help' | 'engage' | string;
    contact?: string;
    video_description?: string;
    match_reason?: string;
    screened_by?: string;
    persona?: string;
    sub_replies?: string[];
    sub_reply_count?: number;
    /** 这一条要做什么：回复某个具体的人，还是直接发根评论（评在视频下） */
    action?: 'reply' | 'hot_comment' | string;
    /** 这个视频的策略结论：同一视频既有根评论又有回复时为 both（两条都做） */
    video_route?: 'reply' | 'hot_comment' | 'both' | string;
    /** 热评竞争强度：cold / open / contested / crowded / too_small */
    competition?: string;
    reply_like_count?: number;
    reply_rcount?: number;
    engagement_at?: string;
    engagement_note?: string;
    reply_sub_preview?: string[];
    draft: string;
    lint_warnings: string[];
    draft_source: string;
    status: 'pending_review' | 'approved' | 'sent' | 'failed' | 'rejected' | 'sending';
    created_at: string;
    decided_at?: string;
    sent_at?: string;
    send_error?: string;
    attempts: number;
    note?: string;
}
export interface AutomationStatus {
    platform?: string;
    enabled: boolean;
    config: Record<string, unknown>;
    funnel: {
        pending_review: number;
        approved: number;
        /** 正在发送中；>0 且长时间不动说明有卡死条目 */
        sending?: number;
        sent: number;
        failed: number;
        rejected: number;
    };
    stats: Record<string, number>;
    cycle: {
        campaign?: {
            profile_id?: string;
        };
        running: boolean;
        last_run_at: string;
        last_summary: string;
        last_error: string;
        stage?: string;
        content_review?: {
            video_id: string;
            title: string;
            description: string;
            decision: string;
            reason: string;
        }[];
    };
    sender: {
        can_send: boolean;
        wait_reason: string;
        cookie_cached: boolean | null;
        account?: {
            uname?: string;
            mid?: number;
            level?: number;
        };
        login_flow?: {
            running: boolean;
            message: string;
        };
        pause_until?: string;
        pause_reason?: string;
        [k: string]: unknown;
    };
}
export interface CrawlerStatus {
    status: 'idle' | 'running' | 'stopping' | 'error';
    platform?: string | null;
    crawler_type?: string | null;
    started_at?: string | null;
    finished_at?: string | null;
    error_message?: string | null;
    comments_crawled?: number | null;
    comments_target?: number | null;
    progress_updated_at?: string | null;
    error_code?: string | null;
    error_hint?: string | null;
    retry_after_seconds?: number | null;
    result_kind?: string | null;
    result_title?: string | null;
    result_message?: string | null;
}
export interface CrawlerLog {
    id: number;
    timestamp: string;
    level: string;
    message: string;
}
export interface CrawlerStartPayload {
    platform: string;
    crawler_type: 'search' | 'detail' | 'creator';
    keywords?: string;
    specified_ids?: string;
    max_notes_count?: number;
    max_comments_count?: number;
    enable_sub_comments?: boolean;
    headless?: boolean;
}
/** 本地已采数据盘点(采集页「本地已采数据」概览) */
export interface LocalDataBatch {
    date: string;
    source: 'manual' | 'automation';
    platform: string;
    contents: number;
    comments: number;
    titles: string[];
}
export interface LocalDataSummary {
    platforms: Record<string, {
        comments: number;
        contents: number;
        batches: number;
    }>;
    batches: LocalDataBatch[];
}
/** 小红书关键词笔记（只有笔记、没有评论；采集页「笔记列表」用） */
export interface XhsNoteItem {
    note_id: string;
    keyword: string;
    title: string;
    author: string;
    note_type: string;
    liked: number;
    collected: number;
    comments: number;
    url: string;
}
export interface XhsNotesResponse {
    batch: string;
    batches: {
        batch: string;
        created_at: string;
        total: number;
    }[];
    total: number;
    limit: number;
    offset: number;
    items: XhsNoteItem[];
    keyword_counts: Record<string, number>;
}
export interface ProfileBrief {
    profile_id: string;
    name: string;
    niche: string;
    target_audience: string;
    is_active: boolean;
    is_configured: boolean;
    updated_at: string;
}
export interface Strategy {
    profile_id?: string;
    name?: string;
    domain?: string;
    research_goal?: string;
    is_configured?: boolean;
    is_builtin?: boolean;
    niche?: string;
    target_audience?: string;
    monetization?: string;
    tone_rules?: string[];
    forbidden?: string[];
    reference_styles?: string[];
    goal?: string;
    evidence?: string;
    target_scenarios?: {
        name?: string;
        axis?: string;
        trigger?: string;
        keywords?: string[];
    }[];
    updated_at?: string;
    exists?: boolean;
    /** 当前生效的档案（不同产品不能混用定位，所以这是显式状态） */
    active_profile_id?: string;
    is_active?: boolean;
    profiles?: ProfileBrief[];
}
export interface CostBucket {
    calls: number;
    ok_calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cost: number;
}
export interface CostSummary {
    pricing: {
        input_per_1m: number;
        output_per_1m: number;
        configured: boolean;
    };
    total: CostBucket & {
        first_ts?: number | null;
    };
    today: CostBucket;
    by_feature: (CostBucket & {
        feature: string;
    })[];
    by_model: (CostBucket & {
        model: string;
    })[];
}
export interface ReportSummary {
    id: string;
    ts: number;
    scope: string;
    total_comments: number;
    total_videos: number;
    audience: string;
    theme_count: number;
    keywords?: string;
}
export interface CommentReport {
    id: string;
    ts: number;
    scope: string;
    keywords?: string;
    total_comments: number;
    total_videos: number;
    top_videos: {
        title: string;
        comments: number;
    }[];
    audience: string;
    pain_themes: {
        theme: string;
        evidence: string;
        heat: string;
    }[];
    reply_opportunities: {
        target: string;
        why: string;
        example: string;
    }[];
    dos: string[];
    carry_over?: string;
    raw?: string;
    exists?: boolean;
}
const BASE = '/api';
/** 后端统一错误信封里的字段（见 api/services/error_handlers.py） */
export interface ApiError extends Error {
    status: number;
    /** 机器可读错误码，如 BAD_INPUT / NEED_LOGIN / RATE_LIMITED */
    code?: string;
    /** 可执行建议 */
    hint?: string;
    /** 限流/冷却时还需等待的秒数 */
    retryAfterSeconds?: number | null;
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
    let message = `${status} ${statusText}`;
    let code: string | undefined;
    let hint: string | undefined;
    let retryAfterSeconds: number | null | undefined;
    if (raw) {
        try {
            const body = JSON.parse(raw);
            const envelope = body?.error;
            if (envelope && typeof envelope === 'object') {
                message = String(envelope.message || message);
                code = typeof envelope.code === 'string' ? envelope.code : undefined;
                hint = typeof envelope.hint === 'string' ? envelope.hint : undefined;
                retryAfterSeconds = envelope.retry_after_seconds ?? undefined;
            }
            else if (typeof body?.detail === 'string') {
                message = body.detail;
            }
        }
        catch {
            // 非 JSON（如网关返回 HTML）：退回状态码 + 截断文本
            message = `${status} ${statusText}: ${raw.slice(0, 200)}`;
        }
    }
    const error = new Error(hint ? `${message}（${hint}）` : message) as ApiError;
    error.status = status;
    error.code = code;
    error.hint = hint;
    error.retryAfterSeconds = retryAfterSeconds;
    return error;
}
export async function req<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${BASE}${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...init,
    });
    if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw describeError(res.status, res.statusText, text);
    }
    return res.json() as Promise<T>;
}
export interface YouTubeTarget {
    channel: string;
    source: string;
    video_count: number;
    selected: {
        id: string;
        title: string;
        views: number;
        url: string;
    }[];
}
export interface YouTubeJob {
    id: string;
    status: 'running' | 'done' | 'error';
    started_at: string;
    finished_at: string;
    params: {
        limit: number;
        channels: string[];
        max_comments: number;
        sort: string;
    };
    progress: {
        done: number;
        total: number;
        current: string;
        rows: number;
    };
    result: Record<string, unknown> | null;
    error: string;
}
export interface YouTubeSummary {
    total_comments: number;
    out_dir: string;
    channels: {
        channel: string;
        comments: number;
        videos: number;
        csv: string;
        top_liked: {
            content: string;
            like_count: number;
        }[];
    }[];
}
export type AutomationPlatform = 'bili' | 'xhs' | 'dy';
const p = (platform: AutomationPlatform) => `&platform=${platform}`;
// ---------------------------------------------------------------------------
// 评论洞察（/api/analysis/*）
//
// 2026-11-11：这套后端是一整条分析链路（路由、服务、测试都齐），
// 这里补齐前端需要的类型与调用，让 InsightPage 与后端契约对齐。
// ---------------------------------------------------------------------------
export interface InsightSourceFile {
    path: string;
    name?: string;
    comment_count?: number;
    category?: string;
    creator?: string;
    folder?: string;
    platform_hint?: string;
    video_label?: string;
    size?: number;
    modified_at?: number;
}
export interface InsightSourceGroup {
    category: string;
    file_count: number;
    comment_count: number;
    creators: {
        creator: string;
        files: InsightSourceFile[];
        file_count: number;
        comment_count: number;
    }[];
}
export interface InsightRunSummary {
    run_id: string;
    name?: string;
    total_records?: number;
    created_at?: string;
    status?: string;
    completed?: number;
    failed?: number;
    analysis_limit?: number;
    use_mock?: boolean;
    profile_id?: string;
    file_paths?: string[];
    project_id?: string;
    storage_dir?: string;
}
export interface InsightPricing {
    model_name: string;
    base_url: string;
    input_price: number;
    output_price: number;
    currency: string;
    provider_label?: string;
}
export interface InsightProfile {
    profile_id: string;
    name?: string;
    niche?: string;
    target_audience?: string;
    is_builtin?: boolean;
    is_configured?: boolean;
    intents?: Record<string, string>;
    signals?: Record<string, string>;
    [k: string]: unknown;
}
export interface InsightProfilesResponse {
    profiles: InsightProfile[];
    /** 2026-11-13：页面必须按「当前生效档案」初始化，否则永远停在内置 default。 */
    active_profile_id?: string;
}
export interface InsightResultsItem {
    record_id: string;
    analyzed_at?: string;
    usage?: {
        prompt_tokens?: number;
        completion_tokens?: number;
    };
    source: {
        comment_text?: string;
        comment_url?: string;
        username?: string;
        user_id?: string;
        user_homepage_url?: string;
        like_count?: number;
        reply_count?: number;
        video_title?: string;
        platform?: string;
        creator_type?: string;
        published_at?: string | null;
    };
    analysis?: {
        primary_intent?: string;
        signals?: string[];
        specific_problems?: string[];
        single_video_relation?: string;
        single_video_limitation_summary?: string;
        product_fit?: string;
        product_fit_reason?: string;
        evidence_quotes?: string[];
        new_signals?: {
            type?: string;
            text?: string;
            evidence_quote?: string;
        }[];
        potential_needs?: string[];
        confidence?: number;
    };
}
export interface InsightResultsResponse {
    total: number;
    page: number;
    page_size: number;
    items: InsightResultsItem[];
}
export interface InsightTheme {
    theme_id: string;
    theme_name: string;
    theme_type?: string;
    definition?: string;
    implication?: string;
    confidence?: number;
    relation_to_existing_hypotheses?: string;
    representative_quotes?: string[];
    record_ids?: string[];
    stats?: {
        comment_count?: number;
        unique_user_count?: number;
        source_file_count?: number;
        video_count?: number;
    };
}
export interface InsightThemesResponse {
    themes?: InsightTheme[];
    cluster_progress?: {
        status?: string;
        message?: string;
        progress_pct?: number;
        theme_count?: number;
        cost?: number;
        currency?: string;
        last_error?: string;
    };
    cluster_running?: boolean;
    warnings?: string[];
}
export interface InsightCreateRunPayload {
    name?: string;
    file_paths: string[];
    analysis_limit?: number;
    use_mock?: boolean;
    research_targets?: string;
    profile_id?: string;
    model?: {
        model_name?: string;
        base_url?: string;
        budget_limit?: number;
    };
}
export interface InsightRunDetail extends InsightRunSummary {
    progress?: Record<string, unknown>;
    config?: Record<string, unknown>;
    estimate?: Record<string, unknown>;
    summary?: Record<string, unknown>;
    pricing?: Record<string, unknown>;
    is_running?: boolean;
    export_paths?: Record<string, string>;
    document_warnings?: string[];
}
export interface InsightReport {
    run_id: string;
    markdown?: string;
    research?: Record<string, unknown>;
    has_report?: boolean;
    waiting_for_open_themes?: boolean;
}
// ---------------------------------------------------------------------------
// 切场景（/api/strategy/scenario/*）
//
// 回答的是「除了我想到的那几个场景，还有哪些地方能打」。
// 六个轴：身份/困境/替代/触发/否认/邻近——不从产品功能反推，从用户生活情境出发。
// ---------------------------------------------------------------------------
export interface ScenarioAxis {
    key: string;
    label: string;
    description: string;
}
export interface Scenario {
    name: string;
    axis: string;
    axis_label: string;
    /** 具体触发情境（When & Why），写得像一个人的真实瞬间 */
    trigger: string;
    pain: string;
    /** 我们的产品在这里具体提供什么 */
    entry: string;
    /** 可直接粘进搜索框的用户原话 */
    keywords: string[];
    platforms: string[];
    why_underused: string;
    /** 低/中/高 + 一句理由；诚实评估比乐观更有用 */
    competitor_density: string;
    /** 以下全部由代码回算，模型不许报数字 */
    hits: number | null;
    users: number | null;
    videos: number | null;
    sample_quotes: string[];
    /** 有信号 / 弱信号 / 无信号 */
    verdict: string;
}
export interface ScenarioPlanResult {
    positioning: string;
    audience: string;
    axes: ScenarioAxis[];
    scenarios: Scenario[];
    warnings: string[];
    verified: boolean;
    message: string;
}
export interface ScenarioVerifyResult {
    scenarios: Scenario[];
    stats: {
        total: number;
        with_signal?: number;
        weak_signal?: number;
        no_signal?: number;
        verified: number;
        axis_coverage?: Record<string, number>;
        warnings?: string[];
    };
    corpus_size: number;
}
export const api = {
    automationStatus: (platform: AutomationPlatform = 'bili', profileId = '') => req<AutomationStatus>(`/automation/status?platform=${platform}${profileId ? `&profile_id=${encodeURIComponent(profileId)}` : ''}`),
    candidates: (status = 'pending_review', limit = 60, platform: AutomationPlatform = 'bili', profileId = '') => req<AutomationCandidate[]>(`/automation/candidates?status=${status}&limit=${limit}${p(platform)}${profileId ? `&profile_id=${encodeURIComponent(profileId)}` : ''}`),
    approve: (id: string, draft: string, platform: AutomationPlatform = 'bili') => req<{
        ok: boolean;
        item: AutomationCandidate;
        warnings: string[];
    }>(`/automation/candidates/${id}/approve?platform=${platform}`, { method: 'POST', body: JSON.stringify({ draft }) }),
    reject: (id: string, platform: AutomationPlatform = 'bili') => req<{
        ok: boolean;
    }>(`/automation/candidates/${id}/reject?platform=${platform}`, { method: 'POST' }),
    bulkRejectRules: (platform: AutomationPlatform = 'bili', profileId = '') => req<{
        ok: boolean;
        rejected: number;
    }>(`/automation/candidates/bulk-reject?platform=${platform}&profile_id=${encodeURIComponent(profileId)}`, {
        method: 'POST',
    }),
    refreshEngagement: (platform: AutomationPlatform = 'bili') => req<{
        ok: boolean;
        updated: number;
        with_activity: {
            id: string;
            like: number;
            rcount: number;
            subs: string[];
        }[];
    }>(`/automation/candidates/refresh-engagement?platform=${platform}`, { method: 'POST' }),
    candidateHumanTouch: (id: string, platform: AutomationPlatform = 'bili') => req<{
        ok: boolean;
        item_id: string;
        report: string;
    }>(`/automation/candidates/${id}/human-touch?platform=${platform}`, { method: 'POST' }),
    bulkApproveLlm: (platform: AutomationPlatform = 'bili', profileId = '') => req<{
        ok: boolean;
        approved: number;
        skipped_no_draft: number;
        skipped_similar: number;
    }>(`/automation/candidates/bulk-approve?platform=${platform}&profile_id=${encodeURIComponent(profileId)}`, { method: 'POST' }),
    biliLogin: () => req<{
        ok: boolean;
        message: string;
    }>('/automation/bili-login', { method: 'POST' }),
    senderResume: (platform: AutomationPlatform = 'bili') => req<{
        ok: boolean;
        message: string;
    }>(`/automation/sender-resume?platform=${platform}`, { method: 'POST' }),
    retract: (id: string, platform: AutomationPlatform = 'bili') => req<{
        ok: boolean;
    }>(`/automation/candidates/${id}/retract?platform=${platform}`, { method: 'POST' }),
    redraft: (id: string, platform: AutomationPlatform = 'bili') => req<{
        ok: boolean;
        item: AutomationCandidate;
    }>(`/automation/candidates/${id}/draft?platform=${platform}`, {
        method: 'POST',
    }),
    collectNow: (platform: AutomationPlatform = 'bili', mode: 'list' | 'search' | '' = '', profileId = '', replyGoal = '', replyMode = 'recommend') => req(`/automation/collect-now?platform=${platform}${mode ? `&mode=${mode}` : ''}`, { method: 'POST', body: JSON.stringify({ profile_id: profileId, reply_goal: replyGoal, reply_mode: replyMode }) }),
    uploadReplyImage: (id: string, file: File, platform: AutomationPlatform = 'bili') => req<{
        ok: boolean;
        item: AutomationCandidate;
    }>(`/automation/candidates/${encodeURIComponent(id)}/attachments?platform=${platform}&filename=${encodeURIComponent(file.name)}`, {
        method: 'POST', headers: { 'Content-Type': file.type || 'application/octet-stream' }, body: file,
    }),
    removeReplyImage: (id: string, attachmentId: string, platform: AutomationPlatform = 'bili') => req<{
        ok: boolean;
        item: AutomationCandidate;
    }>(`/automation/candidates/${encodeURIComponent(id)}/attachments/${encodeURIComponent(attachmentId)}?platform=${platform}`, { method: 'DELETE' }),
    replyImageUrl: (id: string, attachmentId: string, platform: AutomationPlatform = 'bili') => `${BASE}/automation/candidates/${encodeURIComponent(id)}/attachments/${encodeURIComponent(attachmentId)}?platform=${platform}`,
    screenCollected: (max_candidates = 50, auto_draft = true, platform: AutomationPlatform = 'bili', profileId = '', replyGoal = '', replyMode = 'recommend') => req<{
        ok: boolean;
        message: string;
    }>(`/automation/screen-collected?platform=${platform}`, {
        method: 'POST',
        body: JSON.stringify({ max_candidates, auto_draft, profile_id: profileId, reply_goal: replyGoal, reply_mode: replyMode }),
    }),
    crawlerStart: (payload: CrawlerStartPayload) => req('/crawler/start', { method: 'POST', body: JSON.stringify(payload) }),
    crawlerStop: () => req('/crawler/stop', { method: 'POST' }),
    crawlerStatusFresh: () => req<CrawlerStatus>('/crawler/status?refresh_progress=true'),
    crawlerLogs: (limit = 30) => req<{
        logs: CrawlerLog[];
    }>(`/crawler/logs?limit=${limit}`),
    crawlerLocalData: () => req<LocalDataSummary>('/crawler/local-data'),
    xhsNotes: (params: {
        batch?: string;
        q?: string;
        sort?: string;
        limit?: number;
        offset?: number;
    } = {}) => {
        const qs = new URLSearchParams();
        if (params.batch)
            qs.set('batch', params.batch);
        if (params.q)
            qs.set('q', params.q);
        if (params.sort)
            qs.set('sort', params.sort);
        if (params.limit != null)
            qs.set('limit', String(params.limit));
        if (params.offset != null)
            qs.set('offset', String(params.offset));
        const tail = qs.toString();
        return req<XhsNotesResponse>(tail ? `/crawler/xhs-notes?${tail}` : '/crawler/xhs-notes');
    },
    strategyGet: (profileId?: string) => req<Strategy>(`/strategy${profileId ? `?profile_id=${encodeURIComponent(profileId)}` : ''}`),
    strategySave: (s: Partial<Strategy>) => req<Strategy>('/strategy', { method: 'PUT', body: JSON.stringify(s) }),
    strategyProfiles: () => req<{
        active_profile_id: string;
        profiles: ProfileBrief[];
    }>('/strategy/profiles'),
    strategyCreateProfile: (payload: {
        name: string;
        niche?: string;
        target_audience?: string;
        domain?: string;
    }) => req<{
        profile: Strategy;
        active_profile_id: string;
    }>('/strategy/profiles', {
        method: 'POST',
        body: JSON.stringify(payload),
    }),
    strategySetActive: (profileId: string) => req<{
        active_profile_id: string;
        profiles: ProfileBrief[];
    }>('/strategy/active', {
        method: 'PUT',
        body: JSON.stringify({ profile_id: profileId }),
    }),
    // ---- 引导式建档：3 个问题 → 一份可用档案 ----
    onboardingQuestions: () => req<{
        questions: {
            key: string;
            question: string;
            hint: string;
            placeholder: string;
        }[];
        required_count: number;
        already_configured: boolean;
        active_profile_id: string;
    }>('/strategy/onboarding/questions'),
    onboardingSubmit: (payload: {
        domain: string;
        target_audience: string;
        research_goal: string;
        name?: string;
        run_scenario?: boolean;
        scenario_limit?: number;
    }) => req<{
        profile: Strategy;
        active_profile_id: string;
        scenarios: {
            items: Scenario[];
            warnings: string[];
            verified: boolean;
        } | null;
        scenario_error: string;
        next_steps: string[];
    }>('/strategy/onboarding', { method: 'POST', body: JSON.stringify(payload) }),
    costsSummary: () => req<CostSummary>('/costs/summary'),
    // ---- 模型网关配置（服务端持久化，脱敏返回）----
    modelSettingsGet: () => req<{
        configured: boolean;
        base_url: string;
        model_name: string;
        api_key_masked: string;
    }>('/settings/model'),
    modelSettingsSave: (payload: {
        base_url?: string;
        model_name?: string;
        api_key?: string;
    }) => req<{
        configured: boolean;
        base_url: string;
        model_name: string;
        api_key_masked: string;
    }>('/settings/model', { method: 'POST', body: JSON.stringify(payload) }),
    modelSettingsTest: (payload: {
        base_url?: string;
        model_name?: string;
        api_key?: string;
    } = {}) => req<{
        ok: boolean;
        error?: string;
        reply?: string;
    }>('/settings/model/test', {
        method: 'POST',
        body: JSON.stringify(payload),
    }),
    commentsAnalyze: (date?: string, keywords?: string) => req<CommentReport>('/comments/analyze', {
        method: 'POST',
        body: JSON.stringify({ date, keywords }),
    }),
    commentsReports: () => req<ReportSummary[]>('/comments/reports'),
    commentsReport: (id: string) => req<CommentReport>(`/comments/reports/${id}`),
    commentsReportDelete: (id: string) => req(`/comments/reports/${id}`, { method: 'DELETE' }),
    // ---- 评论洞察 ----
    insightSources: () => req<{
        groups?: InsightSourceGroup[];
        total_files?: number;
        total_comments?: number;
    }>('/analysis/sources'),
    insightRuns: () => req<{
        runs: InsightRunSummary[];
    }>('/analysis/runs'),
    insightProfiles: () => req<InsightProfilesResponse>('/analysis/profiles'),
    insightPricing: () => req<InsightPricing>('/analysis/pricing'),
    insightCreateRun: (payload: InsightCreateRunPayload) => req<{
        run_id: string;
        reused?: boolean;
        total_records?: number;
    }>('/analysis/runs', {
        method: 'POST',
        body: JSON.stringify(payload),
    }),
    insightRun: (runId: string) => req<InsightRunDetail>(`/analysis/runs/${runId}`),
    insightAnalyze: (runId: string, payload: Record<string, unknown> = {}) => req<Record<string, unknown>>(`/analysis/runs/${runId}/analyze`, {
        method: 'POST',
        body: JSON.stringify({ background: true, ...payload }),
    }),
    insightReport: (runId: string) => req<InsightReport>(`/analysis/runs/${runId}/research-report`),
    insightCancel: (runId: string) => req<Record<string, unknown>>(`/analysis/runs/${runId}/cancel`, { method: 'POST' }),
    // 后端实际返回 {text, generated}；以前这里写成 {narrative} —— 页面永远读不到内容
    insightNarrative: (runId: string) => req<{
        text?: string;
        generated?: boolean;
        error?: string;
    }>(`/analysis/runs/${runId}/insight-narrative`),
    insightNarrativeGenerate: (runId: string, payload: Record<string, unknown> = {}) => req<{
        text?: string;
        generated?: boolean;
    }>(`/analysis/runs/${runId}/insight-narrative`, {
        method: 'POST',
        body: JSON.stringify(payload),
    }),
    insightResults: (runId: string, query: Record<string, string | number | boolean | undefined> = {}) => {
        const params = new URLSearchParams();
        for (const [k, v] of Object.entries(query)) {
            if (v === undefined || v === '' || v === null)
                continue;
            params.set(k, String(v));
        }
        const qs = params.toString();
        return req<InsightResultsResponse>(`/analysis/runs/${runId}/results/items${qs ? `?${qs}` : ''}`);
    },
    insightThemes: (runId: string) => req<InsightThemesResponse>(`/analysis/runs/${runId}/themes`),
    insightCluster: (runId: string, payload: Record<string, unknown> = {}) => req<Record<string, unknown>>(`/analysis/runs/${runId}/themes/cluster`, {
        method: 'POST',
        body: JSON.stringify({ background: true, ...payload }),
    }),
    automationConfigUpdate: (patch: Record<string, unknown>, platform: AutomationPlatform = 'bili') => req(`/automation/config?platform=${platform}`, { method: 'POST', body: JSON.stringify(patch) }),
    // 产品触达场景：搜索词建议、语料验证与人工采纳。
    // ---- 切场景 ----
    scenarioPlan: (payload: {
        positioning?: string;
        audience?: string;
        value?: string;
        existing_hint?: string;
        limit?: number;
    }) => req<ScenarioPlanResult>('/strategy/scenario/plan', {
        method: 'POST',
        body: JSON.stringify(payload),
    }),
    scenarioVerify: (scenarios: Scenario[]) => req<ScenarioVerifyResult>('/strategy/scenario/verify', {
        method: 'POST',
        body: JSON.stringify({ scenarios }),
    }),
    scenarioAdopt: (scenarios: Scenario[]) => req<{
        ok: boolean;
        target_scenarios: unknown[];
    }>('/strategy/scenario/adopt', {
        method: 'POST',
        body: JSON.stringify({ scenarios }),
    }),
    youtubeTargets: (limit = 3) => req<{
        targets: YouTubeTarget[];
    }>(`/youtube/comments/targets?limit=${limit}`),
    youtubeCollect: (payload: {
        limit?: number;
        channels?: string[];
        max_comments?: number;
        sort?: 'top' | 'newest';
    }) => req<YouTubeJob>('/youtube/comments/collect', { method: 'POST', body: JSON.stringify(payload) }),
    youtubeJob: (id: string) => req<YouTubeJob>(`/youtube/comments/jobs/${id}`),
    youtubeJobs: (limit = 10) => req<YouTubeJob[]>(`/youtube/comments/jobs?limit=${limit}`),
    youtubeSummary: () => req<YouTubeSummary>('/youtube/comments/summary'),
    youtubeReport: (payload: {
        channels?: string[];
        keywords?: string;
    }) => req<CommentReport>('/youtube/comments/report', { method: 'POST', body: JSON.stringify(payload) })
};
