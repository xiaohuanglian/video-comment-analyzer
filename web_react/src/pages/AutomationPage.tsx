import { useCallback, useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X, RefreshCw, AlertTriangle, CheckCircle2, Filter, Loader2 } from 'lucide-react'
import clsx from 'clsx'
import { api, type AutomationCandidate, type AutomationStatus } from '../lib/api'
import CandidateCard from '../components/CandidateCard'

const TABS = [
  { key: 'pending_review', label: '待批准' },
  { key: 'approved', label: '已批准' },
  { key: 'sent', label: '已发送' },
  { key: 'failed', label: '失败' },
  { key: 'rejected', label: '已拒绝' },
] as const

export default function AutomationPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]['key']>('pending_review')
  const [items, setItems] = useState<AutomationCandidate[]>([])
  const [status, setStatus] = useState<AutomationStatus | null>(null)
  const [selected, setSelected] = useState<AutomationCandidate | null>(null)
  const [notice, setNotice] = useState('')
  const [humanTouchReport, setHumanTouchReport] = useState('')
  const [screening, setScreening] = useState(false)
  const [screenResult, setScreenResult] = useState('')

  const refresh = useCallback(async () => {
    try {
      const [s, list] = await Promise.all([api.automationStatus(), api.candidates(tab, 100)])
      setStatus(s)
      // 新条目排前(旧规则筛遗留不再压底)
      setItems(
        (list as AutomationCandidate[]).sort((a, b) =>
          (b.created_at || '').localeCompare(a.created_at || ''),
        ),
      )
      return s
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e))
      return null
    }
  }, [tab])

  // 后台筛选/采集在跑时,自动进入轮询态(从别的页面回来也能续上,不用重新点)
  useEffect(() => {
    if (!status?.cycle?.running) return
    setScreening(true)
  }, [status?.cycle?.running])

  useEffect(() => {
    void refresh()
    const t = setInterval(refresh, screening ? 2000 : 15000)
    return () => clearInterval(t)
  }, [refresh, screening])

  // 筛选:触发后台任务;轮询由下方 useEffect 驱动,点完即可离开页面
  const runScreen = async () => {
    if (screening) return
    setScreenResult('')
    setNotice('')
    try {
      await api.screenCollected(50, true)
      setScreening(true)
    } catch (e) {
      setScreenResult(e instanceof Error ? e.message : String(e))
    }
  }

  // 轮询:筛选中每 2.5s 查状态,结束后展示摘要并刷新列表(超时 10 分钟兜底)
  useEffect(() => {
    if (!screening) return
    let alive = true
    const startedAt = Date.now()
    const tick = async () => {
      if (!alive) return
      try {
        const s = await api.automationStatus()
        setStatus(s)
        if (!s.cycle.running) {
          if (s.cycle.last_error) {
            setScreenResult(`失败:${s.cycle.last_error}`)
          } else {
            try {
              const sum = JSON.parse(s.cycle.last_summary || '{}') as {
                comments?: number
                videos?: number
                funnel?: { excluded?: number; stale?: number; dedup?: number }
                new_candidates?: number
                llm_drafted?: number
              }
              setScreenResult(
                `完成:扫描 ${sum.comments ?? '?'} 条评论/${sum.videos ?? '?'} 个视频 → ` +
                  `排除 ${sum.funnel?.excluded ?? 0}、超龄 ${sum.funnel?.stale ?? 0}、重复 ${sum.funnel?.dedup ?? 0} → ` +
                  `新候选 ${sum.new_candidates ?? 0} 条(AI 起草 ${sum.llm_drafted ?? 0} 条)`,
              )
            } catch {
              setScreenResult('完成,但摘要解析失败,请看待批准列表')
            }
          }
          setScreening(false)
          await refresh()
          return
        }
      } catch {
        /* 网络抖动,下轮再查 */
      }
      if (Date.now() - startedAt > 10 * 60 * 1000) {
        setScreenResult('等待超时,后台仍在跑,稍后自行刷新看待批准')
        setScreening(false)
        return
      }
      setTimeout(tick, 2500)
    }
    tick()
    return () => {
      alive = false
    }
  }, [screening]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="mx-auto max-w-5xl px-6 py-6 space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">回复自动化</h1>
          <p className="text-xs text-stone-400">
            存量评论 → 筛选目标 → LLM 起草 → lint → 人工批准 → 受控发送(采集在「采集」页)
          </p>
        </div>
        <div className="flex items-center gap-2">
          {status && (
            <span
              title="现在唯一在跑的是发送队列:每 20 秒检查一次有没有你批准的回复要发。不会自己采集、不会自己开网页找用户(自动采集已按你的要求关闭)"
              className={clsx(
                'cursor-help rounded-full px-3 py-1 text-xs font-medium',
                status.enabled ? 'bg-emerald-100 text-emerald-700' : 'bg-stone-200 text-stone-500',
              )}
            >
              {status.enabled ? '发送队列:待命' : '发送队列:暂停'}
            </span>
          )}
          <button
            onClick={() => void runScreen()}
            disabled={screening}
            className="flex items-center gap-1.5 rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-xs hover:border-(--brand) disabled:opacity-50"
          >
            {screening ? <Loader2 size={13} className="animate-spin" /> : <Filter size={13} />}
            {screening ? '筛选中…后台在跑,可以离开这页,完成后自动刷新' : '从已采集数据筛选目标(两个采集目录全量)'}
          </button>
          <button
            onClick={() => void refresh()}
            className="rounded-lg border border-stone-200 bg-white p-1.5 hover:border-(--brand)"
          >
            <RefreshCw size={13} />
          </button>
        </div>
      </header>

      {(notice || screenResult) && (
        <div
          className={clsx(
            'flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm',
            screenResult.startsWith('完成')
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-amber-200 bg-amber-50 text-amber-700',
          )}
        >
          <AlertTriangle size={15} /> {screenResult || notice}
          <button
            className="ml-auto"
            onClick={() => {
              setNotice('')
              setScreenResult('')
            }}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* 漏斗 */}
      {status && (
        <div className="grid grid-cols-5 gap-2">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={clsx(
                'rounded-xl border px-3 py-2.5 text-center transition-colors',
                tab === t.key
                  ? 'border-(--brand) bg-orange-50'
                  : 'border-stone-200 bg-white hover:border-stone-300',
              )}
            >
              <div className="text-lg font-semibold text-stone-700">
                {status.funnel[t.key as keyof typeof status.funnel]}
              </div>
              <div className="text-xs text-stone-400">{t.label}</div>
            </button>
          ))}
        </div>
      )}

      {/* 发送通道状态:Cookie 未就绪时显眼提醒 */}
      {status?.sender && !status.sender.cookie_cached && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-700">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>
            发送通道未就绪:B站登录态失效(需要重新扫码登录)。你现在批准的回复会在队列里等待,
            登录恢复后按节奏自动发(间隔约 3 分钟、每日上限、发送时段内);不想等的话,点开条目用「去B站回复」手动回。
          </span>
        </div>
      )}

      {/* 列表 */}
      <div className="space-y-2">
        {tab === 'pending_review' && items.some((c) => c.screened_by !== 'llm') && (
          <button
            onClick={async () => {
              const n = items.filter((c) => c.screened_by !== 'llm').length
              if (!window.confirm(`一键拒绝 ${n} 条旧规则筛的遗留条目?(LLM 精筛的条目不受影响)`)) return
              try {
                const res = await api.bulkRejectRules()
                setNotice(`已清掉 ${res.rejected} 条旧规则筛条目`)
                await refresh()
              } catch (e) {
                setNotice(e instanceof Error ? e.message : String(e))
              }
            }}
            className="w-full rounded-xl border border-dashed border-stone-300 bg-stone-50 py-2 text-xs text-stone-500 hover:border-red-300 hover:text-red-500"
          >
            清掉旧规则筛的遗留条目({items.filter((c) => c.screened_by !== 'llm').length} 条,一键拒绝)
          </button>
        )}
        {tab === 'pending_review' && items.some((c) => c.screened_by === 'llm') && (
          <button
            onClick={async () => {
              const n = items.filter((c) => c.screened_by === 'llm' && (c.draft || '').trim()).length
              if (!window.confirm(`批量批准 ${n} 条 LLM 精筛条目(以当前草稿入队,之后自动发送)?`)) return
              try {
                const res = await api.bulkApproveLlm()
                const parts = [`已批准 ${res.approved} 条`]
                if (res.skipped_similar) parts.push(`${res.skipped_similar} 条因与近期内容过于相似被拦(需改写)`)
                if (res.skipped_no_draft) parts.push(`${res.skipped_no_draft} 条无草稿跳过`)
                setNotice(parts.join(','))
                await refresh()
              } catch (e) {
                setNotice(e instanceof Error ? e.message : String(e))
              }
            }}
            className="w-full rounded-xl border border-dashed border-orange-300 bg-orange-50/60 py-2 text-xs font-medium text-(--brand) hover:bg-orange-50"
          >
            批量批准 LLM 精筛条目({items.filter((c) => c.screened_by === 'llm' && (c.draft || '').trim()).length} 条有草稿)
          </button>
        )}
        {tab === 'sent' && items.length > 0 && (
          <button
            onClick={async () => {
              try {
                setNotice('正在回采B站实时互动…')
                const res = await api.refreshEngagement()
                const act = res.with_activity
                setNotice(
                  act.length
                    ? `已更新 ${res.updated} 条;有互动的 ${act.length} 条:${act.map((a) => `👍${a.like}/回${a.rcount}`).join('、')}`
                    : `已更新 ${res.updated} 条,暂无人理睬(继续等,B站互动是慢热型)`,
                )
                await refresh()
              } catch (e) {
                setNotice(e instanceof Error ? e.message : String(e))
              }
            }}
            className="w-full rounded-xl border border-dashed border-emerald-300 bg-emerald-50/60 py-2 text-xs font-medium text-emerald-700 hover:bg-emerald-50"
          >
            刷新互动数据(回采B站:我方回复的赞/被回复)
          </button>
        )}
        {items.length === 0 && (
          <p className="py-12 text-center text-sm text-stone-400">这个状态下没有条目</p>
        )}
        {items.map((c) => (
          <CandidateCard
            key={c.id}
            c={c}
            onClick={() => setSelected(c)}
            onApprove={async (cc) => {
              try {
                const res = await api.approve(cc.id, cc.draft)
                setNotice(res.warnings?.length ? `已批准,但草稿有 ${res.warnings.length} 条样式提醒:${res.warnings[0]}` : '已批准,排队发送')
                await refresh()
              } catch (e) {
                setNotice(e instanceof Error ? e.message : String(e))
              }
            }}
            onReject={async (cc) => {
              try {
                await api.reject(cc.id)
                await refresh()
              } catch (e) {
                setNotice(e instanceof Error ? e.message : String(e))
              }
            }}
            onHumanTouch={async (cc) => {
              try {
                setHumanTouchReport(`检测中(约10-30秒,LLM逐句扫描)…\n对象:${cc.comment_text.slice(0, 40)}`)
                const res = await api.candidateHumanTouch(cc.id)
                setHumanTouchReport(res.report)
              } catch (e) {
                setHumanTouchReport(`检测失败:${e instanceof Error ? e.message : String(e)}`)
              }
            }}
          />
        ))}
      </div>

      {humanTouchReport && (
        <div className="fixed bottom-4 right-4 z-50 max-h-[60vh] w-[440px] overflow-auto rounded-2xl border border-violet-200 bg-white p-4 shadow-xl">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-violet-700">AI 味检测报告</h3>
            <button onClick={() => setHumanTouchReport('')} className="text-xs text-stone-400 hover:text-stone-600">
              关闭
            </button>
          </div>
          <pre className="whitespace-pre-wrap text-xs leading-relaxed text-stone-700">{humanTouchReport}</pre>
        </div>
      )}

      {/* 抽屉式审批 */}
      <Drawer
        c={selected}
        onClose={() => setSelected(null)}
        onDone={(msg) => {
          setSelected(null)
          if (msg) setNotice(msg)
          void refresh()
        }}
        onDrafted={(item) => {
          setSelected(item)
          void refresh()
        }}
      />
    </div>
  )
}

