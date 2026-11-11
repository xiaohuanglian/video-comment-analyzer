/**
 * vitest 全局 setup。
 *
 * 只做一件事：每个用例结束后卸载 React 树。
 *
 * 为什么必须显式做（2026-11-11）：vitest 配了 `singleThread` + `fileParallelism: false`，
 * jsdom 的 document 会在同一线程里跨文件复用。@testing-library 的自动 cleanup 依赖
 * 全局 afterEach 注册，实测并非每个文件都生效——表现为**顺序依赖的偶发失败**：
 * 某个文件的用例先跑过之后，`ErrorBoundary.test.tsx` 里后两条用例会撞上
 * "Found multiple elements with the text: …"（上一轮的 DOM 还在）。
 * 这里统一注册，跟文件顺序无关。
 */

import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
})
