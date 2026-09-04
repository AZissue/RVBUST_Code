import { BarChart3, Bell, BookOpen, Bot, Building2, ChevronDown, ClipboardList, FileClock, FileText, Gauge, LogOut, Menu, Monitor, Moon, NotebookPen, PanelLeftClose, Settings, Sun, Users, Wrench, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'
import { api, formatDate } from '../lib/api'
import type { ThemeMode } from '../types'

const groups = [
  { label: '工作台', items: [{ to: '/', label: '仪表盘', icon: Gauge }, { to: '/my-work', label: '我的工作', icon: ClipboardList }, { to: '/tickets', label: '工单', icon: FileClock }] },
  { label: '客户', items: [{ to: '/customers', label: '客户管理', icon: Building2 }, { to: '/devices', label: '设备管理', icon: Wrench }] },
  { label: '数据', items: [{ to: '/worklogs', label: '工作记录', icon: NotebookPen }, { to: '/reports', label: '日报/周报/月报', icon: FileText }, { to: '/stats', label: '统计报表', icon: BarChart3 }] },
]

interface Notification { id: string; title: string; body: string; readAt?: string; createdAt: string; ticket?: { id: string } }

export function AppShell() {
  const { user, logout } = useAuth()
  const { mode, setMode } = useTheme()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const [notifications, setNotifications] = useState<Notification[]>([])
  const isAdmin = user?.role === 'admin'

  const loadNotifications = () => api<Notification[]>('/notifications').then(setNotifications).catch(() => setNotifications([]))
  useEffect(() => { void loadNotifications() }, [])
  const unread = notifications.filter((item) => !item.readAt).length
  const setTheme = (next: ThemeMode) => setMode(next)

  return <div className="app-frame">
    <aside className={`sidebar ${menuOpen ? 'sidebar-open' : ''}`}>
      <div className="brand"><div className="brand-mark">TS</div><div><strong>技术支持系统</strong><span>Support Operations V2</span></div><button className="icon-button mobile-only" onClick={() => setMenuOpen(false)}><X size={18} /></button></div>
      <nav>
        {groups.map((group) => <div className="nav-group" key={group.label}><div className="nav-label">{group.label}</div>{group.items.map((item) => <NavLink end={item.to === '/'} key={item.to} to={item.to} onClick={() => setMenuOpen(false)}><item.icon size={17} />{item.label}</NavLink>)}</div>)}
        <div className="nav-group"><div className="nav-label">知识</div><button className="nav-disabled" title="后续阶段开放"><BookOpen size={17} />知识库<span>后续</span></button><button className="nav-disabled" title="后续阶段开放"><Bot size={17} />AI 助手<span>后续</span></button></div>
        {isAdmin && <div className="nav-group"><div className="nav-label">系统</div>
          <NavLink to="/users"><Users size={17} />用户管理</NavLink><NavLink to="/teams"><Users size={17} />团队管理</NavLink><NavLink to="/settings"><Settings size={17} />系统设置</NavLink><NavLink to="/audit"><FileClock size={17} />操作日志</NavLink>
        </div>}
      </nav>
      <button className="collapse-hint"><PanelLeftClose size={16} />V2 第一阶段</button>
    </aside>
    {menuOpen && <button className="sidebar-scrim" onClick={() => setMenuOpen(false)} aria-label="关闭菜单" />}
    <div className="app-main">
      <header className="topbar">
        <button className="icon-button mobile-only" onClick={() => setMenuOpen(true)} title="导航"><Menu size={20} /></button>
        <div className="topbar-context"><span className="status-dot" />内部工作区</div>
        <div className="topbar-actions">
          <div className="theme-switch" aria-label="主题模式">
            <button className={mode === 'light' ? 'active' : ''} onClick={() => setTheme('light')} title="浅色"><Sun size={15} /></button>
            <button className={mode === 'dark' ? 'active' : ''} onClick={() => setTheme('dark')} title="深色"><Moon size={15} /></button>
            <button className={mode === 'system' ? 'active' : ''} onClick={() => setTheme('system')} title="跟随系统"><Monitor size={15} /></button>
          </div>
          <div className="popover-wrap">
            <button className="icon-button notification-button" onClick={() => setNotificationsOpen(!notificationsOpen)} title="通知"><Bell size={18} />{unread > 0 && <span>{unread}</span>}</button>
            {notificationsOpen && <div className="popover notification-popover"><div className="popover-title"><strong>站内通知</strong><button onClick={async () => { await api('/notifications/read-all', { method: 'POST' }); await loadNotifications() }}>全部已读</button></div>
              {notifications.length ? notifications.slice(0, 8).map((item) => <button key={item.id} className={`notification-row ${item.readAt ? '' : 'unread'}`} onClick={async () => { await api(`/notifications/${item.id}/read`, { method: 'PATCH' }); if (item.ticket) navigate(`/tickets/${item.ticket.id}`); setNotificationsOpen(false); await loadNotifications() }}><strong>{item.title}</strong><span>{item.body}</span><small>{formatDate(item.createdAt)}</small></button>) : <div className="empty-compact">暂无通知</div>}
            </div>}
          </div>
          <div className="user-menu"><div className="avatar">{user?.name.slice(0, 1)}</div><div><strong>{user?.name}</strong><span>{user?.role}</span></div><ChevronDown size={15} /><button className="icon-button" onClick={async () => { await logout(); navigate('/login') }} title="退出"><LogOut size={17} /></button></div>
        </div>
      </header>
      <main className="content"><Outlet /></main>
    </div>
  </div>
}
