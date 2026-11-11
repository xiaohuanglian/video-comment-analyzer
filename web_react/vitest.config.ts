import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// 前端测试此前完全不存在（2026-11-11 审计）。这里先覆盖两类最容易悄悄坏掉的东西：
//   1. api.ts 的错误处理契约（后端统一错误信封后，前端必须能读出来）
//   2. 组件在异常时不至于整站白屏（ErrorBoundary）
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.{ts,tsx}'],
    // 统一在每个用例后卸载 React 树：singleThread 下 document 跨文件复用，
    // 只靠 @testing-library 的自动 cleanup 会出现"谁先跑谁影响别人"的偶发失败。
    setupFiles: ['./src/test/setup.ts'],
    // Node 26 + vitest 的 worker 池会在启动阶段挂住（本机实测：
    // 连一个 expect(1+1) 的 smoke 测试都起不来）。单进程内跑，
    // 代价是慢一点，但稳定；CI 用的是 Node 20，不受此影响。
    pool: 'threads',
    poolOptions: { threads: { singleThread: true } },
    fileParallelism: false,
  },
})
