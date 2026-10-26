import type { AutomationCandidate } from '../lib/api'
import clsx from 'clsx'
import { CheckCircle2, XCircle } from 'lucide-react'

export default function CandidateCard({
  c,
  compact = false,
  onClick,
  onApprove,
  onReject,
}: {
  c: AutomationCandidate
  compact?: boolean
  onClick?: () => void
  onApprove?: (c: AutomationCandidate) => Promise<void> | void
  onReject?: (c: AutomationCandidate) => Promise<void> | void
}) {
  const hasDraft = !!(c.draft || '').trim()
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => e.key === 'Enter' && onClick?.()}
      className={clsx(
        'block w-full rounded-lg border border-stone-200 bg-white px-3 py-2 text-left transition-colors',
        onClick && 'cursor-pointer hover:border-(--brand)',
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
        {c.lane === 'engage' ? (
          <span className="rounded bg-sky-100 px-1.5 py-0.5 font-medium text-sky-700">互动</span>
        ) : (
          <span className="rounded bg-orange-100 px-1.5 py-0.5 font-medium text-(--brand)">帮助</span>
        )}
        {typeof c.worth === 'number' && c.worth > 0 && (
          <span
            className={clsx(
              'rounded px-1.5 py-0.5 font-medium',
              c.worth >= 8
                ? 'bg-emerald-100 text-emerald-700'
                : c.worth >= 6
                  ? 'bg-teal-50 text-teal-700'
                  : 'bg-stone-100 text-stone-400',
            )}
            title={c.intent || '综合值得回复度'}
          >
            {c.worth} 分
          </span>
        )}
        {c.screened_by === 'rules' && (
          <span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-600">规则筛</span>
        )}
        {c.tier === 'A' && (
          <span className="rounded bg-orange-50 px-1.5 py-0.5 text-orange-500">新鲜</span>
        )}
        <span className="truncate">{c.video_title}</span>
        <span className="ml-auto shrink-0">👍 {c.like_count}</span>
      </div>
      <p className={clsx('mt-1 text-xs text-stone-600', compact && 'line-clamp-2')}>
        <span className="text-stone-400">{c.commenter}:</span> {c.comment_text}
      </p>
      {c.match_reason && (
        <p className="mt-1 flex items-start gap-1 text-xs text-stone-400">
          <span className="shrink-0">✧</span>
          <span className="line-clamp-2">{c.match_reason}</span>
        </p>
      )}
      {!compact && c.draft && (
        <p className="mt-1.5 rounded bg-stone-50 px-2 py-1.5 text-xs text-stone-700 line-clamp-3">
          草稿:{c.draft}
        </p>
      )}
      {!compact && c.lint_warnings && c.lint_warnings.length > 0 && (
        <p className="mt-1 text-xs text-amber-600">⚠ {c.lint_warnings.length} 条样式提醒(点开可见)</p>
      )}

      {/* 内联操作:待审条目不用进抽屉就能批准/跳转/拒绝 */}
      {c.status === 'pending_review' && (onApprove || onReject) && (
        <div
          className="mt-2 flex items-center gap-2 border-t border-stone-100 pt-2"
          onClick={(e) => e.stopPropagation()}
        >
          {onApprove && (
            <button
              onClick={() => void onApprove(c)}
              disabled={!hasDraft}
              title={hasDraft ? '批准草稿,排队自动发送' : '还没有草稿:点卡片进抽屉让 AI 起草'}
              className={clsx(
                'flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium',
                hasDraft
                  ? 'bg-(--brand) text-white hover:opacity-90'
                  : 'cursor-not-allowed bg-stone-100 text-stone-400',
              )}
            >
              <CheckCircle2 size={13} /> {hasDraft ? '批准' : '无草稿'}
            </button>
          )}
          <a
            href={`${c.video_url}#reply${c.comment_id}`}
            target="_blank"
            rel="noreferrer"
            title="打开这条评论在B站的位置,自己手动回复"
            className="rounded-lg border border-stone-200 px-2.5 py-1 text-xs text-stone-500 hover:border-(--brand) hover:text-(--brand)"
          >
            去B站回 ↗
          </a>
          {onReject && (
            <button
              onClick={() => void onReject(c)}
              title="拒绝这条"
              className="flex items-center gap-1 rounded-lg border border-stone-200 px-2.5 py-1 text-xs text-stone-400 hover:border-red-300 hover:text-red-500"
            >
              <XCircle size={13} /> 拒绝
            </button>
          )}
          {onClick && (
            <button
              onClick={onClick}
              className="ml-auto text-xs text-stone-400 hover:text-(--brand) hover:underline"
            >
              编辑草稿 →
            </button>
          )}
        </div>
      )}
    </div>
  )
}
