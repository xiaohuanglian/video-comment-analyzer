import { useCallback, useEffect, useState } from 'react'
import { Save, Loader2, Check } from 'lucide-react'
import { api, type AutomationStatus } from '../lib/api'

export default function SettingsPage() {
  const [status, setStatus] = useState<AutomationStatus | null>(null)
  const [keywordsText, setKeywordsText] = useState('')
  const [dailySendLimit, setDailySendLimit] = useState(5)
  const [sendInterval, setSendInterval] = useState(300)
  const [sendWindowStart, setSendWindowStart] = useState('10:00')
  const [sendWindowEnd, setSendWindowEnd] = useState('22:00')
  const [freshnessA, setFreshnessA] = useState(48)
  const [freshnessB, setFreshnessB] = useState(168)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .strategyGet()
      .then((s) => setStrategy(s.exists === false ? {} : s))
      .catch(() => {})
    api
      .automationStatus()
      .then((s) => {
        setStatus(s)
        const c = s.config as Record<string, unknown>
        setKeywordsText(((c.keywords as string[]) ?? []).join('\n'))
        setDailySendLimit(Number(c.daily_send_limit ?? 5))
        setSendInterval(Number(c.send_interval_seconds ?? 300))
        setSendWindowStart(String(c.send_window_start ?? '10:00'))
        setSendWindowEnd(String(c.send_window_end ?? '22:00'))
        setFreshnessA(Number(c.freshness_a_hours ?? 48))
        setFreshnessB(Number(c.freshness_b_hours ?? 168))
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const save = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      await api.automationConfigUpdate({
        keywords: keywordsText.split('\n').map((k) => k.trim()).filter(Boolean),
        daily_send_limit: dailySendLimit,
        send_interval_seconds: sendInterval,
        send_window_start: sendWindowStart,
        send_window_end: sendWindowEnd,
        freshness_a_hours: freshnessA,
        freshness_b_hours: freshnessB,
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [keywordsText, dailySendLimit, sendInterval, sendWindowStart, sendWindowEnd, freshnessA, freshnessB])

  const saveStrategy = async () => {
    setStrategyBusy(true)
    try {
      const saved = await api.strategySave(strategy)
      setStrategy(saved)
      setStrategyDirty(false)
      setStrategySaved(true)
      setTimeout(() => setStrategySaved(false), 1500)
    } finally {
      setStrategyBusy(false)
    }
  }

  const setStrat = (patch: Partial<Strategy>) => {
    setStrategy((s) => ({ ...s, ...patch }))
    setStrategyDirty(true)
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-6 space-y-5">
      <header>
        <h1 className="text-lg font-semibold">设置</h1>
        <p className="text-xs text-stone-400">回复自动化的筛选与发送参数(保存即生效)</p>
      </header>

      {error && <p className="text-sm text-red-500">{error}</p>}

      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm space-y-4">
        <div>
          <label className="text-xs text-stone-400">目标关键词(每行一个,用于自动化的目标视频池)</label>
          <textarea
            value={keywordsText}
            onChange={(e) => setKeywordsText(e.target.value)}
            rows={5}
            className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <NumField label="每日发送上限" v={dailySendLimit} set={setDailySendLimit} min={1} max={50} />
          <NumField label="发送间隔(秒)" v={sendInterval} set={setSendInterval} min={60} max={7200} />
          <NumField label="A 档新鲜度(小时)" v={freshnessA} set={setFreshnessA} min={1} max={720} />
          <NumField label="B 档新鲜度(小时)" v={freshnessB} set={setFreshnessB} min={24} max={720} />
          <div>
            <label className="text-xs text-stone-400">发送窗口开始</label>
            <input
              value={sendWindowStart}
              onChange={(e) => setSendWindowStart(e.target.value)}
              className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
            />
          </div>
          <div>
            <label className="text-xs text-stone-400">发送窗口结束</label>
            <input
              value={sendWindowEnd}
              onChange={(e) => setSendWindowEnd(e.target.value)}
              className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
            />
          </div>
        </div>

        <button
          onClick={save}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-40"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : saved ? <Check size={14} /> : <Save size={14} />}
          {saved ? '已保存' : '保存'}
        </button>
      </section>

      {/* 账号定位(策略档案) */}
      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold">账号定位</h2>
            <p className="text-xs text-stone-400">
              所有内容生成的策略基座:选题规划、文案、回复、最强视频都会自动用这里的定位与口吻
            </p>
          </div>
          {strategy.niche && (
            <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs text-emerald-700">
              已建档{strategy.updated_at ? ` · ${strategy.updated_at.slice(5, 10)}` : ''}
            </span>
          )}
        </div>
        <TextField
          label="一句话定位(赛道+差异化)"
          value={strategy.niche ?? ''}
          placeholder="如:给新手的 AI 视频实战教程,只讲能落地的,不吹工具"
          onChange={(v) => setStrat({ niche: v })}
        />
        <TextField
          label="目标受众(具体到人群+痛点)"
          value={strategy.target_audience ?? ''}
          placeholder="如:想用 AI 做视频但没基础的上班族和学生,怕花钱怕学不会"
          onChange={(v) => setStrat({ target_audience: v })}
        />
        <TextField
          label="变现/目标"
          value={strategy.monetization ?? ''}
          placeholder="如:为 youvibe.cn 导流 + 建立个人品牌"
          onChange={(v) => setStrat({ monetization: v })}
        />
        <AreaField
          label="口吻(每行一条)"
          value={(strategy.tone_rules ?? []).join('\n')}
          placeholder={'如:\n说话直接,不端着\n爱举自己的翻车例子\n专业词后必跟一句大白话'}
          onChange={(v) =>
            setStrat({ tone_rules: v.split('\n').map((x) => x.trim()).filter(Boolean) })
          }
        />
        <AreaField
          label="禁区(每行一条)"
          value={(strategy.forbidden ?? []).join('\n')}
          placeholder={'如:\n不夸大效果\n不用引流话术'}
          onChange={(v) =>
            setStrat({ forbidden: v.split('\n').map((x) => x.trim()).filter(Boolean) })
          }
        />
        <AreaField
          label="参考账号/风格(每行一条:学什么)"
          value={(strategy.reference_styles ?? []).join('\n')}
          placeholder={'如:\nK桑 — 教调度不教工具堆砌\n影视飓风 — 信息密度高但节奏稳'}
          onChange={(v) =>
            setStrat({ reference_styles: v.split('\n').map((x) => x.trim()).filter(Boolean) })
          }
        />
        <button
          onClick={saveStrategy}
          disabled={strategyBusy || !strategyDirty}
          className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-40"
        >
          {strategyBusy ? (
            <Loader2 size={14} className="animate-spin" />
          ) : strategySaved ? (
            <Check size={14} />
          ) : (
            <Save size={14} />
          )}
          {strategySaved ? '已保存,全部生成入口已生效' : strategyDirty ? '保存定位' : '无改动'}
        </button>
      </section>

      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold mb-2">红线(不可改)</h2>
        <ul className="text-xs text-stone-500 space-y-1 leading-relaxed">
          <li>· AI 只发现与起草,发送必须经人工批准</li>
          <li>· 草稿硬禁令:无产品名/链接/引流,禁说教腔与黑话(由 reply_style lint 强制执行)</li>
          <li>· 小红书全线冻结中,只做 B 站</li>
          <li>· 自动化不再自己定时扫描采集;采集走「采集」页手动批量,再回来自动化页筛选</li>
        </ul>
        {status && (
          <p className="mt-3 text-xs text-stone-400">
            当前状态:{status.enabled ? '自动化已启用' : '自动化已暂停'} · Cookie{' '}
            {status.sender.cookie_cached ? '已缓存' : '未就绪'}
          </p>
        )}
      </section>
    </div>
  )
}

function TextField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string
  value: string
  placeholder?: string
  onChange: (v: string) => void
}) {
  return (
    <div>
      <label className="text-xs text-stone-400">{label}</label>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
      />
    </div>
  )
}

function AreaField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string
  value: string
  placeholder?: string
  onChange: (v: string) => void
}) {
  return (
    <div>
      <label className="text-xs text-stone-400">{label}</label>
      <textarea
        value={value}
        placeholder={placeholder}
        rows={3}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
      />
    </div>
  )
}

function NumField({
  label,
  v,
  set,
  min,
  max,
}: {
  label: string
  v: number
  set: (n: number) => void
  min: number
  max: number
}) {
  return (
    <div>
      <label className="text-xs text-stone-400">{label}</label>
      <input
        type="number"
        value={v}
        min={min}
        max={max}
        onChange={(e) => set(Number(e.target.value) || min)}
        className="mt-1 w-full rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
      />
    </div>
  )
}
