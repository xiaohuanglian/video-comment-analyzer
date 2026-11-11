import { useCallback, useEffect, useState } from 'react'
import { Loader2, Sparkles, ArrowRight, Check } from 'lucide-react'
import clsx from 'clsx'
import { api, type Scenario } from '../lib/api'

interface Question {
  key: 'domain' | 'target_audience' | 'research_goal'
  question: string
  hint: string
  placeholder: string
}

interface Props {
  /** 建档成功后回调（父级刷新档案列表） */
  onDone?: (profileId: string) => void
  onClose?: () => void
}

/**
 * 引导式建档：3 个问题 → 一份可用档案 → 可选顺手跑一次切场景。
 *
 * 为什么要这一步：内置档案已中立化（不预设行业），所以新用户第一次
 * 打开时，所有需要「我是谁、面向谁」的功能都会明确报错。这是对的，
 * 但不该让人先在设置页填一整页表单。只问"没有就跑不动"的三项。
 */
export default function OnboardingWizard({ onDone, onClose }: Props) {
  const [questions, setQuestions] = useState<Question[]>([])
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [runScenario, setRunScenario] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{
    profileId: string
    scenarios: Scenario[]
    warnings: string[]
    scenarioError: string
    nextSteps: string[]
  } | null>(null)

  useEffect(() => {
    api
      .onboardingQuestions()
      .then((r) => setQuestions(r.questions as Question[]))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const filled = questions.length > 0 && questions.every((q) => (answers[q.key] ?? '').trim().length > 0)

  const submit = useCallback(async () => {
    if (!filled) return
    setBusy(true)
    setError('')
    try {
      const res = await api.onboardingSubmit({
        domain: answers.domain ?? '',
        target_audience: answers.target_audience ?? '',
        research_goal: answers.research_goal ?? '',
        name: answers.domain ?? '',
        run_scenario: runScenario,
      })
      setResult({
        profileId: res.active_profile_id,
        scenarios: res.scenarios?.items ?? [],
        warnings: res.scenarios?.warnings ?? [],
        scenarioError: res.scenario_error,
        nextSteps: res.next_steps,
      })
      onDone?.(res.active_profile_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [answers, filled, runScenario, onDone])

  if (result) {
    return (
      <section className="rounded-2xl border border-emerald-200 bg-emerald-50/40 p-5 space-y-3">
        <div className="flex items-center gap-2">
          <Check size={16} className="text-emerald-600" />
          <h2 className="text-sm font-semibold">档案已建好</h2>
        </div>
        <p className="text-xs text-stone-600">
          已完成建档，之后的分析、筛选、选题都会按这份口径走。想再建第二个产品，回这里点「新建档案」。
        </p>

        {runScenario && (
          <div className="rounded-xl bg-white/70 p-3">
            {result.scenarioError ? (
              <p className="text-xs text-amber-700">{result.scenarioError}</p>
            ) : result.scenarios.length === 0 ? (
              <p className="text-xs text-stone-500">没有生成场景。可以稍后在「选题中心 → 切场景」重跑。</p>
            ) : (
              <>
                <p className="mb-2 text-xs font-medium text-stone-600">
                  顺手切出的 {result.scenarios.length} 个场景（都需要用真实语料验证过才算数）：
                </p>
                <ul className="space-y-1.5">
                  {result.scenarios.map((s, i) => (
                    <li key={i} className="text-xs">
                      <span className="font-medium">{s.name}</span>
                      <span className="ml-1.5 rounded-full bg-stone-100 px-1.5 py-0.5 text-[10px] text-stone-500">
                        {s.axis_label}
                      </span>
                      {s.trigger && <span className="ml-1 text-stone-500">· {s.trigger}</span>}
                    </li>
                  ))}
                </ul>
                {result.warnings.length > 0 && (
                  <p className="mt-2 text-[11px] text-amber-700">{result.warnings.join('；')}</p>
                )}
              </>
            )}
          </div>
        )}

        <ol className="space-y-1 text-xs text-stone-600">
          {result.nextSteps.map((s, i) => (
            <li key={i} className="flex gap-1.5">
              <span className="text-stone-400">{i + 1}.</span>
              {s}
            </li>
          ))}
        </ol>
        {onClose && (
          <button onClick={onClose} className="rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90">
            开始用
          </button>
        )}
      </section>
    )
  }

  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-5 space-y-4 shadow-sm">
      <div>
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <Sparkles size={15} className="text-(--brand)" />
          3 个问题建好档案
        </h2>
        <p className="mt-1 text-xs text-stone-400">
          只需回答三个问题就能开始用。口吻、禁区、参考风格这些后面随时补，不填也不影响跑分析。
        </p>
      </div>

      {error && <p className="text-sm text-red-500">{error}</p>}

      <div className="space-y-3">
        {questions.map((q, idx) => (
          <div key={q.key}>
            <label className="mb-1 flex items-baseline gap-1.5 text-sm font-medium">
              <span className="text-stone-400">{idx + 1}.</span>
              {q.question}
            </label>
            <input
              value={answers[q.key] ?? ''}
              onChange={(e) => setAnswers((a) => ({ ...a, [q.key]: e.target.value }))}
              placeholder={q.placeholder}
              className="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm outline-none focus:border-stone-500"
            />
            <p className="mt-1 text-[11px] text-stone-400">{q.hint}</p>
          </div>
        ))}
      </div>

      <label className="flex items-center gap-2 text-xs text-stone-600">
        <input type="checkbox" checked={runScenario} onChange={(e) => setRunScenario(e.target.checked)} />
        顺便切一次场景（从你的定位推导可切入的角度，约多花十几秒）
      </label>

      <button
        onClick={submit}
        disabled={!filled || busy}
        className={clsx(
          'flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90',
          (!filled || busy) && 'opacity-40',
        )}
      >
        {busy ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
        {busy ? '正在建档…' : '建好并开始'}
      </button>
    </section>
  )
}
