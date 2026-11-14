import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type AutomationStatus } from '../lib/api'
import ReplyPlanPanel from './ReplyPlanPanel'

const status: AutomationStatus = { platform: 'bili', enabled: false,
  config: { keywords: ['已有关键词'], freshness_a_hours: 48, freshness_b_hours: 168,
    daily_send_limit: 3, send_interval_seconds: 600, send_window_start: '10:00', send_window_end: '22:00' },
  funnel: { pending_review: 0, approved: 0, sent: 0, failed: 0, rejected: 0 }, stats: {},
  cycle: { running: false, last_run_at: '', last_summary: '', last_error: '' },
  sender: { can_send: false, wait_reason: '', cookie_cached: null },
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'strategyGet').mockResolvedValue({ profile_id: 'notes', name: '笔记产品', exists: true })
  vi.spyOn(api, 'automationStatus').mockResolvedValue(status)
  vi.spyOn(api, 'automationConfigUpdate').mockResolvedValue({} as Awaited<ReturnType<typeof api.automationConfigUpdate>>)
})

describe('渠道计划与执行约束分开', () => {
  it('轮询更新不覆盖正在编辑的词表', async () => {
    const { rerender } = render(<MemoryRouter><ReplyPlanPanel platform="bili" status={status} onSaved={vi.fn()} /></MemoryRouter>)
    const input = screen.getByLabelText('本轮寻找哪些讨论（每行一个关键词）')
    fireEvent.change(input, { target: { value: '我正在编辑' } })
    rerender(<MemoryRouter><ReplyPlanPanel platform="bili" status={{ ...status, config: { ...status.config, keywords: ['轮询词表'] } }} onSaved={vi.fn()} /></MemoryRouter>)
    expect((input as HTMLTextAreaElement).value).toBe('我正在编辑')
    await screen.findByText(/笔记产品/)
  })

  it('保存筛选计划不能附带放宽节奏、窗口或启用发送', async () => {
    render(<MemoryRouter><ReplyPlanPanel platform="bili" status={status} onSaved={vi.fn()} /></MemoryRouter>)
    fireEvent.change(screen.getByLabelText('本轮寻找哪些讨论（每行一个关键词）'), { target: { value: '新词' } })
    fireEvent.click(screen.getByRole('button', { name: '保存本平台计划' }))
    await waitFor(() => expect(api.automationConfigUpdate).toHaveBeenCalledOnce())
    const patch = vi.mocked(api.automationConfigUpdate).mock.calls[0][0]
    for (const key of ['daily_send_limit', 'send_interval_seconds', 'send_window_start', 'send_window_end', 'enabled']) expect(patch).not.toHaveProperty(key)
    expect(patch.keywords).toEqual(['新词'])
  })

  it('发现其他操作改过词表时保留输入并拒绝覆盖', async () => {
    vi.mocked(api.automationStatus).mockResolvedValue({ ...status, config: { ...status.config, keywords: ['别人已更新'] } })
    render(<MemoryRouter><ReplyPlanPanel platform="bili" status={status} onSaved={vi.fn()} /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: '保存本平台计划' }))
    await screen.findByText(/本平台计划已被其他操作更新/)
    expect(api.automationConfigUpdate).not.toHaveBeenCalled()
  })
})
