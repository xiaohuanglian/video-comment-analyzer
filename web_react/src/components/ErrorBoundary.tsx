import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, RotateCcw } from 'lucide-react'

/**
 * 页面级错误边界。
 *
 * 背景（2026-11-11 审计）：项目有 43 处 `catch (e)` 与 14 处
 * `catch(() => {})`，且**没有任何 ErrorBoundary**。任何一个渲染期异常
 * （例如后端返回结构变了、字段是 undefined）都会让整个工作台白屏，
 * 用户看不到是哪一页出错，也不知道能做什么。
 *
 * 边界只包页面内容，不包侧边栏——这样导航还能用，可以切到别的页面继续。
 */

interface Props {
  children: ReactNode
  /** 用于区分不同页面的名字，显示在 fallback 里 */
  scope?: string
}

interface State {
  error: Error | null
  info: ErrorInfo | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: null }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 浏览器控制台留全量堆栈，方便本地排查；
    // 页面里只给人看摘要，不糊一屏技术细节。
    console.error('[ErrorBoundary]', this.props.scope ?? '', error, info)
    this.setState({ info })
  }

  private reset = (): void => {
    this.setState({ error: null, info: null })
  }

  render(): ReactNode {
    const { error, info } = this.state
    if (!error) return this.props.children

    return (
      <div className="mx-auto max-w-2xl px-6 py-10">
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 space-y-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-amber-900">
            <AlertTriangle size={16} /> 这个页面出错了
            {this.props.scope && (
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-normal text-amber-700">
                {this.props.scope}
              </span>
            )}
          </h2>

          <p className="text-xs text-amber-800">
            内容没有丢，只是这一屏没能渲染出来。可以重试，或切到左侧其它页面继续操作。
          </p>

          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-white/70 p-3 text-[11px] text-stone-600">
            {error.message}
            {info?.componentStack ? `\n${info.componentStack.slice(0, 800)}` : ''}
          </pre>

          <button
            onClick={this.reset}
            className="flex items-center gap-1.5 rounded-lg bg-amber-900 px-3 py-1.5 text-xs font-medium text-white"
          >
            <RotateCcw size={12} /> 重试
          </button>
        </div>
      </div>
    )
  }
}
