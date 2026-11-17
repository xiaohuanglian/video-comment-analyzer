import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Download, Bot, Settings, ScanSearch, Users, House, CircleHelp, ListChecks } from 'lucide-react'
import clsx from 'clsx'
import ErrorBoundary from './ErrorBoundary'

const NAV = [
  { to: '/', label: '开始使用', icon: House, end: true },
  { to: '/collect', label: '1. 采集评论', icon: Download },
  { to: '/reply-list', label: '2. 待回复列表', icon: ListChecks },
  { to: '/insight', label: '需求分析（可选）', icon: ScanSearch },
  { to: '/automation', label: '受控发送（高级）', icon: Bot },
  { to: '/profiles', label: '业务档案', icon: Users },
  { to: '/settings', label: '连接与设置', icon: Settings },
  { to: '/help', label: '使用帮助', icon: CircleHelp },
]

export default function Layout() {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <div className="flex h-full flex-col md:flex-row">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-white focus:p-3">跳到页面内容</a>
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-stone-200 bg-white px-4 py-3 md:hidden">
        <span className="shrink-0 text-sm font-semibold">评论工作台</span>
        <select aria-label="工作台页面" className="min-w-0 rounded-lg border border-stone-200 px-2 py-1.5 text-sm" value={location.pathname} onChange={event => navigate(event.target.value)}>
          {NAV.map(item => <option key={item.to} value={item.to}>{item.label}</option>)}
        </select>
      </header>
      <aside className="hidden w-60 shrink-0 flex-col border-r border-stone-200 bg-white md:flex">
        <div className="px-5 py-4 text-lg font-semibold tracking-tight">
          评论工作台
          <span className="mt-1 block text-xs font-normal text-stone-400">从真实评论中发现需求</span>
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
      <main id="main-content" className="min-h-0 flex-1 min-w-0 overflow-y-auto">
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
