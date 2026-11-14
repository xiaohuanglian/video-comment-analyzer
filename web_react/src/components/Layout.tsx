import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Home, Download, Bot, Lightbulb, PenLine, Settings, BookOpen, Rocket, Sparkles, ScanSearch, MessageSquare } from 'lucide-react'
import clsx from 'clsx'
import ErrorBoundary from './ErrorBoundary'

const NAV = [
  { to: '/', label: '增长工作台', icon: Home, end: true },
  { to: '/assistant', label: 'AI 助手', icon: MessageSquare },
  { to: '/collect', label: '采集', icon: Download },
  { to: '/insight', label: '评论洞察', icon: ScanSearch },
  { to: '/wechat', label: '公众号', icon: BookOpen },
  { to: '/automation', label: '回复自动化', icon: Bot },
  { to: '/topics', label: '选题中心', icon: Lightbulb },
  { to: '/writer', label: '文案生成', icon: PenLine },
  { to: '/studio', label: '创作中台', icon: Sparkles },
  { to: '/publish', label: '发布复盘', icon: Rocket },
  { to: '/settings', label: '设置', icon: Settings },
]

export default function Layout() {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <div className="flex h-full flex-col md:flex-row">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-stone-200 bg-white px-4 py-3 md:hidden">
        <span className="shrink-0 text-sm font-semibold">增长工作台</span>
        <select aria-label="工作台页面" className="min-w-0 rounded-lg border border-stone-200 px-2 py-1.5 text-sm" value={location.pathname} onChange={event => navigate(event.target.value)}>
          {NAV.map(item => <option key={item.to} value={item.to}>{item.label}</option>)}
        </select>
      </header>
      <aside className="hidden w-52 shrink-0 flex-col border-r border-stone-200 bg-white md:flex">
        <div className="px-5 py-4 text-lg font-semibold tracking-tight">
          增长工作台
          <span className="mt-1 block text-xs font-normal text-stone-400">理解 · 执行 · 验证 · 积累</span>
        </div>
        <nav className="flex-1 px-3 space-y-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-orange-50 text-(--brand) font-medium'
                    : 'text-stone-600 hover:bg-stone-100',
                )
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>

      </aside>
      <main className="min-h-0 flex-1 min-w-0 overflow-y-auto">
        {/*
          页面级错误边界：任何一页渲染崩溃都只影响这一屏，
          侧边栏仍在，用户能切到别的页面继续干活（此前会整站白屏）。
        */}
        <ErrorBoundary scope="工作台">
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  )
}