function Drawer({
  c,
  onClose,
  onDone,
  onDrafted,
}: {
  c: AutomationCandidate | null
  onClose: () => void
  onDone: (msg?: string) => void
  onDrafted?: (item: AutomationCandidate) => void
}) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [draftError, setDraftError] = useState('')

  useEffect(() => {
    setDraft(c?.draft ?? '')
  }, [c])

  if (!c) return null
  const warnings = c.lint_warnings ?? []

  const approve = async () => {
    setBusy(true)
    try {
      const res = await api.approve(c.id, draft)
      onDone(res.warnings?.join(';') || undefined)
    } catch (e) {
      onDone(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/20" />
        <Dialog.Content className="fixed right-0 top-0 h-full w-[480px] max-w-[90vw] bg-white shadow-xl flex flex-col outline-none">
          <div className="flex items-center justify-between border-b border-stone-100 px-5 py-3.5">
            <Dialog.Title className="text-sm font-semibold">审批回复草稿</Dialog.Title>
            <Dialog.Close className="text-stone-400 hover:text-stone-600">
              <X size={16} />
            </Dialog.Close>
          </div>

          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            <section>
              <div className="text-xs text-stone-400 mb-1">原视频</div>
              <div className="flex items-center gap-3">
                <a
                  href={c.video_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-(--brand) hover:underline"
                >
                  {c.video_title}
                </a>
                <a
                  href={`${c.video_url}#reply${c.comment_id}`}
                  target="_blank"
                  rel="noreferrer"
                  title="打开这条评论在B站的位置,自己手动回复"
                  className="shrink-0 rounded-lg border border-stone-200 px-2 py-0.5 text-xs text-stone-500 hover:border-(--brand) hover:text-(--brand)"
                >
                  去B站回复 ↗
                </a>
              </div>
            </section>
            <section>
              <div className="text-xs text-stone-400 mb-1">
                评论 · {c.commenter} · 👍{c.like_count} · {c.signal}
              </div>
              <p className="rounded-xl bg-stone-50 px-3.5 py-2.5 text-sm text-stone-700 whitespace-pre-wrap">
                {c.comment_text}
              </p>
            </section>
            <section>
              <div className="mb-1 flex items-center justify-between">
                <div className="text-xs text-stone-400">
                  回复草稿({c.draft_source === 'llm' ? 'AI 起草' : '人工'})
                </div>
                {c.status === 'pending_review' && (
                  <button
                    onClick={async () => {
                      setBusy(true)
                      setDraftError('')
                      try {
                        const res = await api.redraft(c.id)
                        setDraft(res.item.draft)
                        onDrafted?.(res.item)
                      } catch (e) {
                        setDraftError(e instanceof Error ? e.message : String(e))
                      } finally {
                        setBusy(false)
                      }
                    }}
                    disabled={busy}
                    className="text-xs text-(--brand) hover:underline disabled:cursor-wait disabled:text-stone-400"
                  >
                    {busy ? 'AI 起草中…(含去AI味复检,约1分钟,别关)' : c.draft ? '让 AI 重新起草' : '让 AI 起草'}
                  </button>
                )}
                {draftError && <span className="text-xs text-red-500">{draftError}</span>}
              </div>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={7}
                disabled={c.status !== 'pending_review'}
                className="w-full rounded-xl border border-stone-200 px-3.5 py-2.5 text-sm outline-none focus:border-(--brand) disabled:bg-stone-50"
              />
              {warnings.length > 0 && (
                <div className="mt-2 space-y-1">
                  {warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-1.5 text-xs text-amber-600">
                      <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {w}
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>

          <div className="border-t border-stone-100 px-5 py-3.5 flex gap-2">
            {c.status === 'pending_review' ? (
              <>
                <button
                  onClick={approve}
                  disabled={busy || !draft.trim()}
                  className="flex-1 flex items-center justify-center gap-1.5 rounded-xl bg-(--brand) py-2.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
                >
                  <CheckCircle2 size={15} /> 批准并排队发送
                </button>
                <button
                  onClick={async () => {
                    await api.reject(c.id)
                    onDone()
                  }}
                  className="rounded-xl border border-stone-200 px-4 py-2.5 text-sm text-stone-500 hover:border-red-300 hover:text-red-500"
                >
                  拒绝
                </button>
              </>
            ) : (
              <div className="text-sm text-stone-400">
                状态:{c.status}
                {c.sent_at && ` · 发送于 ${c.sent_at}`}
                {c.send_error && <span className="text-red-500"> · {c.send_error}</span>}
                {c.status === 'approved' && (
                  <button
                    onClick={async () => {
                      await api.retract(c.id)
                      onDone()
                    }}
                    className="ml-3 text-(--brand) hover:underline"
                  >
                    撤回到待批准
                  </button>
                )}
              </div>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
