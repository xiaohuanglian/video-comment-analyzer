/**
 * 纯 Node 前端逻辑验证（不依赖 vitest 的 worker 池）。
 *
 * 为什么需要第二个入口：本机 Node v26 与 vitest 的 worker 在启动阶段会挂住
 * （连一个 expect(1+1) 的 smoke 都起不来，已排除是测试代码问题）。
 * CI 用 Node 20 跑 vitest 没问题；但本机想验证时得有一条能跑通的路。
 *
 * 跑法：node --experimental-strip-types src/lib/api.errors.check.ts
 */

import assert from 'node:assert/strict'
import { describeError } from './api.ts'

let passed = 0
const failures: string[] = []

function check(name: string, fn: () => void): void {
  try {
    fn()
    passed += 1
    console.log(`  ok   ${name}`)
  } catch (error) {
    failures.push(`${name}: ${(error as Error).message}`)
    console.log(`  FAIL ${name}`)
  }
}

console.log('describeError 解析后端错误信封')

check('取出 error.message', () => {
  const err = describeError(
    400,
    'Bad Request',
    JSON.stringify({ ok: false, error: { code: 'BAD_INPUT', message: '先勾选至少一个评论文件' } }),
  )
  assert.equal(err.message, '先勾选至少一个评论文件')
  assert.equal(err.code, 'BAD_INPUT')
  assert.equal(err.status, 400)
})

check('hint 拼进消息', () => {
  const err = describeError(
    403,
    'Forbidden',
    JSON.stringify({ ok: false, error: { code: 'NEED_LOGIN', message: '登录态失效', hint: '去设置页扫码' } }),
  )
  assert.match(err.message, /登录态失效/)
  assert.match(err.message, /去设置页扫码/)
})

check('429 保留 retry_after_seconds', () => {
  const err = describeError(
    429,
    'Too Many Requests',
    JSON.stringify({ ok: false, error: { code: 'RATE_LIMITED', message: '冷却中', retry_after_seconds: 120 } }),
  )
  assert.equal(err.retryAfterSeconds, 120)
})

check('兼容 detail 字段', () => {
  assert.equal(describeError(404, 'Not Found', JSON.stringify({ detail: '任务不存在' })).message, '任务不存在')
})

check('非 JSON 退回状态码', () => {
  const err = describeError(502, 'Bad Gateway', '<html>gateway error</html>')
  assert.match(err.message, /502/)
  assert.match(err.message, /gateway error/)
})

check('空响应体不崩', () => {
  const err = describeError(500, 'Internal Server Error', '')
  assert.equal(err.message, '500 Internal Server Error')
})

console.log(`\n通过 ${passed}，失败 ${failures.length}`)
if (failures.length) {
  console.error('\n' + failures.join('\n'))
  process.exit(1)
}
