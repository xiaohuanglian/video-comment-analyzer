import { useEffect, useState } from 'react'
import { api, type Strategy } from '../lib/api'
import { Field } from './ui/Field'
import { buttonClass, errorText, inputClass, panelClass, primaryClass } from './ui/helpers'

export default function ProductProfilePanel({ profileId = '', onCreated, onSaved }: {
  profileId?: string; onCreated: (id: string) => void; onSaved?: () => void;
}) {
  const [profile, setProfile] = useState<Strategy | null>(null)
  const [creating, setCreating] = useState(!profileId)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [audience, setAudience] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [tone, setTone] = useState('')
  const [forbidden, setForbidden] = useState('')
  const [references, setReferences] = useState('')
  useEffect(() => {
    if (!profileId) return
    let current = true
    api.strategyGet(profileId).then(value => {
      if (!current) return
      setProfile(value); setTone((value.tone_rules ?? []).join('\n')); setForbidden((value.forbidden ?? []).join('\n')); setReferences((value.reference_styles ?? []).join('\n'))
    }).catch(e => { if (current) setError(errorText(e)) })
    return () => { current = false }
  }, [profileId])
  const save = async () => {
    if (!profile) return
    setBusy(true); setError(''); setNotice('')
    try {
      setProfile(await api.strategySave({ ...profile, profile_id: profileId,
        tone_rules: tone.split('\n').map(s => s.trim()).filter(Boolean),
        forbidden: forbidden.split('\n').map(s => s.trim()).filter(Boolean),
        reference_styles: references.split('\n').map(s => s.trim()).filter(Boolean) }))
      setNotice('产品档案已保存。'); onSaved?.()
    } catch (e) { setError(errorText(e)) } finally { setBusy(false) }
  }
  return <section className={`${panelClass} space-y-4`}>
    <header className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">{creating ? '直接在这里建立产品' : '产品定位与回复口吻'}</h2>
      <p className="mt-1 text-sm text-stone-500">档案是产品资料的唯一来源，筛选与回复使用当前明确选择的产品资料。</p></div>
      {profileId && <button type="button" disabled={busy} className={buttonClass} onClick={() => setCreating(v => !v)}>{creating ? '返回当前档案' : '添加另一个产品'}</button>}
    </header>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}{notice && <p role="status" className="text-sm text-green-700">{notice}</p>}
    {creating ? <form className="space-y-4" onSubmit={async event => {
      event.preventDefault(); setBusy(true); setError('')
      try {
        const result = await api.strategyCreateProfile({ name, niche: description, domain: description, target_audience: audience })
        if (result.profile.profile_id) onCreated(result.profile.profile_id)
      } catch (e) { setError(errorText(e)) } finally { setBusy(false) }
    }}><fieldset disabled={busy} className="space-y-4">
      <Field label="产品名称"><input required maxLength={40} className={inputClass} value={name} onChange={e => setName(e.target.value)} /></Field>
      <Field label="产品现在能帮人解决什么"><textarea required maxLength={2000} rows={3} className={inputClass} value={description} onChange={e => setDescription(e.target.value)} /></Field>
      <Field label="已经知道的目标人群（选填）"><input maxLength={1000} className={inputClass} value={audience} onChange={e => setAudience(e.target.value)} /></Field>
      <button type="submit" className={primaryClass}>建立产品档案</button>
    </fieldset></form> : profile ? <div className="space-y-4">
      <Field label="产品定位"><textarea maxLength={4000} rows={3} className={inputClass} value={profile.niche ?? ''} onChange={e => setProfile(v => ({ ...v, niche: e.target.value }))} /></Field>
      <Field label="希望服务谁"><textarea maxLength={3000} rows={2} className={inputClass} value={profile.target_audience ?? ''} onChange={e => setProfile(v => ({ ...v, target_audience: e.target.value }))} /></Field>
      <Field label="产品或账号的长期目标（选填）"><textarea maxLength={2000} rows={2} className={inputClass} value={profile.goal ?? ''} onChange={e => setProfile(v => ({ ...v, goal: e.target.value }))} /></Field>
      <details><summary className="cursor-pointer text-sm text-stone-500">回复与内容风格</summary><div className="space-y-4 pt-4">
        <Field label="口吻要求（每行一条）"><textarea rows={3} className={inputClass} value={tone} onChange={e => setTone(e.target.value)} /></Field>
        <Field label="不能说什么（每行一条）"><textarea rows={3} className={inputClass} value={forbidden} onChange={e => setForbidden(e.target.value)} /></Field>
        <Field label="参考账号或风格（每行一条）"><textarea rows={2} className={inputClass} value={references} onChange={e => setReferences(e.target.value)} /></Field>
      </div></details>
      <details><summary className="cursor-pointer text-sm text-stone-500">按需补充收费、证据与评论研究口径</summary><div className="space-y-4 pt-4">
        <Field label="收费与变现方式"><textarea rows={2} className={inputClass} value={profile.monetization ?? ''} onChange={e => setProfile(v => ({ ...v, monetization: e.target.value }))} /></Field>
        <Field label="已有实战证据"><textarea rows={3} className={inputClass} value={profile.evidence ?? ''} onChange={e => setProfile(v => ({ ...v, evidence: e.target.value }))} /></Field>
        <Field label="用于评论分析的领域"><input className={inputClass} value={profile.domain ?? ''} onChange={e => setProfile(v => ({ ...v, domain: e.target.value }))} /></Field>
        <Field label="这次想从评论中研究什么"><textarea rows={2} className={inputClass} value={profile.research_goal ?? ''} onChange={e => setProfile(v => ({ ...v, research_goal: e.target.value }))} /></Field>
      </div></details>
      <div className="flex flex-wrap gap-2"><button type="button" disabled={busy} className={primaryClass} onClick={() => void save()}>保存产品档案</button>
        {profile.active_profile_id !== profileId && <button type="button" disabled={busy} className={buttonClass} onClick={async () => {
          setBusy(true); setError('')
          try {
            await api.strategySetActive(profileId); setProfile(v => ({ ...v, active_profile_id: profileId })); setNotice('已明确切换：之后用户筛选与回复起草使用这份档案。')
          } catch (e) { setError(errorText(e)) } finally { setBusy(false) }
        }}>将这份档案用于筛选与回复工具</button>}
      </div>
      <p className="text-xs leading-relaxed text-stone-500">{profile.active_profile_id === profileId ? '筛选与回复工具当前使用这份档案。' : '当前档案未切换，筛选与回复继续使用原档案。'}</p>
    </div> : <p className="text-sm text-stone-500">正在读取档案…</p>}
  </section>
}
