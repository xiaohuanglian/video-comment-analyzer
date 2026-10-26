import { useCallback, useEffect, useState } from 'react'
import { Save, Loader2, Check, Coins } from 'lucide-react'
import { api, type AutomationStatus, type Strategy, type CostSummary, type CostEntry } from '../lib/api'

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
  // 账号定位(策略档案)——上一版漏了这组状态声明导致白屏,补齐
  const [strategy, setStrategy] = useState<Partial<Strategy>>({})
  const [strategyDirty, setStrategyDirty] = useState(false)
  const [strategyBusy, setStrategyBusy] = useState(false)
  const [strategySaved, setStrategySaved] = useState(false)
  // 费用统计
  const [costs, setCosts] = useState<CostSummary | null>(null)
  const [recentCalls, setRecentCalls] = useState<CostEntry[]>([])
  const [loginBusy, setLoginBusy] = useState(false)

  const refreshStatus = useCallback(() => {
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
      .catch(() => {})
  }, [])

  // 发送通道状态轮询:登录进行中加密轮询,平时也是低频刷新
  useEffect(() => {
    refreshStatus()
    const t = setInterval(refreshStatus, 4000)
    return () => clearInterval(t)
  }, [refreshStatus])

  useEffect(() => {
    api
      .strategyGet()
      .then((s) => setStrategy(s.exists === false ? {} : s))
      .catch(() => {})
    api
      .costsSummary()
      .then(setCosts)
      .catch(() => {})
    api
      .costsLedger(8)
      .then(setRecentCalls)
      .catch(() => {})
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

      {/* 发送通道(B站):登录态监控与扫码恢复 */}
      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm space-y-3">
        <div>
          <h2 className="text-sm font-semibold">发送通道(B 站)</h2>
          <p className="text-xs text-stone-400">受控回复的登录态与发送状态;失效了在这里扫码恢复</p>
        </div>
        <div className="rounded-xl bg-stone-50 px-3.5 py-2.5 text-xs space-y-1">
          <p>
            Cookie 状态:
            {status?.sender?.cookie_cached ? (
              <span className="font-medium text-emerald-600">已就绪</span>
            ) : (
              <span className="font-medium text-red-500">失效(批准的回复会排队等待)</span>
            )}
            {status?.sender?.account?.uname ? (
              <span className="text-stone-400">
                {' '}
                · 账号 {status.sender.account.uname} Lv.{status.sender.account.level ?? '?'}
              </span>
            ) : null}
          </p>
          {status?.sender?.login_flow?.message && (
            <p className="text-amber-600">{status.sender.login_flow.message}</p>
          )}
          {status?.sender?.wait_reason && (
            <p className="text-stone-400">发送节奏:{String(status.sender.wait_reason)}</p>
          )}
          {status?.sender && !status.sender.cookie_cached && !status.sender.login_flow?.running && (
            <p className="text-red-400">
              {String((status.sender as { last_error?: string }).last_error || '')}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={async () => {
              if (loginBusy || status?.sender?.login_flow?.running) return
              setLoginBusy(true)
              try {
                await api.biliLogin()
              } catch (e) {
                setError(e instanceof Error ? e.message : String(e))
              } finally {
                setLoginBusy(false)
              }
            }}
            disabled={loginBusy || status?.sender?.login_flow?.running}
            className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-40"
          >
            {status?.sender?.login_flow?.running ? (
              <>
                <Loader2 size={14} className="animate-spin" /> 登录窗口已打开,等你扫码…
              </>
            ) : (
              '扫码恢复 B 站登录'
            )}
          </button>
          <p className="text-xs text-stone-400">本机会弹出浏览器窗口,用 B 站 App 扫码(3 分钟内有效)</p>
        </div>
      </section>

      {/* 费用统计(只记账,不限流) */}
      <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="flex items-center gap-1.5 text-sm font-semibold">
              <Coins size={14} /> 费用统计
            </h2>
            <p className="text-xs text-stone-400">
              全部 LLM 消耗台账(对话/选题/写稿/洞察/回复起草),只记账不限制
            </p>
          </div>
          <button
            onClick={() => {
              api.costsSummary().then(setCosts).catch(() => {})
              api.costsLedger(8).then(setRecentCalls).catch(() => {})
            }}
            className="rounded-lg border border-stone-200 p-1.5 text-stone-400 hover:border-(--brand) hover:text-(--brand)"
          >
            刷新
          </button>
        </div>

        {!costs ? (
          <p className="py-4 text-center text-xs text-stone-400">还没有消耗记录</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl bg-stone-50 p-3">
                <p className="text-xs text-stone-400">今日</p>
                <p className="text-lg font-semibold">
                  {costs.today.calls} 次 · {costs.today.total_tokens.toLocaleString()} tokens
                </p>
                {costs.pricing.configured && (
                  <p className="text-xs text-stone-400">≈ ¥{costs.today.cost.toFixed(2)}</p>
                )}
              </div>
              <div className="rounded-xl bg-stone-50 p-3">
                <p className="text-xs text-stone-400">累计</p>
                <p className="text-lg font-semibold">
                  {costs.total.calls} 次 · {costs.total.total_tokens.toLocaleString()} tokens
                </p>
                {costs.pricing.configured ? (
                  <p className="text-xs text-stone-400">≈ ¥{costs.total.cost.toFixed(2)}</p>
                ) : (
                  <p className="text-xs text-stone-400">未配价格,按 tokens 统计</p>
                )}
              </div>
            </div>

            {costs.by_feature.length > 0 && (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-stone-400">
                    <th className="py-1 font-normal">功能</th>
                    <th className="py-1 font-normal text-right">调用</th>
                    <th className="py-1 font-normal text-right">输入 tok</th>
                    <th className="py-1 font-normal text-right">输出 tok</th>
                    {costs.pricing.configured && <th className="py-1 font-normal text-right">费用</th>}
                  </tr>
                </thead>
                <tbody>
                  {costs.by_feature.map((f) => (
                    <tr key={f.feature} className="border-t border-stone-100">
                      <td className="py-1">{f.feature}</td>
                      <td className="py-1 text-right">{f.calls}</td>
                      <td className="py-1 text-right">{f.prompt_tokens.toLocaleString()}</td>
                      <td className="py-1 text-right">{f.completion_tokens.toLocaleString()}</td>
                      {costs.pricing.configured && (
                        <td className="py-1 text-right">¥{f.cost.toFixed(2)}</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {recentCalls.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs text-stone-400">最近调用</p>
                {recentCalls.slice(0, 8).map((c, i) => (
                  <p key={i} className="flex items-center gap-2 text-xs text-stone-500">
                    <span className={c.ok ? 'text-emerald-500' : 'text-red-400'}>●</span>
                    <span className="w-32 shrink-0 truncate">{c.feature}</span>
                    <span className="text-stone-300">
                      {new Date(c.ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })}
                    </span>
                    <span>{c.total_tokens.toLocaleString()} tok</span>
                    <span className="text-stone-300">{(c.duration_ms / 1000).toFixed(1)}s</span>
                    {!c.ok && c.error && <span className="truncate text-red-400">{c.error.slice(0, 60)}</span>}
                  </p>
                ))}
              </div>
            )}
          </>
        )}
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
