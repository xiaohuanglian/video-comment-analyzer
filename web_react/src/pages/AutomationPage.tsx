import { useCallback, useEffect, useRef, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X, RefreshCw, AlertTriangle, CheckCircle2, Filter, Loader2 } from 'lucide-react'
import clsx from 'clsx'
import { useSearchParams } from 'react-router-dom'
import { api, type AutomationCandidate, type AutomationStatus, type AutomationPlatform, type ProfileBrief, type Strategy } from '../lib/api'
import CandidateCard from '../components/CandidateCard'
import ReplyPlanPanel from '../components/ReplyPlanPanel'

const TABS = [
  { key: 'pending_review', label: '待批准' },
  { key: 'approved', label: '已批准' },
  { key: 'sent', label: '已发送' },
  { key: 'failed', label: '失败' },
  { key: 'rejected', label: '已拒绝' },
] as const

const PLATFORM_TABS = [
  { key: 'bili', label: 'B站' },
  { key: 'xhs', label: '小红书' },
  { key: 'dy', label: '抖音' },
] as const

export default function AutomationPage() {
  const [params, setParams] = useSearchParams()
  const [platform, setPlatform] = useState<AutomationPlatform>(() => ['bili', 'xhs', 'dy'].includes(params.get('platform') ?? '') ? params.get('platform') as AutomationPlatform : 'bili')
  const profileId = params.get('profile') ?? ''
  const [profiles, setProfiles] = useState<ProfileBrief[]>([])
  const [taskProfile, setTaskProfile] = useState<Strategy | null>(null)
  const [replyGoal, setReplyGoal] = useState('')
  const [replyMode, setReplyMode] = useState('recommend')
  const canRun = !!taskProfile && taskProfile.profile_id === profileId && !!replyGoal.trim()
  const [tab, setTab] = useState<(typeof TABS)[number]['key']>('pending_review')
  const [items, setItems] = useState<AutomationCandidate[]>([])
  const [status, setStatus] = useState<AutomationStatus | null>(null)
  const [selected, setSelected] = useState<AutomationCandidate | null>(null)
  const [notice, setNotice] = useState('')
  const [humanTouchReport, setHumanTouchReport] = useState('')
  const [screening, setScreening] = useState(false)
  const [candidateLimit, setCandidateLimit] = useState(50)
  const [screenResult, setScreenResult] = useState('')
  const refreshVersion = useRef(0)

  useEffect(() => {
    api.strategyProfiles().then(result => setProfiles(result.profiles)).catch(e => setNotice(String(e)))
  }, [])
  useEffect(() => {
    let alive = true
    if (profileId && profileId !== '__unbound__') {
      api.strategyGet(profileId).then(profile => {
        if (!alive) return
        setTaskProfile(profile)
        setReplyGoal(profile.goal || profile.research_goal || '')
      }).catch(e => { if (alive) setNotice(String(e)) })
    }
    return () => { alive = false }
  }, [profileId])

  const refresh = useCallback(async () => {
    const version = ++refreshVersion.current
    try {
      const [s, list] = await Promise.all([api.automationStatus(platform, profileId), api.candidates(tab, 100, platform, profileId)])
      if (version !== refreshVersion.current) return null
      setStatus(s)
      // 价值评分优先，同分时新条目排前
      setItems(
        (list as AutomationCandidate[]).sort((a, b) =>
          (b.worth ?? 0) - (a.worth ?? 0) || (b.created_at || '').localeCompare(a.created_at || ''),
        ),
      )
      return s
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e))
      return null
    }
  }, [tab, platform, profileId])

  // 后台筛选/采集在跑时,自动进入轮询态(从别的页面回来也能续上,不用重新点)
  useEffect(() => {
    if (!status?.cycle?.running) return
    setScreening(true)
  }, [status?.cycle?.running])

  useEffect(() => {
    void refresh()
    const t = setInterval(refresh, screening ? 2000 : 15000)
    return () => clearInterval(t)
  }, [refresh, screening])

  // 筛选:触发后台任务;轮询由下方 useEffect 驱动,点完即可离开页面
  const runScreen = async () => {
    if (screening || !canRun) return
    setScreenResult('')
    setNotice('')
    try {
      await api.screenCollected(candidateLimit, true, platform, profileId, replyGoal, replyMode)
      setScreening(true)
    } catch (e) {
      setScreenResult(e instanceof Error ? e.message : String(e))
    }
  }

  // 轮询:筛选中每 2.5s 查状态,结束后展示摘要并刷新列表(超时 10 分钟兜底)
  useEffect(() => {
    if (!screening) return
    let alive = true
    const startedAt = Date.now()
    const tick = async () => {
      if (!alive) return
      try {
        const s = await api.automationStatus(platform, profileId)
        setStatus(s)
        if (!s.cycle.running) {
          if (s.cycle.last_error) {
            setScreenResult(`失败:${s.cycle.last_error}`)
          } else {
            try {
              const sum = JSON.parse(s.cycle.last_summary || '{}') as {
                comments?: number
                videos?: number
                funnel?: { excluded?: number; stale?: number; dedup?: number }
                llm_screen?: { examined?: number; not_examined?: number; rejected?: number; video_cap?: number; note?: string }
                new_candidates?: number
                llm_drafted?: number
                draft_filtered?: number
                routes?: { hot_comment?: number; reply?: number }
              }
              setScreenResult(
                `完成:扫描 ${sum.comments ?? '?'} 条评论/${sum.videos ?? '?'} 个视频 → ` +
                  `排除 ${sum.funnel?.excluded ?? 0}、超龄 ${sum.funnel?.stale ?? 0}、重复 ${sum.funnel?.dedup ?? 0} → ` +
                  `AI 已看 ${sum.llm_screen?.examined ?? 0} 条、淘汰 ${sum.llm_screen?.rejected ?? 0} 条、未看 ${sum.llm_screen?.not_examined ?? 0} 条 → ` +
                  `新候选 ${sum.new_candidates ?? 0} 条，其中根评论 ${sum.routes?.hot_comment ?? 0} 条、具体回复 ${sum.routes?.reply ?? 0} 条(AI 起草 ${sum.llm_drafted ?? 0} 条，因文案无合适切入点或质检失败过滤 ${sum.draft_filtered ?? 0} 条)` + (sum.llm_screen?.note ? `；${sum.llm_screen.note}` : ''),
              )
            } catch {
              setScreenResult('完成,但摘要解析失败,请看待批准列表')
            }
          }
          setScreening(false)
          await refresh()
          return
        }
      } catch {
        /* 网络抖动,下轮再查 */
      }
      if (Date.now() - startedAt > 10 * 60 * 1000) {
        setScreenResult('等待超时,后台仍在跑,稍后自行刷新看待批准')
        setScreening(false)
        return
      }
      setTimeout(tick, 2500)
    }
    tick()
    return () => {
      alive = false
    }
  }, [screening, platform, profileId]) // eslint-disable-line react-hooks/exhaustive-deps

  let rejectedExamples: { comment: string; reason: string; worth: number }[] = []
  let lastReview: { profile_id?: string; comments?: number; funnel?: { stale?: number; sub_context?: number; dedup?: number }; llm_screen?: { examined?: number; not_examined?: number; note?: string }; new_candidates?: number; routes?: { hot_comment?: number; reply?: number } } = {}
  try {
    const summary = JSON.parse(status?.cycle.last_summary || '{}')
    if (summary.profile_id === profileId) {
      lastReview = summary
      rejectedExamples = [...(summary.llm_screen?.rejected_examples ?? []), ...(summary.draft_rejected_examples ?? [])].slice(0, 20)
    }
  } catch { /* 兼容旧摘要 */ }

  return (
    <div className="mx-auto max-w-5xl px-6 py-6 space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold">回复自动化</h1>
            {/* 平台通道切换：B站 / 小红书（独立队列与节奏） */}
            <div className="flex rounded-lg border border-stone-200 bg-white p-0.5">
              {PLATFORM_TABS.map((pt) => (
                <button
                  key={pt.key}
                  onClick={() => {
                    setPlatform(pt.key)
                    setParams(prev => { const next = new URLSearchParams(prev); next.set('platform', pt.key); return next }, { replace: true })
                    setSelected(null)
                  }}
                  className={clsx(
                    'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                    platform === pt.key ? 'bg-(--brand) text-white' : 'text-stone-500 hover:text-stone-700',
                  )}
                >
                  {pt.label}
                </button>
              ))}
            </div>
          </div>
          <p className="text-xs text-stone-400">
            {platform === 'xhs'
              ? '小红书通道：竞品笔记/关键词采集 → 筛选 → 起草 → 硬校验 → 人批 → CDP 受控发送（撞风控自动停损）'
              : platform === 'dy'
                ? '抖音通道：对标视频/关键词采集 → 筛选 → 起草 → 硬校验 → 人批 → CDP 受控发送（发送默认关闭，撞风控自动停损）'
                : '存量评论 → 筛选目标 → LLM 起草 → lint → 人工批准 → 受控发送(采集在「采集」页)'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {status && (
            <span
              title="现在唯一在跑的是发送队列:每 20 秒检查一次有没有你批准的回复要发。不会自己采集、不会自己开网页找用户(自动采集已按你的要求关闭)"
              className={clsx(
                'cursor-help rounded-full px-3 py-1 text-xs font-medium',
                status.enabled ? 'bg-emerald-100 text-emerald-700' : 'bg-stone-200 text-stone-500',
              )}
            >
              {status.enabled ? '发送队列:待命' : '发送队列:暂停'}
            </span>
          )}
          {(platform === 'xhs' || platform === 'dy') && (
            <button
              onClick={async () => {
                try {
                  setNotice('采集周期已启动（后台运行），完成后自动刷新')
                  setScreening(true)
                  await api.collectNow(platform, '', profileId, replyGoal, replyMode)
                } catch (e) {
                  setNotice(e instanceof Error ? e.message : String(e))
                  setScreening(false)
                }
              }}
              disabled={screening || !canRun}
              className="flex items-center gap-1.5 rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-xs hover:border-(--brand) disabled:opacity-50"
            >
              {platform === 'xhs' ? '立即采集小红书(按配置的清单/关键词)' : '立即采集抖音(按配置的清单/关键词)'}
            </button>
          )}
          <label className="flex items-center gap-1 text-xs text-stone-500">
            待审上限
            <input type="number" min={1} max={500} value={candidateLimit} disabled={screening || !canRun}
              onChange={e => setCandidateLimit(Math.max(1, Math.min(500, Number(e.target.value) || 1)))}
              className="w-16 rounded border border-stone-200 px-2 py-1" />
          </label>
          <button
            onClick={() => void runScreen()}
            disabled={screening || !canRun}
            className="flex items-center gap-1.5 rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-xs hover:border-(--brand) disabled:opacity-50"
          >
            {screening ? <Loader2 size={13} className="animate-spin" /> : <Filter size={13} />}
            {screening ? '筛选中…后台在跑,可以离开这页,完成后自动刷新' : '从已采集数据筛选目标（读取全库，按时效与模型预算评估）'}
          </button>
          <button
            onClick={() => void refresh()}
            className="rounded-lg border border-stone-200 bg-white p-1.5 hover:border-(--brand)"
          >
            <RefreshCw size={13} />
          </button>
        </div>
      </header>
      <section className="space-y-3 rounded-xl border border-orange-200 bg-orange-50/40 p-4">
        <label className="block text-sm font-medium">这次为哪个产品做回复？
          <select aria-label="回复任务产品" value={profileId} disabled={screening} className="ml-3 rounded border border-stone-200 bg-white px-3 py-2"
            onChange={event => { setParams(prev => { const next = new URLSearchParams(prev); next.set('profile', event.target.value); return next }, { replace: true }); refreshVersion.current += 1; setScreenResult(''); setTaskProfile(null); setReplyGoal(''); setSelected(null); setItems([]) }}>
            <option value="">查看全部（请选产品后开始任务）</option>
            {profiles.filter(p => p.is_configured).map(p => <option key={p.profile_id} value={p.profile_id}>{p.name} · {p.profile_id}</option>)}
            <option value="__unbound__">历史条目：归属未记录</option>
          </select>
        </label>
        {taskProfile && taskProfile.profile_id === profileId ? <>
          <p className="text-xs text-stone-600">服务对象：{taskProfile.target_audience}</p>
          <label className="block text-sm">本次回复目标<textarea aria-label="本次回复目标" className="mt-1 w-full rounded border border-stone-200 bg-white p-2 text-sm" rows={2} value={replyGoal} disabled={screening} onChange={event => setReplyGoal(event.target.value)} /></label>
          <label className="block text-sm">回复方式 <select aria-label="回复方式" className="rounded border border-stone-200 bg-white px-2 py-1" value={replyMode} disabled={screening} onChange={event => setReplyMode(event.target.value)}>
            <option value="recommend">需求匹配时自然提产品名</option><option value="trust">只提供帮助，建立信任</option>
          </select></label>
          <p className="text-xs text-stone-500">筛选和草稿固定使用这份产品档案及本次目标；切换内容工具的当前档案不会改变已有条目。先答具体问题，相关时才提产品，发送仍需人工批准。</p>
        </> : <p className="text-xs text-amber-700">已有条目不会因切换产品自动改归属。历史条目需按明确产品重新筛选，才能确认适合谁、推荐什么。</p>}
      </section>
      {items.some(c => !c.profile_id) && <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">当前列表含 {items.filter(c => !c.profile_id).length} 条未绑定产品的历史草稿，并非按本次目标生成。请先选产品查看对应队列；历史文案需要重新核对需求与产品能力，不能直接沿用。</p>}
      {status?.platform === platform && <ReplyPlanPanel key={`${platform}:${profileId}`} platform={platform} status={status} profileId={profileId || undefined} replyGoal={replyGoal} replyMode={replyMode} onSaved={() => void refresh()} />}

      {status?.cycle.running && status.cycle.stage && <p className="text-sm text-stone-500">{status.cycle.stage}</p>}
      {lastReview.profile_id === profileId && !!profileId && !screening && <section aria-label="最近筛选结果" className="space-y-2 rounded-xl border border-stone-200 bg-white p-4 text-xs text-stone-600">
        <p>本产品最近筛选：读取 {lastReview.comments ?? 0} 条评论，{lastReview.funnel?.stale ?? 0} 条超出回复时效；AI 评估 {lastReview.llm_screen?.examined ?? 0} 条，尚未评估 {lastReview.llm_screen?.not_examined ?? 0} 条。</p>
        <p>新增具体回复 {lastReview.routes?.reply ?? 0} 条、根评论 {lastReview.routes?.hot_comment ?? 0} 条。根评论面向整个视频评论区，按竞争与活跃度选址，不代表找到了有匹配需求的人。</p>
        {!!lastReview.llm_screen?.note && <p className="text-amber-700">{lastReview.llm_screen.note}</p>}
      </section>}
      {!!status?.cycle.content_review?.length && (
        <details className="rounded-xl border border-stone-200 bg-white p-4 text-sm">
          <summary className="cursor-pointer">采集前内容预审（{status.cycle.content_review.length} 个视频，仅采入选视频的评论）</summary>
          <p className="mt-2 text-xs text-stone-500">依据标题和简介判断相关性；未读取完整视频，信息不足的暂缓采集。</p>
          {status.cycle.content_review.map(video => (
            <div key={video.video_id} className="mt-3 border-t border-stone-100 pt-2">
              <p>{video.decision === 'collect' ? '入选' : video.decision === 'skip' ? '跳过' : '待查看'} · {video.title}</p>
              <p className="mt-1 text-xs text-stone-600">{video.reason}</p>
              <p className="mt-1 line-clamp-3 text-xs text-stone-400">{video.description}</p>
            </div>
          ))}
        </details>
      )}
      {rejectedExamples.length > 0 && (
        <details className="rounded-xl border border-stone-200 bg-white p-4 text-sm">
          <summary className="cursor-pointer">查看 AI 淘汰样例（最多20条）</summary>
          {rejectedExamples.map((item, index) => <div key={index} className="mt-3 border-t border-stone-100 pt-2">
            <p>{item.comment}</p><p className="mt-1 text-xs text-stone-500">{item.worth}分 · {item.reason}</p>
          </div>)}
        </details>
      )}
      {(notice || screenResult) && (
        <div
          className={clsx(
            'flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm',
            screenResult.startsWith('完成')
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-amber-200 bg-amber-50 text-amber-700',
          )}
        >
          <AlertTriangle size={15} /> {screenResult || notice}
          <button
            className="ml-auto"
            onClick={() => {
              setNotice('')
              setScreenResult('')
            }}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* 漏斗 */}
      {status && (
        <div className="grid grid-cols-5 gap-2">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={clsx(
                'rounded-xl border px-3 py-2.5 text-center transition-colors',
                tab === t.key
                  ? 'border-(--brand) bg-orange-50'
                  : 'border-stone-200 bg-white hover:border-stone-300',
              )}
            >
              <div className="text-lg font-semibold text-stone-700">
                {status.funnel[t.key as keyof typeof status.funnel]}
              </div>
              <div className="text-xs text-stone-400">{t.label}</div>
            </button>
          ))}
        </div>
      )}

      {/*
        卡在 sending 的条目提示（2026-11-11）。
        原先 funnel 只统计 5 种状态，sending 既不在列表里也没有标签页，
        进程崩溃后留下的「发送中」条目在界面上完全消失——既发不出去，
        用户也看不到它存在。后端启动时会自动退回 approved，这里给可见性。
      */}
      {(status?.funnel?.sending ?? 0) > 0 && (
        <div className="flex items-start gap-2 rounded-xl border border-sky-200 bg-sky-50 px-4 py-2.5 text-xs text-sky-800">
          <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin" />
          <span>
            有 {status?.funnel?.sending} 条回复正在发送中。若长时间不动，说明上次发送被中断
            （进程退出/浏览器崩溃）；重启服务会自动退回「待发」并说明原因。
          </span>
        </div>
      )}

      {/* 发送通道状态:B站 Cookie 未就绪 / 小红书停损暂停 时显眼提醒 */}
      {status?.sender && platform === 'bili' && !status.sender.cookie_cached && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-700">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>
            发送通道未就绪:B站登录态失效(需要重新扫码登录)。你现在批准的回复会在队列里等待,
            登录恢复后按节奏自动发(间隔约 3 分钟、每日上限、发送时段内);不想等的话,点开条目用「去B站回复」手动回。
          </span>
        </div>
      )}
      {status?.sender && platform !== 'bili' && status.sender.pause_until && (
        <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-xs text-red-700">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span className="flex-1">
            发送已停损暂停:{status.sender.pause_reason || '发送撞风控'}（至 {String(status.sender.pause_until).slice(5, 16)}）。
            这是撞到风控后的自动保护,请先人工确认账号没被限流,再解除。
          </span>
          <button
            onClick={async () => {
              try {
                await api.senderResume(platform)
                setNotice('已解除发送暂停')
                await refresh()
              } catch (e) {
                setNotice(e instanceof Error ? e.message : String(e))
              }
            }}
            className="shrink-0 rounded-lg border border-red-300 bg-white px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
          >
            确认无碍,解除暂停
          </button>
        </div>
      )}
      {status?.sender && platform === 'xhs' && !status.sender.pause_until && (
        <div className="rounded-xl border border-stone-200 bg-stone-50 px-4 py-2 text-xs text-stone-500">
          小红书发送通道:依赖本机已登录小红书的浏览器(CDP 调试端口 9222)保持开启;
          草稿经硬校验(链接/联系方式/引流话术一律拦)、逐条人工批准后才发送,日上限与间隔比B站更保守。
        </div>
      )}
      {status?.sender && platform === 'dy' && !status.sender.pause_until && (
        <div className="rounded-xl border border-stone-200 bg-stone-50 px-4 py-2 text-xs text-stone-500">
          抖音通道:采集/筛选/起草/人工批准已就绪;发送默认关闭——依赖本机已登录抖音的浏览器(CDP 9222),
          且草稿经硬校验、逐条人批后才发送。启用发送前，请核实本页通道状态与人工批准队列。
        </div>
      )}

      {/* 列表 */}
      <div className="space-y-2">
        {tab === 'pending_review' && profileId && items.some((c) => c.screened_by !== 'llm') && (
          <button
            onClick={async () => {
              const n = items.filter((c) => c.screened_by !== 'llm').length
              if (!window.confirm(`一键拒绝 ${n} 条旧规则筛的遗留条目?(LLM 精筛的条目不受影响)`)) return
              try {
                const res = await api.bulkRejectRules(platform, profileId)
                setNotice(`已清掉 ${res.rejected} 条旧规则筛条目`)
                await refresh()
              } catch (e) {
                setNotice(e instanceof Error ? e.message : String(e))
              }
            }}
            className="w-full rounded-xl border border-dashed border-stone-300 bg-stone-50 py-2 text-xs text-stone-500 hover:border-red-300 hover:text-red-500"
          >
            清掉旧规则筛的遗留条目({items.filter((c) => c.screened_by !== 'llm').length} 条,一键拒绝)
          </button>
        )}
        {tab === 'pending_review' && profileId && profileId !== '__unbound__' && items.some((c) => c.screened_by === 'llm') && (
          <button
            onClick={async () => {
              const n = items.filter((c) => c.screened_by === 'llm' && (c.draft || '').trim()).length
              if (!window.confirm(`批量批准 ${n} 条 LLM 精筛条目(以当前草稿入队,之后自动发送)?`)) return
              try {
                const res = await api.bulkApproveLlm(platform, profileId)
                const parts = [`已批准 ${res.approved} 条`]
                if (res.skipped_similar) parts.push(`${res.skipped_similar} 条因与近期内容过于相似被拦(需改写)`)
                if (res.skipped_no_draft) parts.push(`${res.skipped_no_draft} 条无草稿跳过`)
                setNotice(parts.join(','))
                await refresh()
              } catch (e) {
                setNotice(e instanceof Error ? e.message : String(e))
              }
            }}
            className="w-full rounded-xl border border-dashed border-orange-300 bg-orange-50/60 py-2 text-xs font-medium text-(--brand) hover:bg-orange-50"
          >
            批量批准 LLM 精筛条目({items.filter((c) => c.screened_by === 'llm' && (c.draft || '').trim()).length} 条有草稿)
          </button>
        )}
        {tab === 'sent' && platform === 'bili' && items.length > 0 && (
          <button
            onClick={async () => {
              try {
                setNotice('正在回采B站实时互动…')
                const res = await api.refreshEngagement(platform)
                const act = res.with_activity
                setNotice(
                  act.length
                    ? `已更新 ${res.updated} 条;有互动的 ${act.length} 条:${act.map((a) => `👍${a.like}/回${a.rcount}`).join('、')}`
                    : `已更新 ${res.updated} 条,暂无人理睬(继续等,B站互动是慢热型)`,
                )
                await refresh()
              } catch (e) {
                setNotice(e instanceof Error ? e.message : String(e))
              }
            }}
            className="w-full rounded-xl border border-dashed border-emerald-300 bg-emerald-50/60 py-2 text-xs font-medium text-emerald-700 hover:bg-emerald-50"
          >
            刷新互动数据(回采B站:我方回复的赞/被回复)
          </button>
        )}
        {items.length === 0 && (
          <div className="space-y-3 rounded-xl border border-stone-200 bg-white px-5 py-8 text-sm text-stone-600">
            <p>当前产品在「{TABS.find(t => t.key === tab)?.label}」中没有条目。</p>
            {profileId && profileId !== '__unbound__' && tab === 'pending_review' && !screening && (
              lastReview.profile_id === profileId ? <>
                <p>最近一次读取 {lastReview.comments ?? 0} 条评论：{lastReview.funnel?.stale ?? 0} 条超出回复时效，{lastReview.funnel?.sub_context ?? 0} 条楼中楼仅作上下文，{lastReview.funnel?.dedup ?? 0} 条重复或已处理；AI 已评估 {lastReview.llm_screen?.examined ?? 0} 条、尚未评估 {lastReview.llm_screen?.not_examined ?? 0} 条，新增 {lastReview.new_candidates ?? 0} 条。</p>
                {!!lastReview.llm_screen?.note && <p className="text-amber-700">{lastReview.llm_screen.note}</p>}
                <p>零条不等于没有潜在需求。若 AI 尚未评估且多数评论超龄，请先核对回复时效；重跑同样条件不会改变结果。</p>
              </> : <p>尚无该产品的筛选记录。切换产品不会给旧草稿改归属；可用上方按钮重新评估已采集评论，无需重新爬取。当前只考虑最近 {String(status?.config.freshness_b_hours ?? 168)} 小时发布的评论，旧评论会被跳过。</p>
            )}
            {screening && <p>正在评估已采集评论，完成后自动刷新；不会批准或发送。</p>}
          </div>
        )}
        {items.map((c) => (
          <CandidateCard
            key={c.id}
            c={c}
            onClick={() => setSelected(c)}
            onApprove={async (cc) => {
              try {
                const res = await api.approve(cc.id, cc.draft, platform)
                setNotice(res.warnings?.length ? `已批准,但草稿有 ${res.warnings.length} 条样式提醒:${res.warnings[0]}` : '已批准,排队发送')
                await refresh()
              } catch (e) {
                setNotice(e instanceof Error ? e.message : String(e))
              }
            }}
            onReject={async (cc) => {
              try {
                await api.reject(cc.id, platform)
                await refresh()
              } catch (e) {
                setNotice(e instanceof Error ? e.message : String(e))
              }
            }}
            onHumanTouch={async (cc) => {
              try {
                setHumanTouchReport(`检测中(约10-30秒,LLM逐句扫描)…\n对象:${cc.comment_text.slice(0, 40)}`)
                const res = await api.candidateHumanTouch(cc.id, platform)
                setHumanTouchReport(res.report)
              } catch (e) {
                setHumanTouchReport(`检测失败:${e instanceof Error ? e.message : String(e)}`)
              }
            }}
          />
        ))}
      </div>

      {humanTouchReport && (
        <div className="fixed bottom-4 right-4 z-50 max-h-[60vh] w-[440px] overflow-auto rounded-2xl border border-violet-200 bg-white p-4 shadow-xl">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-violet-700">AI 味检测报告</h3>
            <button onClick={() => setHumanTouchReport('')} className="text-xs text-stone-400 hover:text-stone-600">
              关闭
            </button>
          </div>
          <pre className="whitespace-pre-wrap text-xs leading-relaxed text-stone-700">{humanTouchReport}</pre>
        </div>
      )}

      {/* 抽屉式审批 */}
      <Drawer
        c={selected}
        platform={platform}
        onClose={() => setSelected(null)}
        onDone={(msg) => {
          setSelected(null)
          if (msg) setNotice(msg)
          void refresh()
        }}
        onDrafted={(item) => {
          setSelected(item)
          void refresh()
        }}
      />
    </div>
  )
}

