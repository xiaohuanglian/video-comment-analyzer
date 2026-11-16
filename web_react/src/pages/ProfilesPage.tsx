import { useEffect, useState } from 'react'
import { api, type ProfileBrief } from '../lib/api'
import ProductProfilePanel from '../components/ProductProfilePanel'
import OnboardingWizard from '../components/OnboardingWizard'
import ScenarioPanel from '../components/ScenarioPanel'
import { errorText, inputClass, panelClass } from '../components/ui/helpers'

export default function ProfilesPage() {
  const [profiles, setProfiles] = useState<ProfileBrief[]>([])
  const [profileId, setProfileId] = useState('')
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const load = async () => {
    const result = await api.strategyProfiles()
    setProfiles(result.profiles)
    setProfileId(result.active_profile_id)
  }
  useEffect(() => {
    let current = true
    api.strategyProfiles().then(result => {
      if (current) { setProfiles(result.profiles); setProfileId(result.active_profile_id) }
    }).catch(e => { if (current) setError(errorText(e)) })
    return () => { current = false }
  }, [])
  return <div className="mx-auto max-w-5xl space-y-5 px-5 py-7 sm:px-8">
    <header><h1 className="text-2xl font-semibold">产品与筛选档案</h1><p className="mt-2 text-sm text-stone-500">维护产品事实、目标人群、筛选口径与回复口吻。切换档案后再开始采集、筛选和起草。</p></header>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    <section className={`${panelClass} space-y-3`}>
      <label htmlFor="active-profile" className="text-sm font-medium">当前用于筛选与回复的档案</label>
      <select id="active-profile" className={inputClass} value={profileId} onChange={async e => {
        const id = e.target.value
        try { await api.strategySetActive(id); setProfileId(id); setCreating(false); setError('') } catch (err) { setError(errorText(err)) }
      }}>
        <option value="" disabled>请选择产品档案</option>
        {profiles.map(profile => <option key={profile.profile_id} value={profile.profile_id}>{profile.name}</option>)}
      </select>
      <button type="button" className="text-sm text-(--brand) underline" onClick={() => setCreating(value => !value)}>{creating ? '返回当前档案' : '通过三个问题新建档案'}</button>
    </section>
    {creating ? <OnboardingWizard onClose={() => setCreating(false)} onDone={() => { setCreating(false); load().catch(e => setError(errorText(e))) }} /> : <ProductProfilePanel key={profileId} profileId={profileId} onCreated={() => { load().catch(e => setError(errorText(e))) }} onSaved={() => { load().catch(e => setError(errorText(e))) }} />}
    <details className={panelClass}><summary className="cursor-pointer font-medium">寻找目标用户的具体场景与搜索词</summary><div className="pt-4"><ScenarioPanel key={profileId} /></div></details>
  </div>
}
