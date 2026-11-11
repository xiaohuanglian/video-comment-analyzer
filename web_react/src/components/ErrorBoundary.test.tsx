import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import ErrorBoundary from './ErrorBoundary'

/**
 * 错误边界：任何页面渲染崩溃都不能让整站白屏。
 *
 * 背景（2026-11-11）：项目有 43 处 `catch (e)` 与 14 处 `catch(() => {})`，
 * 却**没有任何 ErrorBoundary**——后端字段一变、某处 undefined 一取，
 * 整个工作台就白屏，用户既看不到哪一页坏了，也做不了任何操作。
 */

function Boom(): never {
  throw new Error('后端返回结构变了：runs 不是数组')
}

const consoleError = console.error

afterEach(() => {
  console.error = consoleError
})

describe('ErrorBoundary', () => {
  it('正常渲染子节点', () => {
    render(
      <ErrorBoundary>
        <div>正常内容</div>
      </ErrorBoundary>,
    )
    expect(screen.getByText('正常内容')).toBeTruthy()
  })

  it('子组件崩溃时显示兜底而不是白屏', () => {
    console.error = vi.fn() // React 会把错误也打到 console，这里静音
    render(
      <ErrorBoundary scope="评论洞察">
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByText(/这个页面出错了/)).toBeTruthy()
    expect(screen.getByText('评论洞察')).toBeTruthy()
  })

  it('兜底里带上原始错误信息，便于定位', () => {
    console.error = vi.fn()
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByText(/runs 不是数组/)).toBeTruthy()
  })

  it('提示用户内容没丢、可以切到别的页面', () => {
    console.error = vi.fn()
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByText(/内容没有丢/)).toBeTruthy()
  })
})
