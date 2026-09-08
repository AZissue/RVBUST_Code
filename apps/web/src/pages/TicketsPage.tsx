import { Archive, ArrowLeft, CheckCircle2, ClipboardList, Clock3, MessageSquare, Plus, Search, Send, X } from 'lucide-react'
import { useEffect, useMemo, useState, useRef } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { CreateTicketModal } from '../components/CreateTicketModal'
import { TicketWorklogModal } from '../components/TicketWorklogModal'
import { PriorityBadge, StatusBadge, statusLabel } from '../components/Status'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { statusChangeLabel, ticketEventTypeLabel, ticketSourceLabel } from '../lib/labels'
import type { Ticket, TicketStatus, Worklog } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

const queueScroll = new Map<string, number>()
const states: TicketStatus[] = ['PENDING', 'IN_PROGRESS', 'WAITING_CUSTOMER', 'WAITING_RND', 'RESOLVED', 'CLOSED']

export function TicketsPage({ mine = false }: { mine?: boolean }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const search = params.get('q') ?? ''
  const status = params.get('status') ?? ''
  const setFilter = (key: string, value: string) => {
    setParams(previous => { const next = new URLSearchParams(previous); value ? next.set(key, value) : next.delete(key); return next }, { replace: true })
  }
  const setSearch = (value: string) => setFilter('q', value)
  const setStatus = (value: string) => setFilter('status', value)
  const returnTo = location.pathname + location.search
  const rememberScroll = () => queueScroll.set(returnTo, window.scrollY)
  const [creating, setCreating] = useState(params.get('create') === '1')
  const remote = useRemote(() => api<Ticket[]>(mine ? '/tickets?mine=1' : '/tickets'), [mine], true)
  useEffect(() => {
    if (!remote.loading) {
      const frame = requestAnimationFrame(() => window.scrollTo(0, queueScroll.get(returnTo) ?? 0))
      return () => cancelAnimationFrame(frame)
    }
  }, [remote.loading, returnTo])
  useEffect(() => { if (params.get('create') === '1') setCreating(true) }, [params])
  const tickets = useMemo(() => (remote.data ?? []).filter((ticket) => {
    const matches = !search || `${ticket.number} ${ticket.title} ${ticket.description} ${ticket.organization.name} ${ticket.cameraModel ?? ''} ${ticket.device?.name ?? ''} ${ticket.device?.serialNumber ?? ''}`.toLowerCase().includes(search.toLowerCase())
    const states = status === 'WAITING' ? ['WAITING_CUSTOMER', 'WAITING_RND'] : status === 'DONE' ? ['RESOLVED', 'CLOSED'] : [status]
    return matches && (!status || states.includes(ticket.status))
  }), [remote.data, search, status])
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  return <div className="page-stack ticket-queue">
    <header className="page-header"><div><span className="eyebrow">{mine ? 'MY WORK' : 'TICKET QUEUE'}</span><h1>{mine ? '我的工作' : '工单管理'}</h1></div><div className="header-actions">{mine && <Link className="button" to="/work-items"><Archive size={16} />历史事项</Link>}<button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />新建工单</button></div></header>
    {mine && <section className="metric-strip compact personal-ticket-metrics">{[['', '全部工单', ClipboardList], ['IN_PROGRESS', '进行中', Clock3], ['WAITING', '等待反馈', MessageSquare], ['DONE', '已完成', CheckCircle2]].map(([value, label, Icon]) => { const Component = Icon as typeof ClipboardList; const group = value === 'WAITING' ? ['WAITING_CUSTOMER', 'WAITING_RND'] : value === 'DONE' ? ['RESOLVED', 'CLOSED'] : [value]; return <button className={`metric ${status === value ? 'selected' : ''}`} key={String(value)} onClick={() => setStatus(String(value))}><Component size={17} /><span>{String(label)}</span><strong>{(remote.data ?? []).filter((t) => !value || group.includes(t.status)).length}</strong></button> })}</section>}
    <section className="toolbar"><div className="searchbox"><Search size={16} /><input placeholder="搜索编号、问题、客户或设备" value={search} onChange={(event) => setSearch(event.target.value)} /></div><select aria-label="工单状态筛选" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option>{states.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}<option value="WAITING">等待反馈</option><option value="DONE">已完成</option></select><span className="result-count">{tickets.length} 张工单</span></section>
    {mine ? <section className="task-list personal-ticket-list">{tickets.map((ticket) => <Link className="task-row" key={ticket.id} to={`/tickets/${ticket.id}`} state={{ returnTo }} onClick={rememberScroll}><div className="task-main"><div className="task-title"><span className="mono">{ticket.number}</span><strong>{ticket.title}</strong></div><div className="task-meta"><span>{ticket.organization.name}</span><span>{ticket.cameraModel || ticket.device?.name || '未关联设备'}</span><span>{ticket.assignee?.name}</span><time>{formatDate(ticket.updatedAt)}</time></div></div><StatusBadge status={ticket.status} /><PriorityBadge priority={ticket.priority} /></Link>)}{!tickets.length && <Empty text="没有符合条件的工单" />}</section> :
    <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>编号</th><th>问题</th><th>客户 / 设备</th><th>状态</th><th>优先级</th><th>负责人</th><th>计划完成</th><th>更新</th></tr></thead><tbody>{tickets.map((ticket) => <tr key={ticket.id} onClick={() => { rememberScroll(); navigate(`/tickets/${ticket.id}`, { state: { returnTo } }) }}><td className="mono">{ticket.number}</td><td><strong>{ticket.title}</strong><small>{ticket.category}</small></td><td>{ticket.organization.name}<small>{ticket.cameraModel || ticket.device?.name || '-'}</small></td><td><StatusBadge status={ticket.status} /></td><td><PriorityBadge priority={ticket.priority} /></td><td>{ticket.assignee?.name ?? '未分配'}</td><td>{formatDate(ticket.plannedAt)}</td><td>{formatDate(ticket.updatedAt)}</td></tr>)}</tbody></table>{!tickets.length && <Empty text="没有符合条件的工单" />}</div></section>
    }
    {creating && <CreateTicketModal defaultAssigneeId={user?.id} onClose={() => { setCreating(false); params.delete('create'); setParams(params) }} onCreated={async (ticket, notice) => { setCreating(false); await remote.refresh(); navigate(`/tickets/${ticket.id}`, { state: { notice, returnTo: location.pathname + (search ? '?q=' + encodeURIComponent(search) : '') + (status ? (search ? '&' : '?') + 'status=' + encodeURIComponent(status) : '') } }) }} />}
  </div>
}

