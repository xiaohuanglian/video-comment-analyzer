import { NavLink, Outlet } from 'react-router-dom'
import { Home, Download, Bot, Lightbulb, PenLine, Settings, BookOpen } from 'lucide-react'
import clsx from 'clsx'

const NAV = [
  { to: '/', label: '首页', icon: Home, end: true },
  { to: '/collect', label: '采集', icon: Download },
  { to: '/wechat', label: '公众号', icon: BookOpen },
  { to: '/automation', label: '回复自动化', icon: Bot },
  { to: '/topics', label: '选题中心', icon: Lightbulb },
  { to: '/writer', label: '文案生成', icon: PenLine },
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
        <Outlet />
      </main>
    </div>
  )
}
