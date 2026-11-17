import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type AutomationPlatform } from '../lib/api'
import { manualApi, type ManualList } from '../lib/manual-replies-api'
import ReplyListPage from './ReplyListPage'

const response = (platform: AutomationPlatform): ManualList => ({
  items: [{ id: `manual_${platform}`, platform, comment_id: '1', video_id: '2', commenter: `${platform}用户`, comment_text: `${platform}：请问这种动画用什么软件？`, video_title: '动画教程', reply_url: platform === 'dy' ? 'https://www.douyin.com/video/2' : platform === 'xhs' ? 'https://www.xiaohongshu.com/explore/2?xsec_token=test' : 'https://www.bilibili.com/video/av2#reply1', location_hint: '按昵称和评论原文查找', match_reason: '正在寻找动画工具', signal: '提问', worth: 8, profile_name: '测试业务', profile_id: 'test', like_count: 5, age_hours: 1, status: 'pending', mode: 'ai' }],
  total: 1, counts: { pending: 1, done: 0, skipped: 0 }, job: { running: false, phase: 'idle', message: '尚未开始筛选' },
})
beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'strategyProfiles').mockResolvedValue({ active_profile_id: 'test', profiles: [{ profile_id: 'test', name: '测试业务', is_configured: true }] } as Awaited<ReturnType<typeof api.strategyProfiles>>)
  vi.spyOn(manualApi, 'list').mockImplementation(async platform => response(platform))
  vi.spyOn(manualApi, 'screen').mockResolvedValue({ running: true, phase: 'starting', message: '筛选已开始' })
  vi.spyOn(manualApi, 'mark').mockResolvedValue({ ...response('bili').items[0], status: 'done' })
  vi.spyOn(api, 'approve')
  vi.spyOn(api, 'screenCollected')
})

describe('三平台人工待回复列表', () => {
  it.each([['bili', 'B 站'], ['dy', '抖音'], ['xhs', '小红书']] as const)('为 %s 显示评论、原因和正确的原帖入口，不自动回复', async (platform, name) => {
    render(<MemoryRouter initialEntries={[`/reply-list?platform=${platform}`]}><ReplyListPage /></MemoryRouter>)
    await screen.findByText(`${platform}：请问这种动画用什么软件？`)
    expect(screen.getByText(/正在寻找动画工具/)).toBeTruthy()
    const link = screen.getByRole('link', { name: `去${name}回复` })
    expect(link.getAttribute('href')).toBe(response(platform).items[0].reply_url)
    expect(manualApi.screen).not.toHaveBeenCalled()
    expect(manualApi.mark).not.toHaveBeenCalled()
    expect(api.approve).not.toHaveBeenCalled()
  })
  it('只有点击我已回复才记录，不进入自动发送队列', async () => {
    render(<MemoryRouter><ReplyListPage /></MemoryRouter>)
    await screen.findByText('bili：请问这种动画用什么软件？')
    fireEvent.click(screen.getByRole('button', { name: '我已回复' }))
    await waitFor(() => expect(manualApi.mark).toHaveBeenCalledWith('bili', 'manual_bili', 'done'))
    expect(api.approve).not.toHaveBeenCalled()
    expect(api.screenCollected).not.toHaveBeenCalled()
  })
  it('AI 筛选必须明确选业务，规则模式可以无密钥启动', async () => {
    render(<MemoryRouter><ReplyListPage /></MemoryRouter>)
    await screen.findByText('bili：请问这种动画用什么软件？')
    fireEvent.click(screen.getByText('筛选设置与新增评论'))
    expect((screen.getByRole('button', { name: '筛选待回复评论' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('怎样筛选？'), { target: { value: 'rules' } })
    await waitFor(() => expect((screen.getByRole('button', { name: '筛选待回复评论' }) as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: '筛选待回复评论' }))
    await waitFor(() => expect(manualApi.screen).toHaveBeenCalledWith('bili', { mode: 'rules', profile_id: '', goal: '', limit: 30, days: 30 }))
    expect(api.approve).not.toHaveBeenCalled()
  })
  it('从 B 站切到抖音时不会残留 B 站的评论', async () => {
    render(<MemoryRouter><ReplyListPage /></MemoryRouter>)
    await screen.findByText('bili：请问这种动画用什么软件？')
    fireEvent.click(screen.getByRole('button', { name: '抖音' }))
    await screen.findByText('dy：请问这种动画用什么软件？')
    expect(screen.queryByText('bili：请问这种动画用什么软件？')).toBeNull()
  })
})
