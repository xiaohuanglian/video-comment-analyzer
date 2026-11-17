import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, CheckCircle2, Circle, Download, FileText, MessageSquare, RefreshCw } from 'lucide-react'
import { api, type LocalDataSummary } from '../lib/api'
import { settingsApi, type SystemStatus } from '../lib/settings-api'
import { buttonClass, panelClass, primaryClass } from '../components/ui/helpers'

export default function HomePage() {
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [data, setData] = useState<LocalDataSummary | null>(null)
  const [profileName, setProfileName] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    Promise.allSettled([settingsApi.systemStatus(), api.crawlerLocalData(), api.strategyProfiles()]).then(([system, inventory, profiles]) => {
      if (!active) return
      setStatus(system.status === 'fulfilled' ? system.value : null)
      setData(inventory.status === 'fulfilled' ? inventory.value : null)
      if (profiles.status === 'fulfilled') {
        const current = profiles.value.profiles.find(p => p.profile_id === profiles.value.active_profile_id)
        setProfileName(current?.is_configured ? current.name : '')
      } else setProfileName(null)
      setError([system, inventory, profiles].some(result => result.status === 'rejected') ? '部分状态暂时读不到。请确认启动窗口仍然开着，再点“重新检查”。' : '')
      setLoading(false)
    })
    return () => { active = false }
  }, [revision])
  const comments = data ? Object.values(data.platforms).reduce((sum, row) => sum + row.comments, 0) : null
  const checks = [
    { title: '连接 AI', description: status === null ? '等待检查' : status.model.configured ? '已填写配置，使用前可测试连接' : '分析和起草前需要填写，采集评论可以先做', ready: status?.model.configured, to: '/settings#model-connection' },
    { title: '告诉工具你在做什么', description: profileName === null ? '等待检查' : profileName ? `当前档案：${profileName}` : '回答三个问题，说明产品和目标用户', ready: !!profileName, to: '/profiles?new=1' },
    { title: '准备一批评论', description: comments === null ? '等待检查' : comments > 0 ? `本地已有 ${comments.toLocaleString()} 条评论` : '从 B 站一个关键词开始，建议先采 3 个视频', ready: comments !== null && comments > 0, to: '/collect' },
  ]
  return <div className="mx-auto max-w-5xl space-y-6 px-5 py-7 sm:px-8">
    <header className="rounded-3xl bg-stone-900 p-6 text-white sm:p-9">
      <p className="text-sm text-orange-200">视频评论工作台 · 从这里开始</p>
      <h1 className="mt-3 text-2xl font-semibold leading-snug sm:text-3xl">把评论变成你能用的线索</h1>
      <p className="mt-3 max-w-xl text-sm leading-7 text-stone-300">找出用户在问什么、遇到什么困难，筛出值得回复的评论。第一次用，先收集一小批评论，再打开“待回复列表”。</p>
      <div className="mt-6 flex flex-wrap gap-3"><Link className={primaryClass} to="/reply-list">打开待回复列表<ArrowRight size={16} /></Link><Link className="inline-flex items-center rounded-lg border border-stone-600 px-4 py-2 text-sm hover:bg-stone-800" to="/help">先看使用方法</Link></div>
    </header>
    <section className={`${panelClass} space-y-4`}>
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">第一次使用，准备这三件事</h2><p className="mt-1 text-sm text-stone-500">按需完成。已有数据可以直接分析。</p></div><button type="button" className={buttonClass} disabled={loading} onClick={() => { setLoading(true); setRevision(value => value + 1) }}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />{loading ? '正在检查' : '重新检查'}</button></div>
      {error && <p role="alert" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">{error}</p>}
      <ul className="divide-y divide-stone-100">{checks.map(check => <li key={check.title}><Link to={check.to} className="flex items-center gap-3 rounded-lg py-4 hover:bg-stone-50">
        {check.ready ? <CheckCircle2 size={21} className="shrink-0 text-emerald-600" /> : <Circle size={21} className="shrink-0 text-stone-300" />}<div className="flex-1"><h3 className="text-sm font-medium">{check.title}</h3><p className="mt-1 text-sm leading-relaxed text-stone-500">{check.description}</p></div><ArrowRight size={16} className="shrink-0 text-stone-400" />
      </Link></li>)}</ul>
    </section>
    <section aria-label="选择要做的事" className="grid gap-4 sm:grid-cols-3">
      {[
        { to: '/collect', icon: Download, title: '1. 找到真实评论', text: '输入关键词，收集视频或笔记下的评论。', action: '去采集' },
        { to: '/reply-list', icon: FileText, title: '2. 筛选待回复评论', text: 'B 站、抖音、小红书统一列表，查看原评论和入选原因。', action: '打开列表' },
        { to: '/reply-list', icon: MessageSquare, title: '3. 去平台回复', text: '打开原视频或笔记，自己回复，再回列表标记“我已回复”。', action: '查看待回复' },
      ].map(({ to, icon: Icon, title, text, action }) => <Link key={title} to={to} className={`${panelClass} transition hover:border-orange-300 hover:shadow-sm`}><Icon size={22} className="text-(--brand)" /><h2 className="mt-4 font-semibold">{title}</h2><p className="mt-2 text-sm leading-6 text-stone-500">{text}</p><p className="mt-5 flex items-center gap-2 text-sm font-medium text-(--brand)">{action}<ArrowRight size={14} /></p></Link>)}
    </section>
    <p className="text-sm leading-6 text-stone-500">B 站、抖音、小红书均支持独立的待回复列表。打开原帖后由你回复，列表处理记录保存在本机；受控发送另在高级页面操作。</p>
  </div>
}
