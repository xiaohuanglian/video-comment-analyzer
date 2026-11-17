import { Link } from 'react-router-dom'
import { ArrowRight, CircleHelp } from 'lucide-react'

const steps = [
  { to: '/collect', label: '采集评论', hint: '先收集一小批真实评论' },
  { to: '/reply-list', label: '待回复列表', hint: '筛出值得回复的评论' },
  { to: '/reply-list', label: '去平台回复', hint: '查看原帖，回复后手动标记' },
]

export default function WorkflowGuide({ current }: { current: number }) {
  return <section aria-label="操作流程" className="rounded-2xl border border-stone-200 bg-white p-4 sm:p-5">
    <div className="mb-3 flex items-center justify-between gap-3 text-sm"><p className="font-medium">按这三步完成一次工作</p><Link to="/help" className="flex items-center gap-1 text-stone-500 hover:text-(--brand)"><CircleHelp size={15} />使用帮助</Link></div>
    <ol className="grid gap-2 sm:grid-cols-3">
      {steps.map((step, index) => <li key={step.label}><Link to={step.to} aria-current={current === index ? 'step' : undefined} className={`flex h-full items-center gap-3 rounded-xl p-3 ${current === index ? 'bg-orange-50 ring-1 ring-orange-200' : 'bg-stone-50 hover:bg-stone-100'}`}>
        <span className={`flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${current === index ? 'bg-(--brand) text-white' : 'bg-white text-stone-500'}`}>{index + 1}</span>
        <div className="flex-1"><p className="text-sm font-medium">{step.label}</p><p className="mt-1 text-xs leading-relaxed text-stone-500">{step.hint}</p></div><ArrowRight size={14} className="shrink-0 text-stone-400" />
      </Link></li>)}
    </ol>
  </section>
}
