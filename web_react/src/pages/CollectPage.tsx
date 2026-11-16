import ReportPanel from '../components/ReportPanel'
import CollectPanel from '../components/CollectPanel'
import XhsNotesPanel from '../components/XhsNotesPanel'
import LocalDataPanel from '../components/LocalDataPanel'
import YouTubePanel from '../components/YouTubePanel'

export default function CollectPage() {
  return (
    <div className="mx-auto max-w-5xl px-6 py-6 space-y-4">
      <header>
        <h1 className="text-lg font-semibold">评论采集</h1>
        <p className="text-xs text-stone-400">
          先小批量采集评论，再分析用户需求、筛选并起草回复。采集节奏和冷却按平台执行。
        </p>
      </header>
      <CollectPanel />
      {/* 笔记列表放在「本地已采数据」之前：刚采回来的帖子是最想先看到的东西 */}
      <XhsNotesPanel />
      <LocalDataPanel />
      <YouTubePanel />
      <ReportPanel />
    </div>
  )
}
