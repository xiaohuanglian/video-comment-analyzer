/**
 * 数字展示收口（列表里的互动数）。
 *
 * 单独放一个文件而不是放在组件里：组件文件只导出组件，热更新才不会整块失效
 * （oxlint 的 react(only-export-components) 就是在提醒这件事）。
 */

/** 过万写成 x.x万，十万以上不带小数：6 位数字挤在表格里看不出量级 */
export function formatCount(n: number): string {
  if (!n) return '0'
  if (n >= 10000) return `${(n / 10000).toFixed(n >= 100000 ? 0 : 1)}万`
  return n.toLocaleString()
}
