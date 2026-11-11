import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import XhsNotesPanel from './XhsNotesPanel'
import { formatCount } from '../lib/format'

/**
 * 采集页「小红书笔记列表」：用户要的是"看见标题 + 互动数据 + 能点开原帖"，
 * 所以这里锁三件事——字段渲染、原帖链接、按关键词点选筛选。
 */

const notes = vi.fn()

vi.mock('../lib/api', () => ({
  api: {
    xhsNotes: (...args: unknown[]) => notes(...args),
  },
}))

const RESPONSE = {
  batch: '20261111_200159',
  batches: [{ batch: '20261111_200159', created_at: '2026-11-11 20:01:59', total: 2 }],
  total: 2,
  limit: 500,
  offset: 0,
  keyword_counts: { 信息过载: 1, 戒短视频: 1 },
  items: [
    {
      note_id: 'n3',
      keyword: '信息过载',
      title: '别再看和你无关的信息',
      author: '心理师 bestta',
      note_type: 'normal',
      liked: 32681,
      collected: 9000,
      comments: 479,
      url: 'https://www.xiaohongshu.com/explore/n3?xsec_token=t3',
    },
    {
      note_id: 'n2',
      keyword: '戒短视频',
      title: '亲测45天，大脑真的能被重新训练',
      author: '老金的开源人生',
      note_type: 'video',
      liked: 8152,
      collected: 3001,
      comments: 323,
      url: 'https://www.xiaohongshu.com/explore/n2?xsec_token=t2',
    },
  ],
}

beforeEach(() => {
  notes.mockReset()
  notes.mockResolvedValue(RESPONSE)
})

describe('formatCount', () => {
  it('过万收口成 x.x万，十万以上不带小数', () => {
    expect(formatCount(0)).toBe('0')
    expect(formatCount(999)).toBe('999')
    expect(formatCount(8152)).toBe('8,152')
    expect(formatCount(32681)).toBe('3.3万')
    expect(formatCount(193466)).toBe('19万')
  })
})

describe('XhsNotesPanel', () => {
  it('渲染标题、作者、互动数与跳原帖箭头', async () => {
    render(<XhsNotesPanel />)

    const link = await screen.findByRole('link', { name: /别再看和你无关的信息/ })
    expect(link.getAttribute('href')).toContain('/explore/n3')
    expect(link.getAttribute('target')).toBe('_blank')
    // 箭头图标就是"能点开"的可视提示，缺了这条需求就没满足
    expect(link.querySelector('svg')).toBeTruthy()

    expect(screen.getByText('心理师 bestta')).toBeTruthy()
    expect(screen.getByText('3.3万')).toBeTruthy()
    expect(screen.getByText('9,000')).toBeTruthy()
    expect(screen.getByText('479')).toBeTruthy()
    expect(screen.getByText('视频')).toBeTruthy()
    expect(screen.getByText(/共 2 条/)).toBeTruthy()
  })

  it('点关键词胶囊会用该词重新查询', async () => {
    render(<XhsNotesPanel />)
    await screen.findByRole('link', { name: /别再看和你无关的信息/ })

    screen.getByRole('button', { name: '戒短视频 1' }).click()

    await waitFor(() => {
      expect(notes).toHaveBeenLastCalledWith(expect.objectContaining({ q: '戒短视频' }))
    })
  })

  it('没有批次时给出可执行的下一步', async () => {
    notes.mockResolvedValue({ ...RESPONSE, batch: '', batches: [], total: 0, items: [], keyword_counts: {} })
    render(<XhsNotesPanel />)
    expect(await screen.findByText(/还没有关键词笔记/)).toBeTruthy()
  })

  it('接口报错时显示错误而不是白屏', async () => {
    notes.mockRejectedValue(new Error('后端挂了'))
    render(<XhsNotesPanel />)
    expect(await screen.findByText('后端挂了')).toBeTruthy()
  })
})
