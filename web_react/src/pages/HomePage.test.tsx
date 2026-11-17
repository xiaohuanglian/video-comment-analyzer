import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import { settingsApi, type SystemStatus } from '../lib/settings-api'
import HomePage from './HomePage'

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(settingsApi, 'systemStatus').mockResolvedValue({ model: { configured: true }, channels: [] } as unknown as SystemStatus)
  vi.spyOn(api, 'crawlerLocalData').mockResolvedValue({ platforms: { bili: { comments: 120, contents: 3, batches: 1 } }, batches: [] })
  vi.spyOn(api, 'strategyProfiles').mockResolvedValue({ active_profile_id: 'test', profiles: [{ profile_id: 'test', name: '测试业务', is_configured: true }] } as Awaited<ReturnType<typeof api.strategyProfiles>>)
  vi.spyOn(api, 'modelSettingsTest')
  vi.spyOn(api, 'crawlerStart')
})

describe('新手首页状态', () => {
  it('读取真实准备状态，不自动测试模型或采集', async () => {
    render(<MemoryRouter><HomePage /></MemoryRouter>)
    await screen.findByText('本地已有 120 条评论')
    expect(screen.getByText('当前档案：测试业务')).toBeTruthy()
    expect(screen.getByText('已填写配置，使用前可测试连接')).toBeTruthy()
    expect(api.modelSettingsTest).not.toHaveBeenCalled()
    expect(api.crawlerStart).not.toHaveBeenCalled()
  })
  it('部分状态失败不显示为零数据或未配置', async () => {
    vi.mocked(settingsApi.systemStatus).mockRejectedValue(new Error('offline'))
    vi.mocked(api.strategyProfiles).mockRejectedValue(new Error('offline'))
    render(<MemoryRouter><HomePage /></MemoryRouter>)
    await screen.findByRole('alert')
    expect(screen.getByText('本地已有 120 条评论')).toBeTruthy()
    expect(screen.getAllByText('等待检查')).toHaveLength(2)
    expect(screen.queryByText(/未配置模型/)).toBeNull()
  })
})
