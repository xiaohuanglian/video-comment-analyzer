export const inputClass = 'w-full rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm text-stone-800 outline-none focus:border-(--brand) focus:ring-2 focus:ring-orange-100 disabled:bg-stone-50'
export const buttonClass = 'inline-flex items-center justify-center gap-2 rounded-lg border border-stone-200 bg-white px-3.5 py-2 text-sm font-medium text-stone-700 transition hover:bg-stone-50 disabled:cursor-wait disabled:opacity-40'
export const primaryClass = 'inline-flex items-center justify-center gap-2 rounded-lg bg-(--brand) px-4 py-2 text-sm font-medium text-white transition hover:opacity-90 disabled:cursor-wait disabled:opacity-40'
export const panelClass = 'rounded-2xl border border-stone-200 bg-white p-5 sm:p-6'
export const lines = (text: string) => text.split('\n').map(s => s.trim()).filter(Boolean)
export const errorText = (error: unknown) => error instanceof Error ? error.message : String(error)
export const decisionLabel = { continue: '继续验证', adjust: '调整方案', stop: '停止投入' }
export const attemptStatus = { ready: '待执行', running: '待观察', observing: '待复盘', reviewed: '已复盘' }
