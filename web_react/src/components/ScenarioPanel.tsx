import { useState } from 'react'
import {
  AlertTriangle,
  Check,
  Loader2,
  Radar,
  Search,
  Sparkles,
  TrendingUp,
} from 'lucide-react'
import clsx from 'clsx'
import { api, type Scenario, type ScenarioPlanResult, type ScenarioVerifyResult } from '../lib/api'

/**
 * 切场景。
 *
 * 解决的具体问题（用户原话）：
 *   「youvibe 上都是 AI 做的好看的图、视频，复制提示词就能做同款。
 *    这个定位我自己想只能想到『求模板、求提示词、新人小白』，
 *    但实际上还有非常多的场景可以切入。」
 *
 * 为什么要想不全：人天然**从产品功能反推场景**（我有模板 → 找求模板的人），
 * 这条路竞争最激烈。真正的机会在你用户的生活情境里。
 *
 * 所以这里强制走六条路径：身份 / 困境 / 替代 / 触发 / 否认 / 邻近。
 * 生成之后**必须验证**——跑一遍真实语料，看是不是真有人这么问。
 */

const AXIS_COLOR: Record<string, string> = {
  identity: 'bg-sky-50 text-sky-700 border-sky-200',
  struggle: 'bg-rose-50 text-rose-700 border-rose-200',
  alternative: 'bg-amber-50 text-amber-700 border-amber-200',
  trigger: 'bg-violet-50 text-violet-700 border-violet-200',
  denial: 'bg-stone-100 text-stone-600 border-stone-200',
  adjacent: 'bg-emerald-50 text-emerald-700 border-emerald-200',
}

