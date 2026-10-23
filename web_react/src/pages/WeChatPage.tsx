import { useCallback, useEffect, useState } from 'react'
import { Download, Loader2, RefreshCw, BookOpen, Layers, Trash2, FileText } from 'lucide-react'
import { api } from '../lib/api'

interface WechatEntry {
  id: string
  ts: number
  title: string
  account: string
  date: string
  url: string
  dir: string
  images: number
  videos?: number
}

interface TaskState {
  running: boolean
  kind: string
  total: number
  done: number
  current: string
  error: string
}

export default function WeChatPage() {
  const [lib, setLib] = useState<WechatEntry[]>([])
  const [articleUrl, setArticleUrl] = useState('')
  const [singleBusy, setSingleBusy] = useState(false)
  const [collectionUrl, setCollectionUrl] = useState('')
  const [collBusy, setCollBusy] = useState(false)
  const [task, setTask] = useState<TaskState | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const [l, t] = await Promise.all([api.wechatLibrary(), api.wechatTask()])
      setLib(l as WechatEntry[])
      setTask(t as TaskState)
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = setInterval(refresh, task?.running ? 2000 : 10000)
    return () => clearInterval(timer)
  }, [refresh, task?.running])

  const downloadArticle = async () => {
    if (!articleUrl.trim() || singleBusy) return
    setSingleBusy(true)
    setError('')
    setNotice('')
    try {
      const e = await api.wechatArticle(articleUrl.trim())
      const entry = e as WechatEntry
      const stats = `${entry.images} 张图${entry.videos ? `、${entry.videos} 个视频` : ''}`
      setNotice(`已下载:《${entry.title}》(${stats})`)
      setArticleUrl('')
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSingleBusy(false)
    }
  }

  const startCollection = async () => {
    if (!collectionUrl.trim() || collBusy) return
    setCollBusy(true)
    setError('')
    setNotice('')
    try {
      const res = await api.wechatCollection(collectionUrl.trim())
      setNotice((res as { message: string }).message)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCollBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-6 space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">公众号采集</h1>
          <p className="text-xs text-stone-400">
            内置能力:文章/合集批量下载(md+html+图片),素材进资料库,供选题与文案引用
          </p>
        </div>
        <button
          onClick={() => void refresh()}
          className="rounded-lg border border-stone-200 bg-white p-1.5 hover:border-(--brand)"
        >
          <RefreshCw size={13} />
        </button>
      </header>

      {notice && (
        <p className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm text-emerald-700">
          {notice}
        </p>
      )}
      {error && (
        <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-600">
          {error}
        </p>
      )}

      {/* 单篇 */}
      <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-3">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <BookOpen size={14} /> 单篇下载
        </h2>
        <div className="flex gap-2">
          <input
            value={articleUrl}
            onChange={(e) => setArticleUrl(e.target.value)}
            placeholder="公众号文章链接 https://mp.weixin.qq.com/s/…"
            className="flex-1 rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
          />
          <button
            onClick={downloadArticle}
            disabled={singleBusy || !articleUrl.trim()}
            className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-40"
          >
            {singleBusy ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />} 下载
          </button>
        </div>
      </section>

      {/* 合集 */}
      <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-3">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <Layers size={14} /> 合集(专栏)整包下载
          <span className="text-xs font-normal text-stone-400">
            自动翻页收集合集内全部文章,逐篇下载(间隔限速,防封)
          </span>
        </h2>
        <div className="flex gap-2">
          <input
            value={collectionUrl}
            onChange={(e) => setCollectionUrl(e.target.value)}
            placeholder="合集链接 https://mp.weixin.qq.com/mp/appmsgalbum/…"
            className="flex-1 rounded-lg border border-stone-200 px-3 py-2 text-sm outline-none focus:border-(--brand)"
          />
          <button
            onClick={startCollection}
            disabled={collBusy || !collectionUrl.trim()}
            className="flex items-center gap-1.5 rounded-lg bg-(--brand) px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-40"
          >
            {collBusy ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />} 开始
          </button>
        </div>

        {task && (task.running || task.done > 0) && (
          <div className="rounded-xl bg-stone-50 px-4 py-3 text-sm space-y-1.5">
            {task.running ? (
              <div className="flex items-center gap-2 text-stone-600">
                <Loader2 size={14} className="animate-spin text-sky-600" />
                合集任务:{task.done}/{task.total} 篇 · 正在:《{task.current}》
              </div>
            ) : (
              <p className="text-emerald-600">
                上次合集任务完成:{task.done}/{task.total} 篇
              </p>
            )}
            {task.total > 0 && (
              <div className="h-1.5 overflow-hidden rounded-full bg-stone-200">
                <div
                  className="h-full rounded-full bg-(--brand) transition-all"
                  style={{ width: `${(task.done / Math.max(1, task.total)) * 100}%` }}
                />
              </div>
            )}
            {task.error && <p className="text-xs text-amber-600">最近一篇失败:{task.error}</p>}
          </div>
        )}
      </section>

      {/* 资料库 */}
      <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm space-y-2">
        <h2 className="text-sm font-semibold">
          资料库({lib.length} 篇)
          <span className="ml-2 text-xs font-normal text-stone-400">
            存于 data/wechat/,按公众号分目录;md 可直接喂给选题/文案
          </span>
        </h2>
        {lib.length === 0 && <p className="py-8 text-center text-xs text-stone-400">还没有下载任何文章</p>}
        {lib.map((e) => (
          <div
            key={e.id}
            className="flex items-center gap-3 rounded-xl border border-stone-200 px-3 py-2 hover:border-(--brand)"
          >
            <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700 shrink-0">
              {e.account}
            </span>
            <a
              href={e.url}
              target="_blank"
              rel="noreferrer"
              className="flex-1 truncate text-sm text-stone-700 hover:text-(--brand)"
            >
              {e.title}
            </a>
            <span className="shrink-0 text-xs text-stone-400">{e.date}</span>
            <span className="shrink-0 text-xs text-stone-400">🖼{e.images}</span>
            {e.videos ? <span className="shrink-0 text-xs text-stone-400">🎬{e.videos}</span> : null}
            <a
              href={`http://127.0.0.1:8766/api/data/files/${e.dir}/article.md`}
              target="_blank"
              rel="noreferrer"
              title="查看 md"
              className="shrink-0 text-stone-400 hover:text-(--brand)"
            >
              <FileText size={14} />
            </a>
            <button
              onClick={() => void api.wechatDelete(e.id).then(refresh)}
              className="shrink-0 text-stone-300 hover:text-red-400"
            >
              <Trash2 size={13} />
            </button>
          </div>
        ))}
      </section>

      <p className="text-xs text-stone-400">
        版权提醒:下载内容仅供个人学习与素材研究,请勿搬运分发;引用请标明原作者。
      </p>
    </div>
  )
}
