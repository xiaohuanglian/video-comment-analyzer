import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type AutomationPlatform, type AutomationStatus, type Strategy } from '../lib/api'
import { Field } from './growth/ui'
import { buttonClass, errorText, inputClass, panelClass, primaryClass } from './growth/ui-helpers'

const businessKeys = ['keywords', 'note_urls', 'collect_mode', 'freshness_a_hours', 'freshness_b_hours', 'hot_comment_enabled', 'hot_comment_max_per_cycle', 'hot_comment_min_play', 'hot_comment_max_silence_hours'] as const
const signature = (config: Record<string, unknown>) => JSON.stringify(businessKeys.map(key => config[key] ?? null))

export default function ReplyPlanPanel({ platform, status, onSaved }: { platform: AutomationPlatform; status: AutomationStatus; onSaved: () => void }) {
  // This component is keyed by platform; polling must never overwrite a draft.
  const [initialSignature, setInitialSignature] = useState(() => signature(status.config))
  const [keywords, setKeywords] = useState(() => ((status.config.keywords as string[]) ?? []).join('\n'))
  const [urls, setUrls] = useState(() => ((status.config.note_urls as string[]) ?? []).join('\n'))
  const [config, setConfig] = useState(() => ({ collect_mode: String(status.config.collect_mode ?? 'auto'),
    freshness_a_hours: Number(status.config.freshness_a_hours ?? 48), freshness_b_hours: Number(status.config.freshness_b_hours ?? 168),
    hot_comment_enabled: status.config.hot_comment_enabled !== false, hot_comment_max_per_cycle: Number(status.config.hot_comment_max_per_cycle ?? 2),
    hot_comment_min_play: Number(status.config.hot_comment_min_play ?? 1000), hot_comment_max_silence_hours: Number(status.config.hot_comment_max_silence_hours ?? 720) }))
  const [profile, setProfile] = useState<Strategy | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  useEffect(() => {
    let current = true
    api.strategyGet().then(value => { if (current) setProfile(value) }).catch(() => {})
    return () => { current = false }
  }, [])
  const parseLines = (text: string) => text.split('\n').map(s => s.trim()).filter(Boolean)
  return <details className={`${panelClass} space-y-4`}><summary className="cursor-pointer font-medium">本平台的选址与筛选计划</summary>
    <div className="space-y-4 pt-3">
      <p className="text-xs leading-relaxed text-stone-500">定位、人群和口吻来自内容工具当前档案：{profile?.name ?? profile?.niche ?? '尚未读取'}。关键词与时效是本平台任务输入；现有词表仍按平台保存，尚未绑定到单次增长尝试。</p>
      <Link to={`/?view=product${profile?.profile_id ? `&profile=${encodeURIComponent(profile.profile_id)}` : ''}`} className="text-xs text-(--brand) underline">查看或明确切换产品档案</Link>
      <form className="space-y-4" onSubmit={async event => {
        event.preventDefault(); setBusy(true); setNotice('')
        try {
          const latest = await api.automationStatus(platform)
          if (signature(latest.config) !== initialSignature) throw new Error('本平台计划已被其他操作更新，请刷新页面后重试，当前输入尚未保存。')
          const latestProfile = await api.strategyGet()
          if (profile && latestProfile.profile_id !== profile.profile_id) throw new Error('内容工具的当前档案已改变，请刷新核对产品后再保存。')
          const patch: Record<string, unknown> = { keywords: parseLines(keywords), freshness_a_hours: config.freshness_a_hours, freshness_b_hours: config.freshness_b_hours }
          if (platform !== 'bili') Object.assign(patch, { note_urls: parseLines(urls), collect_mode: config.collect_mode })
          else Object.assign(patch, { hot_comment_enabled: config.hot_comment_enabled, hot_comment_max_per_cycle: config.hot_comment_max_per_cycle, hot_comment_min_play: config.hot_comment_min_play, hot_comment_max_silence_hours: config.hot_comment_max_silence_hours })
          await api.automationConfigUpdate(patch, platform)
          setInitialSignature(signature({ ...latest.config, ...patch })); setNotice('本平台计划已保存，执行节奏与开关保持原有策略。'); onSaved()
        } catch (e) { setNotice(errorText(e)) } finally { setBusy(false) }
      }}><fieldset disabled={busy} className="space-y-4">
        <Field label="本轮寻找哪些讨论（每行一个关键词）"><textarea rows={4} className={inputClass} value={keywords} onChange={e => setKeywords(e.target.value)} /></Field>
        {(profile?.target_scenarios ?? []).some(s => s.keywords?.length) && <button type="button" className={buttonClass} onClick={() => setKeywords([...new Set(profile!.target_scenarios!.flatMap(s => s.keywords ?? []))].join('\n'))}>从当前档案带入词表，待确认保存</button>}
        {platform !== 'bili' && <><Field label="已确认的内容链接（每行一条）"><textarea rows={3} className={inputClass} value={urls} onChange={e => setUrls(e.target.value)} /></Field>
          <Field label="这次怎样选择内容"><select className={inputClass} value={config.collect_mode} onChange={e => setConfig(v => ({ ...v, collect_mode: e.target.value }))}><option value="auto">有清单用清单，否则搜索</option><option value="list">只使用清单</option><option value="search">关键词搜索（仍受配额和冷却限制）</option></select></Field></>}
        <div className="grid gap-4 sm:grid-cols-2">{(['freshness_a_hours', 'freshness_b_hours'] as const).map((key, index) => <Field key={key} label={`${index === 0 ? '优先' : '最迟'}考虑多久内的内容（小时）`} hint="这是内容选择口径，与平台请求间隔是两件事。"><input required type="number" min={index === 0 ? 1 : 24} max={720} className={inputClass} value={config[key]} onChange={e => setConfig(v => ({ ...v, [key]: Number(e.target.value) }))} /></Field>)}</div>
        {platform === 'bili' && <details><summary className="cursor-pointer text-sm text-stone-500">根评论选址（可选）</summary><div className="space-y-4 pt-3"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={config.hot_comment_enabled} onChange={e => setConfig(v => ({ ...v, hot_comment_enabled: e.target.checked }))} />允许生成根评论候选，发送仍需人工批准</label>
          <div className="grid gap-4 sm:grid-cols-2">{[
            ['hot_comment_max_per_cycle', '每轮候选上限', 10], ['hot_comment_min_play', '最低播放量', 1000000], ['hot_comment_max_silence_hours', '评论区最长静默时间（小时）', 8760],
          ].map(([key, label, max]) => <Field key={key} label={String(label)}><input type="number" min={1} max={Number(max)} required className={inputClass} value={Number(config[key as keyof typeof config])} onChange={e => setConfig(v => ({ ...v, [key]: Number(e.target.value) }))} /></Field>)}</div>
        </div></details>}
        <p className="text-xs text-stone-500">当前执行约束：每日上限 {String(status.config.daily_send_limit)} 条，基础发送间隔 {String(status.config.send_interval_seconds)} 秒，允许时段 {String(status.config.send_window_start)}–{String(status.config.send_window_end)}。本表只保存选址与筛选口径。</p>
        <button type="submit" className={primaryClass}>保存本平台计划</button>
      </fieldset></form>
      {notice && <p role="status" className="text-sm text-stone-600">{notice}</p>}
    </div>
  </details>
}
