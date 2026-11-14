import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type CostSummary } from '../lib/api'
import { growthApi, type SystemStatus } from '../lib/growth-api'
import SettingsPage from './SettingsPage'

const status: SystemStatus = { model: { configured: true, base_url: 'https://gateway.example', model: 'test-model', api_key_masked: '****1234', connection: 'not_checked', environment_override: false },
  channels: [{ platform: 'xhs', label: '小红书', state: 'manual_hold', login: 'not_checked', manual_hold: true }], note: '仅检查本地记录，未验证登录有效性。' }

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(growthApi, 'systemStatus').mockResolvedValue(status)
  vi.spyOn(api, 'costsSummary').mockResolvedValue({ today: { calls: 0, total_tokens: 0 }, pricing: { configured: false }, by_feature: [] } as unknown as CostSummary)
  vi.spyOn(api, 'modelSettingsTest').mockResolvedValue({ ok: true, reply: 'ok' })
  vi.spyOn(api, 'biliLogin').mockResolvedValue({} as Awaited<ReturnType<typeof api.biliLogin>>)
  vi.spyOn(api, 'automationConfigUpdate')
})

describe('设置只维护连接与异常', () => {
  it('打开设置不测试连接、不登录、不修改执行策略', async () => {
    render(<MemoryRouter><SettingsPage /></MemoryRouter>)
    await screen.findByText(/模型已配置，连接尚未验证/)
    expect(screen.getByText(/小红书：人工停采记录待核查/)).toBeTruthy()
    expect(api.modelSettingsTest).not.toHaveBeenCalled()
    expect(api.biliLogin).not.toHaveBeenCalled()
    expect(api.automationConfigUpdate).not.toHaveBeenCalled()
    expect(screen.queryByLabelText(/目标关键词/)).toBeNull()
    expect(screen.queryByRole('spinbutton')).toBeNull()
    expect(screen.queryByText(/发送通道正常/)).toBeNull()
  })

  it('只有主动测试后才显示成功，编辑配置后回到未验证', async () => {
    render(<MemoryRouter><SettingsPage /></MemoryRouter>)
    await screen.findByText(/模型已配置，连接尚未验证/)
    fireEvent.click(screen.getByRole('button', { name: '测试这组连接' }))
    await screen.findByText(/这组模型连接刚刚测试成功/)
    fireEvent.change(screen.getByLabelText('模型名称'), { target: { value: 'new-model' } })
    expect(screen.queryByText(/这组模型连接刚刚测试成功/)).toBeNull()
    expect(screen.getByText(/模型已配置，连接尚未验证/)).toBeTruthy()
  })

  it('刷新状态不覆盖正在编辑的模型配置', async () => {
    render(<MemoryRouter><SettingsPage /></MemoryRouter>)
    await screen.findByText(/模型已配置，连接尚未验证/)
    fireEvent.change(screen.getByLabelText('网关根地址'), { target: { value: 'https://new.example' } })
    fireEvent.click(screen.getByRole('button', { name: '刷新本地状态' }))
    await waitFor(() => expect(growthApi.systemStatus).toHaveBeenCalledTimes(2))
    expect((screen.getByLabelText('网关根地址') as HTMLInputElement).value).toBe('https://new.example')
  })
})
