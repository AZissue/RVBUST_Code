import { AlertTriangle, ArrowRight, CheckCircle2, CircleDot, Clock3, MessageSquare, Plus, RefreshCw } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { PriorityBadge, StatusBadge } from '../components/Status'
import { QuickTicketInput } from '../components/QuickTicketInput'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'
import type { Ticket, Worklog } from '../types'

interface Summary {
  ticketCounts: { todayTodo: number; pending: number; inProgress: number; highPriority: number; waitingCustomer: number; waitingRnd: number; todayCompleted: number }
  myTickets: Ticket[]; activeTickets: Ticket[]; todayWorklogs: Worklog[]
}
export function DashboardPage() {
  const navigate = useNavigate()
  const remote = useRemote(() => api<Summary>('/dashboard'), [], true)
  const data = remote.data
  if (remote.loading) return <PageLoading />
  if (!data) return <PageError message={remote.error} retry={remote.refresh} />
  const c = data.ticketCounts
  const metrics = [['今日待办', c.todayTodo, CircleDot], ['待处理工单', c.pending, Clock3], ['处理中工单', c.inProgress, RefreshCw], ['等待反馈', c.waitingCustomer + c.waitingRnd, MessageSquare], ['今日已完成', c.todayCompleted, CheckCircle2]] as const
  return <div className="page-stack dashboard-page">
    <header className="page-header"><div><span className="eyebrow">TODAY</span><h1>今日工作台</h1></div><div className="header-actions"><button className="button" onClick={() => void remote.refresh()}><RefreshCw size={16} />刷新</button><button className="button primary" onClick={() => navigate('/tickets?create=1')}><Plus size={16} />新建工单</button></div></header>
    {remote.error && <div role="alert" className="form-error">{remote.error}</div>}
    <section className="today-overview">{metrics.map(([label, value, Icon]) => <div key={label}><Icon size={16} /><span>{label}</span><strong>{value}</strong></div>)}</section>
    <div className="workbench-layout"><main className="workbench-main">
      <section className="workspace-section"><div className="section-heading"><h2>正在推进</h2><Link to="/my-work">我的工作<ArrowRight size={15} /></Link></div><TicketRows tickets={data.activeTickets} />{!data.activeTickets.length && <Empty text="当前没有正在处理的工单" />}</section>
      <section className="workspace-section"><div className="section-heading"><h2>需要关注的工单</h2><Link to="/tickets">查看工单<ArrowRight size={15} /></Link></div><TicketRows tickets={data.myTickets} />{!data.myTickets.length && <Empty text="当前没有需要关注的工单" />}<div className="ticket-alerts"><span><AlertTriangle size={14} />异常提醒</span><small>高优先级 {c.highPriority}</small><small>等待客户 {c.waitingCustomer}</small><small>等待研发 {c.waitingRnd}</small></div></section>
    </main><aside className="workbench-aside"><QuickTicketInput />
      <section className="workspace-section"><div className="section-heading"><h2>今日工作记录</h2><Link to="/worklogs">全部记录<ArrowRight size={15} /></Link></div><div className="today-timeline">{data.todayWorklogs.map((log) => <button key={log.id} onClick={() => navigate('/worklogs')}><time>{new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(log.occurredAt))}</time><i /><div><span>{log.workType.label}</span><strong>{log.summary}</strong>{(log.result || log.organization?.name) && <p>{[log.organization?.name, log.result].filter(Boolean).join(' · ')}</p>}</div></button>)}{!data.todayWorklogs.length && <Empty text="今天还没有确认记录" />}</div></section>
    </aside></div>
  </div>
}
function TicketRows({ tickets }: { tickets: Ticket[] }) {
  const navigate = useNavigate()
  return <div className="attention-list">{tickets.map((t) => <button key={t.id} onClick={() => navigate(`/tickets/${t.id}`)}><span className="mono">{t.number}</span><div><strong>{t.title}</strong><small>{t.organization.name} · {t.assignee?.name ?? '未分配'}</small></div><StatusBadge status={t.status} /><PriorityBadge priority={t.priority} /></button>)}</div>
}
export function PageLoading() { return <div className="state-page"><span className="spinner" />正在加载</div> }
export function PageError({ message, retry }: { message: string; retry: () => void }) { return <div className="state-page"><AlertTriangle size={24} /><strong>数据加载失败</strong><span>{message}</span><button className="button" onClick={retry}>重试</button></div> }
export function Empty({ text }: { text: string }) { return <div className="empty-compact">{text}</div> }
