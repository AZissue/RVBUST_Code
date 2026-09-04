import { AlertTriangle, ArrowRight, Check, CheckCircle2, CircleDot, Clock3, MessageSquare, Plus, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { PriorityBadge, StatusBadge } from '../components/Status'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import type { Ticket, WorkItem, Worklog } from '../types'

interface Summary {
  workItemCounts: { todayTodo: number; inProgress: number; waitingFeedback: number; todayCompleted: number }
  ticketCounts: { pending: number; inProgress: number; highPriority: number; waitingCustomer: number; waitingRnd: number }
  myTickets: Ticket[]
  myWorkItems: WorkItem[]
  todayWorklogs: Worklog[]
  recentReplies: Array<{ id: string; content: string; ticket: { id: string; number: string; title: string } }>
}

const statusLabels = { TODO: '待开始', IN_PROGRESS: '进行中', WAITING_FEEDBACK: '等待反馈', COMPLETED: '已完成', CANCELED: '已取消' }

export function DashboardPage() {
  const navigate = useNavigate(); const [rawText, setRawText] = useState(''); const remote = useRemote(() => api<Summary>('/dashboard'), []); const data = remote.data
  if (remote.loading) return <PageLoading />
  if (remote.error || !data) return <PageError message={remote.error} retry={remote.refresh} />
  const metrics = [['今日待办', data.workItemCounts.todayTodo, CircleDot], ['进行中事项', data.workItemCounts.inProgress, RefreshCw], ['处理中工单', data.ticketCounts.inProgress, Clock3], ['等待反馈', data.workItemCounts.waitingFeedback, MessageSquare], ['今日已完成', data.workItemCounts.todayCompleted, CheckCircle2]] as const
  const openQuickCapture = () => { if (rawText.trim()) sessionStorage.setItem('quick-capture', rawText.trim()); navigate('/worklogs?create=1') }
  const complete = async (item: WorkItem) => { await api(`/work-items/${item.id}`, { method: 'PATCH', body: JSON.stringify({ status: 'COMPLETED' }) }); await remote.refresh() }
  return <div className="page-stack dashboard-page">
    <header className="page-header"><div><span className="eyebrow">TODAY</span><h1>今日工作台</h1><p>聚焦今天需要推进的工作和客户问题。</p></div><div className="header-actions"><button className="button" onClick={() => void remote.refresh()}><RefreshCw size={16} />刷新</button><button className="button primary" onClick={() => navigate('/work-items')}><Plus size={16} />新建事项</button><button className="button" onClick={() => navigate('/tickets?create=1')}><Plus size={16} />新建工单</button></div></header>
    <section className="today-overview">{metrics.map(([label, value, Icon]) => <div key={label}><Icon size={16} /><span>{label}</span><strong>{value}</strong></div>)}</section>
    <div className="workbench-layout"><main className="workbench-main">
      <section className="workspace-section"><div className="section-heading"><div><h2>正在推进</h2><p>我的进行中工作事项</p></div><Link to="/my-work">查看全部<ArrowRight size={15} /></Link></div><div className="dashboard-tasks">{data.myWorkItems.map((item) => <article key={item.id} onClick={() => navigate('/my-work')}><button className="task-complete" title="完成" onClick={(event) => { event.stopPropagation(); void complete(item) }}><Check size={13} /></button><div><div className="task-title"><strong>{item.title}</strong><span className={`status-dot-inline status-${item.status.toLowerCase()}`} />{statusLabels[item.status]}</div><p>{item.workType.label} · {item.dueDate ? `截止 ${formatDate(item.dueDate).slice(0, 5)}` : '未设截止'}</p><div className="mini-progress"><i style={{ width: `${item.progress}%` }} /></div></div><strong className="progress-number">{item.progress}%</strong></article>)}{!data.myWorkItems.length && <Empty text="当前没有进行中的事项" />}</div></section>
      <section className="workspace-section"><div className="section-heading"><div><h2>需要关注的工单</h2><p>高优先级、即将到期、等待反馈或分配给我的问题</p></div><Link to="/tickets">查看工单<ArrowRight size={15} /></Link></div><div className="attention-list">{data.myTickets.map((ticket) => <button key={ticket.id} onClick={() => navigate(`/tickets/${ticket.id}`)}><span className="mono">{ticket.number}</span><div><strong>{ticket.title}</strong><small>{ticket.organization.name} · {ticket.assignee?.name || '未分配'}</small></div><StatusBadge status={ticket.status} /><PriorityBadge priority={ticket.priority} /></button>)}{!data.myTickets.length && <Empty text="当前没有需要关注的工单" />}</div><div className="ticket-alerts"><span><AlertTriangle size={14} />异常提醒</span><small>高优先级 {data.ticketCounts.highPriority}</small><small>等待客户 {data.ticketCounts.waitingCustomer}</small><small>等待研发 {data.ticketCounts.waitingRnd}</small>{data.recentReplies.length > 0 && <small>最近客户回复 {data.recentReplies.length}</small>}</div></section>
    </main><aside className="workbench-aside">
      <section className="workspace-section quick-capture-panel"><div className="section-heading"><div><h2>快速记录</h2><p>记录事实，AI 将帮助拆分和归类</p></div></div><textarea value={rawText} onChange={(event) => setRawText(event.target.value)} rows={7} placeholder="上午完成SDK安装教程第二版，下午帮浙江智享排查M2600无点云，调整巨帧后恢复。" /><small>当前使用规则拆分，保存前由你确认；尚未接入 AI 语义识别。</small><button className="button primary" disabled={!rawText.trim()} onClick={openQuickCapture}><Plus size={15} />生成工作记录草稿</button></section>
      <section className="workspace-section"><div className="section-heading"><div><h2>今日工作记录</h2><p>仅显示已确认事实</p></div><Link to="/worklogs">全部记录<ArrowRight size={15} /></Link></div><div className="today-timeline">{data.todayWorklogs.map((log) => <button key={log.id} onClick={() => navigate('/worklogs')}><time>{new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(log.occurredAt))}</time><i /><div><span>{log.workType.label}</span><strong>{log.summary}</strong>{(log.result || log.organization?.name) && <p>{[log.organization?.name, log.result].filter(Boolean).join(' · ')}</p>}</div></button>)}{!data.todayWorklogs.length && <Empty text="今天还没有确认记录" />}</div></section>
    </aside></div>
  </div>
}

export function PageLoading() { return <div className="state-page"><span className="spinner" />正在加载</div> }
export function PageError({ message, retry }: { message: string; retry: () => void }) { return <div className="state-page"><AlertTriangle size={24} /><strong>数据加载失败</strong><span>{message}</span><button className="button" onClick={retry}>重试</button></div> }
export function Empty({ text }: { text: string }) { return <div className="empty-compact">{text}</div> }