export default function ScenarioPanel() {
  const [positioning, setPositioning] = useState('')
  const [audience, setAudience] = useState('')
  const [existingHint, setExistingHint] = useState('')
  const [plan, setPlan] = useState<ScenarioPlanResult | null>(null)
  const [verified, setVerified] = useState<ScenarioVerifyResult | null>(null)
  const [adopted, setAdopted] = useState<string[]>([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const scenarios: Scenario[] = verified?.scenarios ?? plan?.scenarios ?? []

  const generate = async () => {
    setBusy('plan')
    setError('')
    setVerified(null)
    setAdopted([])
    try {
      const res = await api.scenarioPlan({
        positioning,
        audience,
        existing_hint: existingHint,
        limit: 5,
      })
      setPlan(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const verify = async () => {
    if (!scenarios.length) return
    setBusy('verify')
    setError('')
    try {
      setVerified(await api.scenarioVerify(scenarios))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const adopt = async (item: Scenario) => {
    setBusy(`adopt:${item.name}`)
    setError('')
    try {
      await api.scenarioAdopt([item])
      setAdopted((prev) => (prev.includes(item.name) ? prev : [...prev, item.name]))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-3">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold">
            <Radar size={14} /> 切场景
          </h2>
          <p className="mt-1 text-xs text-stone-400">
            从产品定位推导可切入的场景。六条路径：身份 / 困境 / 替代 / 触发 / 否认 / 邻近。
            生成后必须用真实语料验证——不然只是漂亮的猜测。
          </p>
        </div>

        <label className="block space-y-1 text-xs">
          <span className="text-stone-500">产品/内容定位</span>
          <textarea
            value={positioning}
            onChange={(e) => setPositioning(e.target.value)}
            rows={2}
            placeholder="例：AI 做图工具，站内有大量好看的图和视频，用户复制提示词或 skill 就能做同款"
            className="w-full rounded-lg border border-stone-200 px-2 py-1.5"
          />
        </label>

        <label className="block space-y-1 text-xs">
          <span className="text-stone-500">目标人群</span>
          <input
            value={audience}
            onChange={(e) => setAudience(e.target.value)}
            placeholder="例：想用 AI 做内容但不会设计的人"
            className="w-full rounded-lg border border-stone-200 px-2 py-1.5"
          />
        </label>

        <label className="block space-y-1 text-xs">
          <span className="text-stone-500">
            你已经想到的场景（可选，用来让模型避开雷同）
          </span>
          <input
            value={existingHint}
            onChange={(e) => setExistingHint(e.target.value)}
            placeholder="例：求模板、求提示词、新人小白"
            className="w-full rounded-lg border border-stone-200 px-2 py-1.5"
          />
        </label>

        <button
          onClick={() => void generate()}
          disabled={busy !== '' || !positioning.trim()}
          className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
        >
          {busy === 'plan' ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
          生成 5 个场景
        </button>
      </section>

      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span className="break-all">{error}</span>
        </div>
      )}

      {plan && plan.warnings.length > 0 && (
        <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-800 space-y-1">
          {plan.warnings.map((w) => (
            <div key={w}>· {w}</div>
          ))}
        </div>
      )}

      {scenarios.length > 0 && (
        <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">
              场景
              <span className="ml-2 text-xs font-normal text-stone-400">
                {verified ? `已验证 ${verified.stats.total} 个 · 语料 ${verified.corpus_size} 条` : '还没验证'}
              </span>
            </h3>
            <button
              onClick={() => void verify()}
              disabled={busy !== ''}
              className="flex items-center gap-1.5 rounded-lg border border-stone-200 px-3 py-1.5 text-xs text-stone-600 hover:border-(--brand)"
            >
              {busy === 'verify' ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />}
              用语料验证
            </button>
          </div>

          {verified?.stats.warnings?.map((w) => (
            <div key={w} className="text-[11px] text-amber-700">· {w}</div>
          ))}

          <div className="space-y-2">
            {scenarios.map((item) => {
              const isAdopted = adopted.includes(item.name)
              const signal = item.verdict.startsWith('有信号')
              const none = item.verdict.startsWith('无信号')
              return (
                <div
                  key={item.name}
                  className={clsx(
                    'rounded-xl border px-3 py-2.5 space-y-1.5',
                    isAdopted ? 'border-(--brand)' : 'border-stone-200',
                  )}
                >
                  <div className="flex items-start gap-2">
                    <span
                      className={clsx(
                        'shrink-0 rounded border px-1.5 py-0.5 text-[10px]',
                        AXIS_COLOR[item.axis] ?? 'bg-stone-100 text-stone-600 border-stone-200',
                      )}
                    >
                      {item.axis_label}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-medium text-stone-800">{item.name}</div>
                      {item.trigger && (
                        <div className="mt-0.5 text-[11px] text-stone-500">{item.trigger}</div>
                      )}
                    </div>
                    {item.verdict && (
                      <span
                        className={clsx(
                          'shrink-0 rounded px-1.5 py-0.5 text-[10px]',
                          signal
                            ? 'bg-emerald-50 text-emerald-700'
                            : none
                              ? 'bg-stone-100 text-stone-500'
                              : 'bg-amber-50 text-amber-700',
                        )}
                        title={item.verdict}
                      >
                        {signal ? '有信号' : none ? '无信号' : '弱信号'}
                      </span>
                    )}
                  </div>

                  {item.verdict && (
                    <div className="text-[11px] text-stone-500">
                      命中 {item.hits ?? 0} 条 · 独立用户 {item.users ?? 0} · 视频 {item.videos ?? 0}
                    </div>
                  )}

                  {item.keywords.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {item.keywords.map((k) => (
                        <span
                          key={k}
                          className="rounded bg-stone-50 px-1.5 py-0.5 text-[10px] text-stone-600"
                        >
                          {k}
                        </span>
                      ))}
                    </div>
                  )}

                  {item.pain && <div className="text-[11px] text-stone-500">痛：{item.pain}</div>}
                  {item.entry && (
                    <div className="text-[11px] text-stone-500">我们能给：{item.entry}</div>
                  )}
                  {item.why_underused && (
                    <div className="text-[11px] text-stone-400">被忽略的原因：{item.why_underused}</div>
                  )}
                  {item.competitor_density && (
                    <div className="flex items-center gap-1 text-[11px] text-stone-400">
                      <TrendingUp size={11} /> 竞争：{item.competitor_density}
                    </div>
                  )}

                  {item.sample_quotes.length > 0 && (
                    <div className="rounded bg-stone-50 px-2 py-1 text-[10px] text-stone-500">
                      真实评论：{item.sample_quotes[0]}
                    </div>
                  )}

                  <button
                    onClick={() => void adopt(item)}
                    disabled={busy !== '' || isAdopted}
                    className={clsx(
                      'flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] transition-colors',
                      isAdopted
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                        : 'border-stone-200 text-stone-600 hover:border-(--brand)',
                    )}
                  >
                    {busy === `adopt:${item.name}` ? (
                      <Loader2 size={11} className="animate-spin" />
                    ) : (
                      <Check size={11} />
                    )}
                    {isAdopted ? '已采纳（筛选会围绕它判断）' : '采纳这个场景'}
                  </button>
                </div>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}
