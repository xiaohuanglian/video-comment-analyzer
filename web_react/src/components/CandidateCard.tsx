import type { AutomationCandidate } from '../lib/api'
import clsx from 'clsx'

export default function CandidateCard({
  c,
  compact = false,
  onClick,
}: {
  c: AutomationCandidate
  compact?: boolean
  onClick?: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'block w-full rounded-lg border border-stone-200 bg-white px-3 py-2 text-left transition-colors',
        onClick && 'hover:border-(--brand) cursor-pointer',
      )}
    >
      <div className="flex items-center gap-2 text-xs text-stone-400">
        <span
          className={clsx(
            'rounded px-1.5 py-0.5 font-medium',
            c.tier === 'A' ? 'bg-orange-100 text-(--brand)' : 'bg-stone-100 text-stone-500',
          )}
        >
          {c.tier} 类
        </span>
        <span className="truncate">{c.video_title}</span>
        <span className="ml-auto shrink-0">👍 {c.like_count}</span>
      </div>
      <p className={clsx('mt-1 text-xs text-stone-600', compact && 'line-clamp-2')}>
        <span className="text-stone-400">{c.commenter}:</span> {c.comment_text}
      </p>
      {!compact && c.draft && (
        <p className="mt-1.5 rounded bg-stone-50 px-2 py-1.5 text-xs text-stone-700 line-clamp-3">
          草稿:{c.draft}
        </p>
      )}
    </button>
  )
}
