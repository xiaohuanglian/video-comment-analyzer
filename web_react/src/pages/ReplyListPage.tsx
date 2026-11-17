import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Check, Copy, ExternalLink, Filter, Loader2, RefreshCw } from 'lucide-react'
import { api, type AutomationPlatform, type ProfileBrief } from '../lib/api'
import { manualApi, type ManualJob, type ManualList, type ManualStatus } from '../lib/manual-replies-api'
import { buttonClass, errorText, inputClass, panelClass, primaryClass } from '../components/ui/helpers'
import { Field } from '../components/ui/Field'

const platforms = [{ id: 'bili', name: 'B 站' }, { id: 'dy', name: '抖音' }, { id: 'xhs', name: '小红书' }] as const
const tabs = [{ id: 'pending', name: '待回复' }, { id: 'done', name: '我已回复' }, { id: 'skipped', name: '已跳过' }] as const

export default function ReplyListPage() {
  const [params, setParams] = useSearchParams()
  const platform = (platforms.some(p => p.id === params.get('platform')) ? params.get('platform') : 'bili') as AutomationPlatform
  const platformName = platforms.find(p => p.id === platform)!.name
  const [profiles, setProfiles] = useState<ProfileBrief[]>([])
  const [profileId, setProfileId] = useState('')
  const [mode, setMode] = useState<'ai' | 'rules'>('ai')
  const [tab, setTab] = useState<ManualStatus>('pending')
  const [limit, setLimit] = useState(30)
  const [days, setDays] = useState(30)
  const [goal, setGoal] = useState('')
  const [offset, setOffset] = useState(0)
  const [result, setResult] = useState<ManualList | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState('')
  const [loading, setLoading] = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(true)
  const collapseOnLoad = useRef(true)
  const version = useRef(0)
  const filterProfile = mode === 'ai' ? profileId : ''
  const [startedJob, setStartedJob] = useState<{ platform: string; job: ManualJob } | null>(null)
  const job = startedJob?.platform === platform ? startedJob.job : result?.job

  useEffect(() => {
    let alive = true
    api.strategyProfiles().then(response => { if (alive) setProfiles(response.profiles.filter(p => p.is_configured)) }).catch(e => { if (alive) setError(errorText(e)) })
    return () => { alive = false }
  }, [])
  const refresh = useCallback(async () => {
    const requestVersion = ++version.current
    try {
      const response = await manualApi.list(platform, tab, filterProfile, offset)
      if (version.current !== requestVersion) return
      setResult(response); setStartedJob(null); setError('')
      if (collapseOnLoad.current && !response.job.running) { setSettingsOpen(response.total === 0); collapseOnLoad.current = false }
    } catch (e) { if (version.current === requestVersion) setError(errorText(e)) }
    finally { if (version.current === requestVersion) setLoading(false) }
  }, [platform, tab, filterProfile, offset])
  const invalidate = useCallback(() => { version.current++ }, [])
  useEffect(() => {
    const first = setTimeout(() => void refresh(), 0)
    const timer = setInterval(() => void refresh(), job?.running ? 2000 : 15000)
    return () => { invalidate(); clearTimeout(first); clearInterval(timer) }
  }, [refresh, job?.running, invalidate])
  const selectPlatform = (id: string) => {
    collapseOnLoad.current = true
    version.current++; setResult(null); setLoading(true); setOffset(0); setNotice(''); setError(''); setStartedJob(null)
    setParams({ platform: id })
  }
  const start = async () => {
    const operationVersion = version.current
    collapseOnLoad.current = true
    setBusy('screen'); setNotice(''); setError('')
    try {
      const currentPlatform = platform
      const nextJob = await manualApi.screen(platform, { mode, profile_id: mode === 'ai' ? profileId : '', goal, limit, days })
      if (operationVersion !== version.current) return
      setStartedJob({ platform: currentPlatform, job: nextJob }); setTab('pending'); setOffset(0)
      await refresh()
    } catch (e) { setError(errorText(e)) } finally { setBusy('') }
  }
  const mark = async (id: string, status: ManualStatus) => {
    const operationVersion = version.current
    setBusy(id); setError(''); setNotice('')
    try { await manualApi.mark(platform, id, status); if (operationVersion !== version.current) return; setNotice(status === 'done' ? '已记录为“我已回复”。这是你的手动记录，不代表平台已确认。' : status === 'skipped' ? '已跳过，可以在“已跳过”中恢复。' : '已恢复到待回复。'); await refresh() }
    catch (e) { setError(errorText(e)) } finally { setBusy('') }
  }
  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); setNotice('已复制评论原文，可在平台评论区中查找。') }
    catch { setError('浏览器未允许复制，请手动选中评论原文复制。') }
  }
  const running = !!job?.running
  const working = busy !== '' || running
  return <div className="mx-auto max-w-5xl space-y-5 px-5 py-7 sm:px-8">
    <header><p className="text-sm font-medium text-(--brand)">采集完成后，来这里找值得回复的人</p><h1 className="mt-2 text-2xl font-semibold">待回复列表</h1><p className="mt-2 text-sm leading-7 text-stone-500">筛选 → 看原评论和入选原因 → 去平台回复 → 回来标记“我已回复”。本列表不会自动发送。</p></header>
    <nav aria-label="回复平台" className="flex flex-wrap gap-2">{platforms.map(p => <button type="button" key={p.id} aria-pressed={p.id === platform} className={p.id === platform ? primaryClass : buttonClass} onClick={() => selectPlatform(p.id)}>{p.name}</button>)}</nav>
    {error && <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p>}
    {notice && <p role="status" className="rounded-xl bg-emerald-50 p-4 text-sm text-emerald-800">{notice}</p>}
    <details className={`${panelClass} space-y-4`} open={settingsOpen} onToggle={event => setSettingsOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer font-semibold">筛选设置与新增评论</summary>
      <div className="space-y-4 pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">筛选{platformName}已采集的评论</h2><Link to={`/collect?platform=${platform}`} className="text-sm text-(--brand) underline">还没有数据？先去采集 →</Link></div>
      <fieldset disabled={working} className="space-y-4">
        <Field label="怎样筛选？"><select className={inputClass} value={mode} onChange={e => { version.current++; setMode(e.target.value as 'ai' | 'rules'); setResult(null); setLoading(true); setOffset(0) }}><option value="ai">AI 按业务匹配（需要 AI 连接和业务档案）</option><option value="rules">提问 / 求助规则初筛（无需 AI，需人工核对业务相关性）</option></select></Field>
        {mode === 'ai' ? <div className="grid gap-4 sm:grid-cols-2"><Field label="为哪个业务找人？"><select className={inputClass} value={profileId} onChange={e => { version.current++; setProfileId(e.target.value); setResult(null); setLoading(true); setOffset(0) }}><option value="">请选择已配置的业务档案</option>{profiles.map(p => <option key={p.profile_id} value={p.profile_id}>{p.name}</option>)}</select></Field><Field label="这次想找到什么需求？（可选）" hint="留空按业务档案的研究目标筛选。"><input className={inputClass} value={goal} onChange={e => setGoal(e.target.value)} placeholder="例如：想学视频剪辑但不知从何开始" /></Field></div> : <p className="rounded-xl bg-amber-50 p-3 text-sm leading-6 text-amber-900">规则初筛沿用现有的提问、求助和工具使用规则，适合先找可能有需求的评论。它不代表已匹配你的业务，也不包含 AI 评分。</p>}
        <div className="grid gap-4 sm:grid-cols-2"><Field label="本次最多新增"><select className={inputClass} value={limit} onChange={e => setLimit(Number(e.target.value))}>{[10, 30, 50, 100].map(n => <option key={n} value={n}>{n} 条</option>)}</select></Field><Field label="评论发布于"><select className={inputClass} value={days} onChange={e => setDays(Number(e.target.value))}>{[7, 30, 90, 365].map(n => <option key={n} value={n}>最近 {n} 天</option>)}</select></Field></div>
      </fieldset>
      {mode === 'ai' && <p className="text-sm leading-6 text-stone-500">先<Link to="/profiles?new=1" className="text-(--brand) underline">建好业务档案</Link>、<Link to="/settings#model-connection" className="text-(--brand) underline">连接 AI</Link>。AI 只筛选评论并说明原因，不生成或发送回复；每轮最多评估 300 条，调用可能产生费用。</p>}
      <button type="button" disabled={working || (mode === 'ai' && !profileId)} className={primaryClass} onClick={() => void start()}>{working ? <Loader2 size={16} className="animate-spin" /> : <Filter size={16} />}{running ? '正在筛选，可稍后回来查看' : busy === 'screen' ? '正在启动…' : '筛选待回复评论'}</button>
      {job && job.phase !== 'idle' && <p role={job.phase === 'failed' ? 'alert' : 'status'} className={`text-sm leading-6 ${job.phase === 'failed' ? 'text-red-700' : 'text-stone-600'}`}>{job.message}{job.summary && ` 本轮读取 ${job.summary.comments} 条，评估 ${job.summary.examined} 条，尚未评估 ${job.summary.not_examined} 条。`}{!!job.summary?.model_failures && ` 有 ${job.summary.model_failures} 条 AI 判断失败，未作为匹配结果入选。`}</p>}
      <p className="text-xs leading-6 text-stone-500">列表和处理记录保存在本机，刷新或重启后仍可查看。筛选任务在工具退出后中断，可重新开始。</p>
      </div>
    </details>
    <section className="space-y-4" aria-label={`${platformName}回复清单`}>
      <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex flex-wrap gap-2">{tabs.map(t => <button type="button" key={t.id} aria-pressed={tab === t.id} className={tab === t.id ? primaryClass : buttonClass} onClick={() => { version.current++; setTab(t.id); setOffset(0); setResult(null); setLoading(true) }}>{t.name} {result?.counts[t.id] ?? '—'}</button>)}</div><button type="button" className={buttonClass} onClick={() => void refresh()}><RefreshCw size={14} />刷新列表</button></div>
      {!result ? <p className="py-8 text-center text-sm text-stone-500">{loading ? '正在读取列表…' : '列表未能读取，请刷新重试。'}</p> : <>
        <p className="text-sm text-stone-500">{mode === 'ai' && profileId ? `当前业务：${profiles.find(p => p.profile_id === profileId)?.name ?? profileId}` : '查看本平台所有业务和规则初筛记录'} · 共 {result.total} 条。打开原帖不会自动标记已回复。</p>
        {result.items.length === 0 && <div className={`${panelClass} text-sm leading-7 text-stone-500`}>{tab === 'pending' ? '这里还没有待回复评论。先采集本平台评论，再在上方启动筛选；没有匹配结果时请核对业务档案、评论时间范围和筛选结果提示。' : '这里还没有处理记录。'}</div>}
        {result.items.map(item => <article key={item.id} className={`${panelClass} space-y-4`}>
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{item.commenter || '昵称未记录'}</h3><span className="text-xs text-stone-500">{platformName} · {item.profile_name} · {item.mode === 'ai' ? `AI 匹配 ${item.worth} / 10` : '规则初筛，未做业务匹配'}</span></div>
          <blockquote className="whitespace-pre-wrap break-words rounded-xl bg-stone-50 p-4 text-sm leading-7 text-stone-800">{item.comment_text}</blockquote>
          <div className="space-y-2 text-sm leading-6"><p><span className="text-stone-400">入选原因：</span>{item.match_reason || item.signal}</p><p><span className="text-stone-400">原视频 / 笔记：</span>{item.video_title || `内容 ID ${item.video_id}`}</p><p className="text-xs text-stone-500">{item.location_hint}</p></div>
          <div className="flex flex-wrap gap-2">{item.reply_url ? <a className={primaryClass} href={item.reply_url} target="_blank" rel="noreferrer"><ExternalLink size={15} />去{platformName}回复</a> : <span className="text-sm text-amber-800">未记录原帖链接，请按标题到平台查找。</span>}<button type="button" className={buttonClass} onClick={() => void copy(item.comment_text)}><Copy size={14} />复制评论定位</button>
            {tab === 'pending' ? <><button type="button" disabled={busy !== ''} className={buttonClass} onClick={() => void mark(item.id, 'done')}><Check size={15} />我已回复</button><button type="button" disabled={busy !== ''} className={buttonClass} onClick={() => void mark(item.id, 'skipped')}>跳过</button></> : <button type="button" disabled={busy !== ''} className={buttonClass} onClick={() => void mark(item.id, 'pending')}>恢复待回复</button>}
          </div>
        </article>)}
        {(result.total > 50 || offset > 0) && <div className="flex items-center justify-center gap-3"><button className={buttonClass} disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - 50)); setLoading(true); setResult(null) }}>上一页</button><span className="text-sm">第 {Math.floor(offset / 50) + 1} 页</span><button className={buttonClass} disabled={offset + 50 >= result.total} onClick={() => { setOffset(offset + 50); setLoading(true); setResult(null) }}>下一页</button></div>}
      </>}
    </section>
  </div>
}