function Drawer({
  c,
  platform,
  onClose,
  onDone,
  onDrafted,
}: {
  c: AutomationCandidate | null
  platform: AutomationPlatform
  onClose: () => void
  onDone: (msg?: string) => void
  onDrafted?: (item: AutomationCandidate) => void
}) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [draftError, setDraftError] = useState('')

  useEffect(() => {
    setDraft(c?.draft ?? '')
  }, [c?.id, c?.draft])

  if (!c) return null
  const warnings = c.lint_warnings ?? []
  const isHot = c.action === 'hot_comment'
  const isXhs = platform === 'xhs' || c.platform === 'xhs'
  const manualReplyUrl = isXhs
    ? c.comment_url || c.video_url
    : isHot
      ? c.video_url
      : `${c.video_url}#reply${c.comment_id}`

  const approve = async () => {
    setBusy(true)
    try {
      const res = await api.approve(c.id, draft, platform)
      onDone(res.warnings?.join(';') || undefined)
    } catch (e) {
      onDone(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/20" />
        <Dialog.Content className="fixed right-0 top-0 h-full w-[480px] max-w-[90vw] bg-white shadow-xl flex flex-col outline-none">
          <div className="flex items-center justify-between border-b border-stone-100 px-5 py-3.5">
            <Dialog.Title className="text-sm font-semibold">
              {isHot ? '审批根评论草稿' : '审批回复草稿'}
            </Dialog.Title>
            <Dialog.Close className="text-stone-400 hover:text-stone-600">
              <X size={16} />
            </Dialog.Close>
          </div>

          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            <section>
              <div className="text-xs text-stone-400 mb-1">原视频</div>
              <div className="flex items-center gap-3">
                <a
                  href={c.video_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-(--brand) hover:underline"
                >
                  {c.video_title}
                </a>
                <a
                  href={manualReplyUrl}
                  target="_blank"
                  rel="noreferrer"
                  title={
                    isHot
                      ? '打开这条视频,自己手动发一条根评论'
                      : isXhs
                        ? '打开这条评论在小红书的位置,自己手动回复'
                        : '打开这条评论在B站的位置,自己手动回复'
                  }
                  className="shrink-0 rounded-lg border border-stone-200 px-2 py-0.5 text-xs text-stone-500 hover:border-(--brand) hover:text-(--brand)"
                >
                  {isHot ? '去视频下评论 ↗' : isXhs ? '去小红书回复 ↗' : '去B站回复 ↗'}
                </a>
              </div>
            </section>
            {isHot ? (
              <section>
                <div className="text-xs text-stone-400 mb-1">
                  根评论 · 直接评在视频下 · {c.signal}
                </div>
                <p className="rounded-xl bg-rose-50 px-3.5 py-2.5 text-xs leading-relaxed text-stone-600">
                  这条发出去<b>没有通知</b>,和已有热评一起按赞数排序——赢了才有公域曝光,
                  输了就是沉底。所以文案要有别人没说的那一面。
                </p>
                {c.sub_replies && c.sub_replies.length > 0 && (
                  <div className="mt-2 rounded-xl bg-stone-50 px-3.5 py-2.5">
                    <div className="text-xs text-stone-400">评论区已有热评(起草时要求绕开)</div>
                    <ul className="mt-1 space-y-1 text-xs text-stone-600">
                      {c.sub_replies.map((t, i) => (
                        <li key={i}>· {t}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </section>
            ) : (
              <section>
                <div className="text-xs text-stone-400 mb-1">
                  评论 · {c.commenter} · 👍{c.like_count} · {c.signal}
                </div>
                <p className="rounded-xl bg-stone-50 px-3.5 py-2.5 text-sm text-stone-700 whitespace-pre-wrap">
                  {c.comment_text}
                </p>
              </section>
            )}
            <section>
              <div className="mb-1 flex items-center justify-between">
                <div className="text-xs text-stone-400">
                  {c.profile_name || '归属未记录'} · 回复草稿({c.draft_source === 'llm' ? 'AI 起草' : '人工'})
                </div>
                {c.status === 'pending_review' && (
                  <button
                    onClick={async () => {
                      setBusy(true)
                      setDraftError('')
                      try {
                        const res = await api.redraft(c.id, platform)
                        setDraft(res.item.draft)
                        onDrafted?.(res.item)
                      } catch (e) {
                        setDraftError(e instanceof Error ? e.message : String(e))
                      } finally {
                        setBusy(false)
                      }
                    }}
                    disabled={busy}
                    className="text-xs text-(--brand) hover:underline disabled:cursor-wait disabled:text-stone-400"
                  >
                    {busy ? 'AI 起草中…（核对推荐理由与内容质检）' : c.draft ? '让 AI 重新起草' : '让 AI 起草'}
                  </button>
                )}
                {draftError && <span className="text-xs text-red-500">{draftError}</span>}
              </div>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={7}
                disabled={c.status !== 'pending_review'}
                className="w-full rounded-xl border border-stone-200 px-3.5 py-2.5 text-sm outline-none focus:border-(--brand) disabled:bg-stone-50"
              />
              <div className="mt-3 space-y-2">
                <label className="block text-xs text-stone-600">添加回复图片（PNG/JPEG/GIF，每张最多8MB，最多3张）
                  <input aria-label="添加回复图片" type="file" accept="image/png,image/jpeg,image/gif" multiple
                    disabled={busy || c.status !== 'pending_review' || (c.attachments?.length ?? 0) >= 3}
                    className="mt-1 block w-full text-xs"
                    onChange={async event => {
                      const files = Array.from(event.currentTarget.files ?? [])
                      event.currentTarget.value = ''
                      if (!files.length) return
                      setBusy(true); setDraftError('')
                      try {
                        for (const file of files) {
                          const result = await api.uploadReplyImage(c.id, file, platform)
                          onDrafted?.(result.item)
                        }
                      } catch (error) { setDraftError(error instanceof Error ? error.message : String(error)) }
                      finally { setBusy(false) }
                    }} />
                </label>
                <p className="text-xs text-stone-400">{platform === 'bili' ? '图片先保存在本机，人工批准发送后才上传B站。更换图片须先撤回批准。' : '本平台尚未验证自动带图发送；可以保存、预览和下载后手工发送。带图草稿不能自动批准，避免漏发图片。'}</p>
                <div className="flex flex-wrap gap-3">{(c.attachments ?? []).map(attachment => (
                  <div key={attachment.attachment_id} className="w-28 rounded border border-stone-200 p-1.5">
                    <img className="h-20 w-full rounded object-contain" src={api.replyImageUrl(c.id, attachment.attachment_id, platform)} alt={attachment.original_name} />
                    <p className="truncate text-xs text-stone-500">{attachment.original_name}</p>
                    <div className="mt-1 flex justify-between text-xs">
                      <a className="text-(--brand)" href={api.replyImageUrl(c.id, attachment.attachment_id, platform)} download={attachment.original_name}>下载</a>
                      {c.status === 'pending_review' && <button disabled={busy} className="text-red-500" onClick={async () => {
                        setBusy(true); setDraftError('')
                        try { const result = await api.removeReplyImage(c.id, attachment.attachment_id, platform); onDrafted?.(result.item) }
                        catch (error) { setDraftError(error instanceof Error ? error.message : String(error)) }
                        finally { setBusy(false) }
                      }}>移除</button>}
                    </div>
                  </div>
                ))}</div>
              </div>
              {warnings.length > 0 && (
                <div className="mt-2 space-y-1">
                  {warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-1.5 text-xs text-amber-600">
                      <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {w}
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>

          <div className="border-t border-stone-100 px-5 py-3.5 flex gap-2">
            {c.status === 'pending_review' ? (
              <>
                <button
                  onClick={approve}
                  disabled={busy || !draft.trim() || !c.profile_id || c.product_source_outdated || (platform !== 'bili' && !!c.attachments?.length)}
                  className="flex-1 flex items-center justify-center gap-1.5 rounded-xl bg-(--brand) py-2.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
                >
                  <CheckCircle2 size={15} /> 批准并排队发送
                </button>
                <button
                  onClick={async () => {
                    await api.reject(c.id, platform)
                    onDone()
                  }}
                  className="rounded-xl border border-stone-200 px-4 py-2.5 text-sm text-stone-500 hover:border-red-300 hover:text-red-500"
                >
                  拒绝
                </button>
              </>
            ) : (
              <div className="text-sm text-stone-400">
                状态:{c.status}
                {c.sent_at && ` · 发送于 ${c.sent_at}`}
                {c.send_error && <span className="text-red-500"> · {c.send_error}</span>}
                {c.status === 'approved' && (
                  <button
                    onClick={async () => {
                      await api.retract(c.id, platform)
                      onDone()
                    }}
                    className="ml-3 text-(--brand) hover:underline"
                  >
                    撤回到待批准
                  </button>
                )}
              </div>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
