import CollectPanel from '../components/CollectPanel'
import ReportPanel from '../components/ReportPanel'

export default function CollectPage() {
  return (
    <div className="mx-auto max-w-5xl px-6 py-6 space-y-4">
      <header>
        <h1 className="text-lg font-semibold">评论采集</h1>
        <p className="text-xs text-stone-400">
          一切的前提:先把评论批量采回来,洞察、选题、回复才有原料。建议一次采几千到几万条。
        </p>
      </header>
      <CollectPanel />
      <ReportPanel />
    </div>
  )
}
