import { describe, expect, it, vi, afterEach } from 'vitest'
import { api, describeError } from './api'

/**
 * API 客户端的错误契约。
 *
 * 背景（2026-11-11）：后端统一了错误信封
 * `{ ok: false, error: { code, message, hint, retry_after_seconds } }`，
 * 但前端原先只会抛 `${status} ${statusText}: ${原始 JSON 文本}`，
 * 用户看到的是 200 个字符的 JSON——等于没提示。
 */

const realFetch = globalThis.fetch

function mockFetchOnce(response: Response) {
  globalThis.fetch = vi.fn().mockResolvedValue(response) as unknown as typeof fetch
}

afterEach(() => {
  globalThis.fetch = realFetch
  vi.restoreAllMocks()
})

describe('describeError 解析后端错误信封', () => {
  it('取出 error.message 而不是把整段 JSON 丢给用户', () => {
    const err = describeError(
      400,
      'Bad Request',
      JSON.stringify({
        ok: false,
        error: { code: 'BAD_INPUT', message: '先勾选至少一个评论文件', hint: '', retry_after_seconds: null },
      }),
    )
    expect(err.message).toBe('先勾选至少一个评论文件')
    expect(err.code).toBe('BAD_INPUT')
    expect(err.status).toBe(400)
  })

  it('带 hint 时拼在括号里，给人下一步动作', () => {
    const err = describeError(
      403,
      'Forbidden',
      JSON.stringify({ ok: false, error: { code: 'NEED_LOGIN', message: '登录态失效', hint: '去设置页扫码' } }),
    )
    expect(err.message).toContain('登录态失效')
    expect(err.message).toContain('去设置页扫码')
    expect(err.hint).toBe('去设置页扫码')
  })

  it('429 保留 retry_after_seconds', () => {
    const err = describeError(
      429,
      'Too Many Requests',
      JSON.stringify({
        ok: false,
        error: { code: 'RATE_LIMITED', message: '平台冷却中', retry_after_seconds: 120 },
      }),
    )
    expect(err.code).toBe('RATE_LIMITED')
    expect(err.retryAfterSeconds).toBe(120)
  })

  it('兼容旧的 detail 字段（FastAPI 默认形状）', () => {
    const err = describeError(404, 'Not Found', JSON.stringify({ detail: '任务不存在' }))
    expect(err.message).toBe('任务不存在')
  })

  it('非 JSON 响应退回状态码 + 截断文本，不抛解析异常', () => {
    const err = describeError(502, 'Bad Gateway', '<html>gateway error</html>')
    expect(err.message).toContain('502')
    expect(err.message).toContain('gateway error')
  })

  it('空响应体也能给出可读信息', () => {
    const err = describeError(500, 'Internal Server Error', '')
    expect(err.message).toBe('500 Internal Server Error')
    expect(err.status).toBe(500)
  })
})

describe('api 请求层', () => {
  it('成功时返回解析后的 JSON', async () => {
    mockFetchOnce(
      new Response(JSON.stringify({ runs: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    expect(await api.insightRuns()).toEqual({ runs: [] })
  })

  it('失败时抛出带 code 的 ApiError', async () => {
    mockFetchOnce(
      new Response(
        JSON.stringify({ ok: false, error: { code: 'BAD_INPUT', message: '参数不对' } }),
        { status: 400 },
      ),
    )
    await expect(api.insightRuns()).rejects.toMatchObject({ code: 'BAD_INPUT' })
  })

  it('POST 带 JSON body 与 Content-Type', async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ run_id: 'r1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    globalThis.fetch = spy as unknown as typeof fetch

    await api.insightCreateRun({ file_paths: ['a.csv'], use_mock: true })

    const [url, init] = spy.mock.calls[0]
    expect(String(url)).toContain('/api/analysis/runs')
    expect(init.method).toBe('POST')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body)).toMatchObject({ file_paths: ['a.csv'], use_mock: true })
  })

  it('所有请求都走 /api 前缀（开发代理与生产同源都靠它）', async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    globalThis.fetch = spy as unknown as typeof fetch

    await api.insightRuns()
    expect(String(spy.mock.calls[0][0]).startsWith('/api/')).toBe(true)
  })
})

describe('洞察页面依赖的端点路径', () => {
  const cases: [string, () => Promise<unknown>, string][] = [
    ['insightSources', () => api.insightSources(), '/api/analysis/sources'],
    ['insightRuns', () => api.insightRuns(), '/api/analysis/runs'],
    ['insightProfiles', () => api.insightProfiles(), '/api/analysis/profiles'],
    ['insightPricing', () => api.insightPricing(), '/api/analysis/pricing'],
  ]

  for (const [name, call, expected] of cases) {
    it(`${name} 命中 ${expected}`, async () => {
      const spy = vi.fn().mockResolvedValue(
        new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
      )
      globalThis.fetch = spy as unknown as typeof fetch
      await call()
      expect(String(spy.mock.calls[0][0])).toContain(expected)
    })
  }
})
