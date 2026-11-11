import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import CandidateCard from './CandidateCard'
import type { AutomationCandidate } from '../lib/api'

/**
 * 两张候选卡长得很像，但动的是完全不同的东西：
 *   - reply：回复某个具体的人（平台发通知，触达确定，只在楼里可见）
 *   - hot_comment：直接评在视频下（零通知，和已有热评按赞数排序）
 *
 * 混在一张卡上显示会让审批的人搞错自己在批什么，所以这里锁死两者的可辨识差异。
 */

function base(over: Partial<AutomationCandidate> = {}): AutomationCandidate {
  return {
    id: 'c_c1',
    comment_id: 'c1',
    video_id: 'v1',
    video_title: '这个视频讲 AI 视频',
    video_url: 'https://www.bilibili.com/video/v1',
    commenter: '路人甲',
    comment_text: '请问这种动画用什么软件做的呀',
    like_count: 3,
    age_hours: 5,
    signal: '问工具/怎么做',
    tier: 'A',
    lane: 'help',
    action: 'reply',
    draft: '用即梦，先固定参考图',
    lint_warnings: [],
    draft_source: 'llm',
    status: 'pending_review',
    created_at: '2026-11-11T10:00:00',
    attempts: 0,
    ...over,
  }
}

// 内联操作行只在能批准/拒绝时出现（待审条目），所以这里给个空实现
const noop = () => undefined

// 每个用例都渲染一张卡；不清理会互相匹配到对方的文案
afterEach(cleanup)

describe('CandidateCard 动作区分', () => {
  it('回复条目显示对方评论，手动入口带评论锚点', () => {
    render(<CandidateCard c={base()} onApprove={noop} onReject={noop} />)
    expect(screen.getByText('回复')).toBeTruthy()
    expect(screen.getByText(/路人甲/)).toBeTruthy()
    expect(screen.getByText(/请问这种动画/)).toBeTruthy()
    const link = screen.getByText('去B站回 ↗').closest('a')!
    expect(link.getAttribute('href')).toBe('https://www.bilibili.com/video/v1#replyc1')
  })

  it('根评论条目不再显示“回复谁”，而是给出要绕开的已有热评', () => {
    render(
      <CandidateCard
        onApprove={noop}
        onReject={noop}
        c={base({
          action: 'hot_comment',
          comment_id: '0',
          commenter: '',
          comment_text: '',
          competition: 'cold',
          sub_replies: ['第一条热评', '第二条热评'],
        })}
      />,
    )
    expect(screen.getByText('根评论')).toBeTruthy()
    expect(screen.getByText(/已有热评/)).toBeTruthy()
    expect(screen.getByText(/第一条热评/)).toBeTruthy()
    expect(screen.queryByText(/路人甲/)).toBeNull()
    const link = screen.getByText('去视频下评论 ↗').closest('a')!
    // 根评论没有目标评论，不能拼 #reply0
    expect(link.getAttribute('href')).toBe('https://www.bilibili.com/video/v1')
  })

  it('同视频两种都做时给出明确标记', () => {
    render(<CandidateCard c={base({ video_route: 'both' })} />)
    expect(screen.getByText('两条都做')).toBeTruthy()
  })

  it('竞争判定写进徽章提示，人能看到为什么判成该发根评论', () => {
    render(
      <CandidateCard
        c={base({ action: 'hot_comment', comment_id: '0', competition: 'open', sub_replies: [] })}
      />,
    )
    const badge = screen.getByText('根评论')
    expect(badge.getAttribute('title')).toContain('还有空位')
    expect(screen.getByText(/评论区还没有像样的热评/)).toBeTruthy()
  })
})
