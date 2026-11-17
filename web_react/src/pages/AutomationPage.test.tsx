import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type AutomationStatus } from '../lib/api'
import AutomationPage from './AutomationPage'

const status: AutomationStatus = {
  enabled: false, platform: 'bili', config: {},
  funnel: { pending_review: 0, approved: 0, sent: 0, failed: 0, rejected: 0 }, stats: {},
  cycle: { running: false, last_run_at: '', last_summary: '', last_error: '' },
  sender: { can_send: false, wait_reason: '', cookie_cached: false },
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'strategyProfiles').mockResolvedValue({ active_profile_id: '早播', profiles: ['造浪', '早播'].map(id => ({ profile_id: id, name: id, niche: '', target_audience: '', is_active: id === '早播', is_configured: true, updated_at: '' })) })
  vi.spyOn(api, 'strategyGet').mockImplementation(async id => ({ profile_id: id || '早播', name: id || '早播', target_audience: `${id}受众`, goal: `${id}试用` }))
  vi.spyOn(api, 'automationStatus').mockResolvedValue(status)
  vi.spyOn(api, 'candidates').mockResolvedValue([])
  vi.spyOn(api, 'screenCollected').mockResolvedValue({ ok: true, message: '已开始' })
})
afterEach(cleanup)

describe('回复任务明确绑定产品', () => {
  it('不借用全局早播档案替用户决定产品', async () => {
    render(<MemoryRouter><AutomationPage /></MemoryRouter>)
    await screen.findByRole('option', { name: '造浪 · 造浪' })
    const run = screen.getByRole('button', { name: /筛选值得回复的用户/ }) as HTMLButtonElement
    expect(run.disabled).toBe(true)
    expect(screen.queryByLabelText('本次回复目标')).toBeNull()
  })

  it('筛选请求携带所选产品和目标，切换后队列查询同步隔离', async () => {
    render(<MemoryRouter><AutomationPage /></MemoryRouter>)
    await screen.findByRole('option', { name: '造浪 · 造浪' })
    fireEvent.change(screen.getByLabelText('回复任务产品'), { target: { value: '造浪' } })
    const goal = await screen.findByLabelText('本次回复目标')
    fireEvent.change(goal, { target: { value: '让新手完成第一条内容' } })
    fireEvent.click(screen.getByRole('button', { name: /筛选值得回复的用户/ }))
    await waitFor(() => expect(api.screenCollected).toHaveBeenCalledWith(50, true, 'bili', '造浪', '让新手完成第一条内容', 'recommend'))
    await waitFor(() => expect((screen.getByLabelText('回复任务产品') as HTMLSelectElement).disabled).toBe(false))
    fireEvent.change(screen.getByLabelText('回复任务产品'), { target: { value: '早播' } })
    await waitFor(() => expect(api.candidates).toHaveBeenLastCalledWith('pending_review', 100, 'bili', '早播'))
    expect((await screen.findByLabelText('本次回复目标') as HTMLTextAreaElement).value).toBe('早播试用')
  })
})

it('添加图片后保留未保存的文字，并显示附件预览', async () => {
  const candidate = { id: 'c1', comment_id: '1', video_id: 'v', video_title: '原视频', video_url: 'https://www.bilibili.com/video/v', commenter: '用户', comment_text: '想知道怎么做', like_count: 0, age_hours: 1, signal: '需求', tier: 'A', draft: '原草稿', lint_warnings: [], draft_source: 'llm', status: 'pending_review' as const, created_at: '', attempts: 0, profile_id: '造浪', profile_name: '造浪', attachments: [] }
  vi.mocked(api.candidates).mockResolvedValue([candidate])
  const attachment = { attachment_id: 'abc', extension: 'png', mime_type: 'image/png', size: 10, width: 4, height: 5, original_name: '示意.png' }
  vi.spyOn(api, 'uploadReplyImage').mockResolvedValue({ ok: true, item: { ...candidate, attachments: [attachment] } })
  render(<MemoryRouter initialEntries={['/automation?profile=造浪']}><AutomationPage /></MemoryRouter>)
  fireEvent.click(await screen.findByText('编辑草稿 →'))
  const dialog = await screen.findByRole('dialog')
  const textarea = dialog.querySelector('textarea')!
  fireEvent.change(textarea, { target: { value: '尚未保存的新文字' } })
  const file = new File(['fixture'], '示意.png', { type: 'image/png' })
  fireEvent.change(screen.getByLabelText('添加回复图片'), { target: { files: [file] } })
  await waitFor(() => expect(api.uploadReplyImage).toHaveBeenCalledWith('c1', file, 'bili'))
  expect(await screen.findByAltText('示意.png')).toBeTruthy()
  expect(textarea.value).toBe('尚未保存的新文字')
})

it('空队列解释产品未筛选和评论时效，不暗示需要重新采集', async () => {
  render(<MemoryRouter initialEntries={['/automation?profile=造浪']}><AutomationPage /></MemoryRouter>)
  expect(await screen.findByText(/尚无该产品的筛选记录/)).toBeTruthy()
  expect(screen.getByText(/关键词只用于在平台搜索视频/)).toBeTruthy()
})

it('已筛选但全部超龄时展示真实漏斗，不把零条称为没有需求', async () => {
  vi.mocked(api.automationStatus).mockResolvedValue({ ...status, cycle: { ...status.cycle, last_summary: JSON.stringify({ profile_id: '造浪', comments: 10, funnel: { stale: 10 }, llm_screen: { examined: 0 }, new_candidates: 0 }) } })
  render(<MemoryRouter initialEntries={['/automation?profile=造浪']}><AutomationPage /></MemoryRouter>)
  expect(await screen.findByText(/最近一次读取 10 条评论：10 条超出回复时效/)).toBeTruthy()
  expect(screen.getByText(/零条不等于没有潜在需求/)).toBeTruthy()
})
