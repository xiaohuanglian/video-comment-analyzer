import type { AutomationCandidate } from '../lib/api'
import clsx from 'clsx'
import { CheckCircle2, XCircle } from 'lucide-react'

/** 热评竞争判定 → 人话。判定依据见 api/services/outreach/hot_comment.py。 */
const COMPETITION_LABEL: Record<string, string> = {
  cold: '评论区冷清,容易占位',
  open: '还有空位',
  contested: '有人抢但没坐稳',
  crowded: '已被热评占住',
  too_small: '播放太少,没人看',
  unknown_coverage: '只采到几条评论,看不出真实热评',
}

export default function CandidateCard({
  c,
  compact = false,
  onClick,
  onApprove,
  onReject,
  onHumanTouch,
}: {
  c: AutomationCandidate
  compact?: boolean
  onClick?: () => void
  onApprove?: (c: AutomationCandidate) => Promise<void> | void
  onReject?: (c: AutomationCandidate) => Promise<void> | void
  onHumanTouch?: (c: AutomationCandidate) => Promise<void> | void
}) {
  const hasDraft = !!(c.draft || '').trim()
  // 热评条目没有目标评论(comment_id 是 "0"),手动入口只能开到视频本身
  const isHot = c.action === 'hot_comment'
  // 小红书条目:手动回复入口用带 xsec_token 的评论直链(B站的 #reply 锚点对小红书无效)
  const isXhs = c.platform === 'xhs'
  const manualReplyUrl = isXhs
    ? c.comment_url || c.video_url
    : isHot
      ? c.video_url
      : `${c.video_url}#reply${c.comment_id}`
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
        {isHot ? (
          <span
            className="rounded bg-rose-100 px-1.5 py-0.5 font-medium text-rose-700"
            title={
              `根评论:直接评在视频下,争公域曝光(和已有热评比赞数排序),没有通知` +
              (c.competition ? ` · 竞争判定:${COMPETITION_LABEL[c.competition] || c.competition}` : '')
            }
          >
            根评论
          </span>
        ) : (
          <span
            className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-600"
            title="回复:平台会给被回复的人发通知,触达确定,但只在这条评论的楼里可见"
          >
            回复
          </span>
        )}
        {c.video_route === 'both' && (
          <span
            className="rounded bg-violet-100 px-1.5 py-0.5 font-medium text-violet-700"
            title="这个视频值得两条都做:评论区有人在问事(该回),同时热评还没占住位置(该发根评论)"
          >
            两条都做
          </span>
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
        {!!c.persona && (
          <span
            className="rounded px-1.5 py-0.5 text-violet-600"
            title="对方画像:决定回复话术分层"
            style={{ background: 'rgb(245 243 255)' }}
          >
            {c.persona === 'novice_doer'
              ? '新手实干'
              : c.persona === 'expert_doer'
                ? '老手实干'
                : c.persona === 'thinker'
                  ? '观点讨论'
                  : c.persona === 'watcher'
                    ? '观望焦虑'
                    : c.persona === 'beggar'
                      ? '求带党'
                      : '营销号'}
          </span>
        )}
        {c.tier === 'A' && (
          <span className="rounded bg-orange-50 px-1.5 py-0.5 text-orange-500">新鲜</span>
        )}
        {c.status === 'sent' && c.reply_like_count !== undefined && (
          <span
            className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-600"
            title={c.engagement_note || `实时互动(更新于 ${c.engagement_at?.slice(5, 16) ?? ''})`}
          >
            回👍{c.reply_like_count} · 被回{c.reply_rcount}
          </span>
        )}
        {!!c.sub_reply_count && (
          <span
            className="rounded bg-sky-50 px-1.5 py-0.5 text-sky-600"
            title="楼中楼已有回复,精筛会判断是否已被答好"
          >
            💬 {c.sub_reply_count}
          </span>
        )}
        <span className="truncate">{c.video_title}</span>
        <span className="ml-auto shrink-0">👍 {c.like_count}</span>
      </div>
      {isHot ? (
        <div className="mt-1 text-xs text-stone-600">
          {c.sub_replies && c.sub_replies.length > 0 ? (
            <>
              <span className="text-stone-400">已有热评(起草要绕开):</span>
              <ul className="mt-0.5 space-y-0.5">
                {c.sub_replies.slice(0, 3).map((t, i) => (
                  <li key={i} className={clsx('line-clamp-1', compact && i > 0 && 'hidden')}>
                    · {t}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <span className="text-stone-400">评论区还没有像样的热评,第一条就是位置</span>
          )}
        </div>
      ) : (
        <p className={clsx('mt-1 text-xs text-stone-600', compact && 'line-clamp-2')}>
          <span className="text-stone-400">{c.commenter}:</span> {c.comment_text}
        </p>
      )}
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
            href={manualReplyUrl}
            target="_blank"
            rel="noreferrer"
            title={
              isHot
                ? '打开这条视频,自己手动发一条根评论'
                : isXhs
                  ? '打开这条评论在小红书的位置,自己手动回复'
                  : '打开这条评论在B站的位置,自己手动回复'
            }
            className="rounded-lg border border-stone-200 px-2.5 py-1 text-xs text-stone-500 hover:border-(--brand) hover:text-(--brand)"
          >
            {isHot ? '去视频下评论 ↗' : isXhs ? '去小红书回 ↗' : '去B站回 ↗'}
          </a>
          {onHumanTouch && hasDraft && (
            <button
              onClick={() => void onHumanTouch(c)}
              title="AI 味检测:逐句扫机器痕迹,出报告"
              className="flex items-center gap-1 rounded-lg border border-stone-200 px-2.5 py-1 text-xs text-stone-400 hover:border-violet-300 hover:text-violet-500"
            >
              AI味
            </button>
          )}
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
