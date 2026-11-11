import { NavLink, Outlet } from 'react-router-dom'
import { Home, Download, Bot, Lightbulb, PenLine, Settings, BookOpen, Rocket, Sparkles, ScanSearch } from 'lucide-react'
import clsx from 'clsx'
import ErrorBoundary from './ErrorBoundary'

const NAV = [
  { to: '/', label: '首页', icon: Home, end: true },
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
  return (
    <div className="flex h-full">
      <aside className="w-52 shrink-0 border-r border-stone-200 bg-white flex flex-col">
        <div className="px-5 py-4 text-lg font-semibold tracking-tight">
          评论工作台
          <span className="ml-2 text-xs font-normal text-stone-400">v2</span>
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
      <main className="flex-1 min-w-0 overflow-y-auto">
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
