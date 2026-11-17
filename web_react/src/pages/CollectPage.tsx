import { Link } from 'react-router-dom'
import ReportPanel from '../components/ReportPanel'
import CollectPanel from '../components/CollectPanel'
import XhsNotesPanel from '../components/XhsNotesPanel'
import LocalDataPanel from '../components/LocalDataPanel'
import YouTubePanel from '../components/YouTubePanel'
import WorkflowGuide from '../components/WorkflowGuide'

export default function CollectPage() {
  return <div className="mx-auto max-w-5xl space-y-5 px-5 py-7 sm:px-8">
    <header><h1 className="text-2xl font-semibold">采集评论</h1><p className="mt-2 text-sm leading-6 text-stone-500">选一个平台、输入关键词，先收集一小批评论。采集时弹出登录页面，请按提示完成登录。</p></header>
    <WorkflowGuide current={0} />
    <CollectPanel />
    <LocalDataPanel />
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-orange-200 bg-orange-50 p-5"><p className="text-sm leading-6 text-stone-600">采完以后：到“待回复列表”选择相同平台，筛选值得回复的评论，再逐条去平台回复。</p><Link to="/reply-list" className="shrink-0 text-sm font-medium text-(--brand) underline">下一步：待回复列表 →</Link></div>
    <details className="rounded-2xl border border-stone-200 bg-white p-5"><summary className="cursor-pointer font-medium">查看采回的小红书笔记</summary><div className="pt-4"><XhsNotesPanel /></div></details>
    <details className="rounded-2xl border border-stone-200 bg-white p-5"><summary className="cursor-pointer font-medium">更多工具：YouTube 评论与历史报告</summary><p className="mt-2 text-sm text-stone-500">第一次使用可以先跳过，主要采集流程在上方。</p><div className="space-y-4 pt-4"><YouTubePanel /><ReportPanel /></div></details>
  </div>
}
