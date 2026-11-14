import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, Coins, KeyRound, Loader2, RefreshCw } from 'lucide-react'
import { api, type CostSummary } from '../lib/api'
import { growthApi, type SystemStatus } from '../lib/growth-api'
import { Field } from '../components/growth/ui'
import { buttonClass, errorText, inputClass, panelClass, primaryClass } from '../components/growth/ui-helpers'

const channelLabels: Record<string, string> = {
  manual_hold: '人工停采记录待核查', cooling: '采集冷却中', paused: '发送停损中',
  disabled: '自动化未开启', not_checked: '已启用，账号可用性未验证', error: '本地状态读取失败',
}
export default function SettingsPage() {
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [costs, setCosts] = useState<CostSummary | null>(null)
  const [model, setModel] = useState({ base_url: '', model_name: '', api_key: '' })
  const [maskedKey, setMaskedKey] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [connection, setConnection] = useState<'not_checked' | 'ok' | 'failed'>('not_checked')
  useEffect(() => {
    let current = true
    growthApi.systemStatus().then(value => {
      if (!current) return
      setStatus(value); setModel({ base_url: value.model.base_url, model_name: value.model.model, api_key: '' }); setMaskedKey(value.model.api_key_masked)
    }).catch(e => { if (current) setError(errorText(e)) })
    api.costsSummary().then(value => { if (current) setCosts(value) }).catch(e => { if (current) setError(errorText(e)) })
    return () => { current = false }
  }, [])
  const updateModel = (patch: Partial<typeof model>) => { setModel(value => ({ ...value, ...patch })); setConnection('not_checked'); setNotice('') }
  const operateModel = async (test: boolean) => {
    setBusy(test ? 'test' : 'save'); setError(''); setNotice('')
    try {
      const payload = { ...model, api_key: model.api_key || undefined }
      if (test) {
        const result = await api.modelSettingsTest(payload)
        setConnection(result.ok ? 'ok' : 'failed')
        setNotice(result.ok ? '这组连接测试成功。' : `连接测试失败：${result.error ?? '请检查网络与配置'}`)
      } else {
        const saved = await api.modelSettingsSave(payload)
        setMaskedKey(saved.api_key_masked); setModel(value => ({ ...value, api_key: '' })); setConnection('not_checked')
        const current = await growthApi.systemStatus(); setStatus(current)
        setNotice(current.model.environment_override ? '已保存。运行环境中的模型配置优先，请核对实际使用的模型。' : '配置已保存，请测试连接。')
      }
    } catch (e) { setError(errorText(e)); if (test) setConnection('failed') } finally { setBusy('') }
  }
  const issues = status?.channels.filter(channel => ['manual_hold', 'cooling', 'paused', 'error'].includes(channel.state)) ?? []
  return <div className="mx-auto max-w-5xl space-y-5 px-5 py-7 sm:px-8">
    <header><h1 className="text-2xl font-semibold">连接与系统设置</h1><p className="mt-2 text-sm text-stone-500">处理模型连接、账号异常与费用。产品定位和增长任务在增长工作台里完成。</p></header>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    <section className={`${panelClass} space-y-3`}><h2 className="font-semibold">现在需要处理什么</h2>
      {!status ? <p className="text-sm text-stone-500">{error ? '状态未能读取，尚不能判断是否需要处理。' : '正在读取本地状态…'}</p> : <>
        <a href="#model-connection" className="block rounded-lg bg-stone-50 p-3 text-sm">{status.model.configured ? connection === 'ok' ? '这组模型连接刚刚测试成功' : connection === 'failed' ? '模型连接失败，请核查网络和配置' : '模型已配置，连接尚未验证；使用 AI 前可在下方测试' : '尚未配置模型，AI 起草需要先连接模型'} →</a>
        {issues.map(channel => <div key={channel.platform} className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{channel.label}：{channelLabels[channel.state]}。{channel.manual_hold ? '请由人核查账号恢复情况，人工停采不会在此自动解除。' : '请核对已有拦截记录，等待或处理异常后再执行。'}</div>)}
        {issues.length === 0 && <p className="text-sm text-stone-500">未发现已记录的通道拦截；账号登录有效性尚未验证。</p>}
        <Link to="/?view=product" className={buttonClass}>回到产品档案与增长任务</Link>
      </>}
    </section>
    <section id="model-connection" className={`${panelClass} space-y-4`}>
      <h2 className="flex items-center gap-2 font-semibold"><KeyRound size={17} />模型网关连接</h2>
      {status && <p className="break-words text-xs leading-relaxed text-stone-500">实际使用：{status.model.model || '未配置'} · {status.model.configured ? '有配置，连接需单独验证' : '缺少有效配置'}{status.model.environment_override && ' · 运行环境配置优先于本页保存值'}</p>}
      <fieldset disabled={busy !== '' || !status} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2"><Field label="网关根地址"><input className={inputClass} value={model.base_url} onChange={e => updateModel({ base_url: e.target.value })} /></Field><Field label="模型名称"><input className={inputClass} value={model.model_name} onChange={e => updateModel({ model_name: e.target.value })} /></Field></div>
        <Field label="API Key" hint={maskedKey ? `已有凭据 ${maskedKey}；留空保留原 Key。` : '填写模型服务提供的凭据。'}><input type="password" autoComplete="off" className={inputClass} value={model.api_key} onChange={e => updateModel({ api_key: e.target.value })} /></Field>
        <div className="flex flex-wrap gap-2"><button type="button" className={primaryClass} onClick={() => void operateModel(true)}>{busy === 'test' ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}测试这组连接</button><button type="button" className={buttonClass} onClick={() => void operateModel(false)}>保存连接配置</button></div>
      </fieldset>
      {notice && <p role="status" className="text-sm text-stone-600">{notice}</p>}
    </section>
    <section className={`${panelClass} space-y-4`}>
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">平台与账号</h2><p className="mt-1 text-xs text-stone-500">节奏由平台执行策略管理；这里说明当前有效策略与已有异常。</p></div><button type="button" disabled={busy !== ''} className={buttonClass} onClick={async () => {
        setBusy('refresh'); setError(''); try { setStatus(await growthApi.systemStatus()) } catch (e) { setError(errorText(e)) } finally { setBusy('') }
      }}><RefreshCw size={14} />刷新本地状态</button></div>
      {status?.channels.map(channel => <article key={channel.platform} className="space-y-3 border-t border-stone-100 pt-4">
        <div className="flex flex-wrap justify-between gap-3"><h3 className="text-sm font-medium">{channel.label} · {channelLabels[channel.state] ?? '状态未知'}</h3><Link className="text-xs text-(--brand) underline" to={`/automation?platform=${channel.platform}`}>查看本平台任务与账号处理</Link></div>
        {channel.send_policy && <p className="text-xs leading-relaxed text-stone-500">发送：每日上限 {channel.send_policy.daily_send_limit} 条，基础间隔 {channel.send_policy.send_interval_seconds} 秒，允许时段 {channel.send_policy.send_window_start}–{channel.send_policy.send_window_end}。<br />采集：基础间隔 {channel.crawl_interval?.join(' + 抖动 ')} 秒；搜索间隔 {channel.search_interval?.join(' + 抖动 ')} 秒。<br />来源：{channel.policy_source}。这些是本项目执行约束，不能保证平台不会拦截。</p>}
        {channel.cooldown_seconds ? <p className="text-xs text-amber-800">已记录冷却，剩余约 {Math.ceil(channel.cooldown_seconds / 3600)} 小时。</p> : null}
        {channel.message && <p className="text-xs text-red-700">{channel.message}</p>}
        {channel.platform === 'bili' && <button type="button" disabled={busy !== '' || channel.manual_hold} className={buttonClass} onClick={async () => {
          setBusy('login'); setError(''); try { await api.biliLogin(); setNotice('已请求打开 B 站登录窗口，请按官方页面完成扫码。登录有效性以实际通道检查为准。') } catch (e) { setError(errorText(e)) } finally { setBusy('') }
        }}>需要恢复 B 站登录时，打开扫码窗口</button>}
      </article>)}
      {status && <p className="text-xs leading-relaxed text-stone-500">{status.note}</p>}
    </section>
    <details className={`${panelClass} space-y-3`}><summary className="flex cursor-pointer items-center gap-2 font-medium"><Coins size={17} />费用与调用统计</summary>
      {costs ? <div className="space-y-3 pt-3"><p className="text-sm">今日 {costs.today.calls} 次调用 · {costs.today.total_tokens.toLocaleString()} tokens{costs.pricing.configured && ` · 约 ¥${costs.today.cost.toFixed(4)}`}</p>{costs.by_feature.map(row => <p key={row.feature} className="text-xs text-stone-500">{row.feature} · {row.calls} 次 · {row.total_tokens.toLocaleString()} tokens</p>)}</div> : <p className="pt-3 text-sm text-stone-500">费用暂未取得，不能按零费用解释。</p>}
    </details>
  </div>
}