export function TicketDetailPage() {
  const { user } = useAuth()
  const users = useRemote(() => api<Array<{ id: string; name: string }>>('/users/assignable'), [])
  const [saving, setSaving] = useState(false)
  const [logging, setLogging] = useState(false)
  const [sending, setSending] = useState(false)
  const eventLock = useRef(false)
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const [notice, setNotice] = useState<string>((location.state as { notice?: string } | null)?.notice ?? '')
  const remote = useRemote(() => api<Ticket>(`/tickets/${id}`), [id], true)
  const worklogs = useRemote(() => user?.role !== 'customer' ? api<Worklog[]>(`/worklogs?ticketId=${encodeURIComponent(id)}`) : Promise.resolve([]), [user?.role, id], true)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  if (remote.loading) return <PageLoading />
  if (remote.error || !remote.data) return <PageError message={remote.error} retry={remote.refresh} />
  const ticket = remote.data
  const editable = user?.role === 'admin' || user?.id === ticket.createdBy?.id || user?.id === ticket.assignee?.id
  const assign = async (assigneeId: string) => { setSaving(true); setError(''); try { await api(`/tickets/${id}`, { method: 'PATCH', body: JSON.stringify({ assigneeId }) }); await remote.refresh() } catch (e) { setError(e instanceof Error ? e.message : '分配失败') } finally { setSaving(false) } }
  const changeStatus = async (status: TicketStatus) => { try { await api(`/tickets/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) }); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '状态更新失败') } }
  const addEvent = async () => { if (!message.trim() || eventLock.current) return; eventLock.current = true; setSending(true); try { await api(`/tickets/${id}/events`, { method: 'POST', body: JSON.stringify({ type: 'INTERNAL_NOTE', visibility: 'INTERNAL', content: message }) }); setMessage(''); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '发送失败') } finally { eventLock.current = false; setSending(false) } }
  return <div className="page-stack">
    {ticket.rawText && <details className="raw-input"><summary>原始快速输入</summary><p>{ticket.rawText}</p></details>}
    <header className="detail-header"><button className="icon-button" onClick={() => { const target = (location.state as { returnTo?: string } | null)?.returnTo; navigate(target && /^\/(tickets|my-work)(\?|$)/.test(target) ? target : '/tickets') }} title="返回"><ArrowLeft size={20} /></button><div><span className="mono eyebrow">{ticket.number}</span><h1>{ticket.title}</h1><div className="inline-meta"><StatusBadge status={ticket.status} /><PriorityBadge priority={ticket.priority} /><span>{ticket.organization.name}</span></div></div><select className="status-select" disabled={!editable} value={ticket.status} onChange={(event) => void changeStatus(event.target.value as TicketStatus)}>{states.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}</select></header>
    {notice && <div className="form-error" style={{ borderColor: 'var(--success, #2e7d32)', background: 'rgba(46,125,50,.08)', color: 'var(--success, #2e7d32)' }}><button onClick={() => setNotice('')}><X size={14} /></button>{notice}</div>}
    {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
    {user?.role !== 'customer' && <section aria-label="工单工作记录"><div className="section-heading"><h2>工作记录</h2><button className="button primary" onClick={() => setLogging(true)}><ClipboardList size={16} />登记工作记录</button></div>
      {worklogs.error ? <div className="form-error">{worklogs.error}<button onClick={() => void worklogs.refresh()}>重试</button></div> : worklogs.loading ? <p>加载中…</p> : <div className="timeline">{(worklogs.data ?? []).filter(log => log.ticket?.id === id).map(log => <article key={log.id}><div className="timeline-dot" /><header><strong>{log.author.name}</strong><time>{formatDate(log.occurredAt)}</time><span>{log.workType.label}</span></header><p>{log.summary}</p>{log.result && <p>结果：{log.result}</p>}{log.nextStep && <p>下一步：{log.nextStep}</p>}</article>)}{!worklogs.data?.some(log => log.ticket?.id === id) && <p className="muted">暂无工作记录</p>}</div>}
    </section>}
    {logging && <TicketWorklogModal ticket={ticket} onClose={() => setLogging(false)} onSaved={() => { setLogging(false); setNotice('工作记录已保存'); void worklogs.refresh() }} />}
    <div className="ticket-layout"><section className="panel"><div className="section-heading"><div><h2>处理时间线</h2><p>内部跟进记录，仅团队可见</p></div></div><div className="timeline">{ticket.events?.map((event) => <article key={event.id}><div className="timeline-dot" /><header><strong>{event.author.name}</strong><span className={`visibility ${event.visibility.toLowerCase()}`}>{event.visibility === 'INTERNAL' ? '内部' : '客户可见'}</span><time>{formatDate(event.createdAt)}</time></header><p>{event.type === 'STATUS_CHANGE' ? statusChangeLabel(event.content) : event.content}</p><small>{ticketEventTypeLabel(event.type)}</small></article>)}</div>
      {user?.role !== 'customer' && <div className="composer">{!editable && <p className="readonly-hint">当前为协作只读模式：可追加跟进记录，内容与状态的修改仅限创建人、负责人或管理员</p>}<textarea rows={3} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="记录跟进情况，仅内部可见" /><button className="button primary" disabled={sending || !message.trim()} onClick={() => void addEvent()}><Send size={16} />写入时间线</button></div>}</section>
      <aside className="detail-aside"><section><h2>工单上下文</h2><dl><dt>客户</dt><dd><Link to={`/customers/${ticket.organization.id}`}>{ticket.organization.name}</Link></dd><dt>联系人</dt><dd>{ticket.contact?.name ?? '-'}</dd><dt>创建人</dt><dd>{ticket.createdBy?.name ?? '-'}</dd><dt>创建时间</dt><dd>{formatDate(ticket.createdAt)}</dd><dt>负责人</dt><dd>{editable ? <select aria-label="工单负责人" disabled={saving || !users.data} value={ticket.assignee?.id ?? ''} onChange={(e) => void assign(e.target.value)}><option disabled value="">未分配</option>{users.data?.map((u) => <option value={u.id} key={u.id}>{u.name}</option>)}</select> : ticket.assignee?.name ?? '未分配'}</dd><dt>计划完成</dt><dd>{formatDate(ticket.plannedAt)}</dd><dt>来源</dt><dd>{ticketSourceLabel(ticket.source)}</dd><dt>分类</dt><dd>{ticket.category}</dd></dl></section><section><h2>设备环境</h2><dl><dt>相机型号</dt><dd>{ticket.cameraModel || '-'}</dd><dt>SN</dt><dd className="mono">{ticket.serialNumber || '-'}</dd><dt>SDK</dt><dd>{ticket.sdkVersion || '-'}</dd><dt>系统环境</dt><dd>{ticket.systemEnvironment || '-'}</dd></dl></section><section><h2>问题描述</h2><p>{ticket.description}</p></section></aside>
    </div>
  </div>
}
