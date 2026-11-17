import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type CrawlerStatus } from '../lib/api'
import CollectPanel from './CollectPanel'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'crawlerStatusFresh').mockResolvedValue({ status: 'idle' })
  vi.spyOn(api, 'crawlerLogs').mockResolvedValue({ logs: [] })
  vi.spyOn(api, 'crawlerStart').mockResolvedValue({ status: 'ok' })
})
const mount = () => render(<MemoryRouter><CollectPanel /></MemoryRouter>)

describe('新手采集流程', () => {
  it('打开不自动采集，提交时规范中文输入并保留小批量上限', async () => {
    mount()
    await screen.findByText('可以开始')
    expect(api.crawlerStart).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('2. 输入搜索关键词'), { target: { value: '视频剪辑，AI教程，视频剪辑' } })
    fireEvent.click(screen.getByRole('button', { name: '开始采集评论' }))
    await waitFor(() => expect(api.crawlerStart).toHaveBeenCalledWith({ platform: 'bili', crawler_type: 'search', keywords: '视频剪辑,AI教程', max_notes_count: 3, max_comments_count: 50 }))
  })
  it('粘贴网址会解释正确输入方式，不向后台提交', async () => {
    mount()
    await screen.findByText('可以开始')
    fireEvent.change(screen.getByLabelText('2. 输入搜索关键词'), { target: { value: 'https://example.com/video' } })
    fireEvent.click(screen.getByRole('button', { name: '开始采集评论' }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('请不要粘贴网址'))
    expect(api.crawlerStart).not.toHaveBeenCalled()
  })
  it('零条评论失败也显示原因、下一步与冷却时间', async () => {
    vi.mocked(api.crawlerStatusFresh).mockResolvedValue({ status: 'error', comments_crawled: 0, error_message: '需要登录', error_hint: '先完成官方扫码登录', retry_after_seconds: 90 } as CrawlerStatus)
    mount()
    await screen.findByText('错误:需要登录')
    expect(screen.getByText(/下一步：先完成官方扫码登录/)).toBeTruthy()
    expect(screen.getByText(/剩余等待约 2 分钟/)).toBeTruthy()
  })
  it('后端断开时明确告知并禁止提交', async () => {
    vi.mocked(api.crawlerStatusFresh).mockRejectedValue(new Error('offline'))
    mount()
    await screen.findByRole('alert')
    fireEvent.change(screen.getByLabelText('2. 输入搜索关键词'), { target: { value: '测试' } })
    expect((screen.getByRole('button', { name: '开始采集评论' }) as HTMLButtonElement).disabled).toBe(true)
    expect(api.crawlerStart).not.toHaveBeenCalled()
  })
})
