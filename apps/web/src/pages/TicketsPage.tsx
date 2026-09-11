import { ArrowLeft, CheckCircle2, ClipboardList, Clock3, MessageSquare, Plus, RefreshCw, RotateCcw, Search, Send, Trash2, UserPlus, X } from 'lucide-react'
import { useEffect, useState, useRef } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { CreateTicketModal } from '../components/CreateTicketModal'
import { Pagination } from '../components/Pagination'
import { DeleteTimelineDialog } from '../components/DeleteTimelineDialog'
import { DeleteTicketDialog } from '../components/DeleteTicketDialog'
import { PriorityBadge, StatusBadge, StatusTransition, statusLabel } from '../components/Status'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { ticketCategoryLabel, ticketEventTypeLabel } from '../lib/labels'
import type { Ticket, TicketStatus } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

const queueScroll = new Map<string, number>()
const states: TicketStatus[] = ['PENDING', 'IN_PROGRESS', 'WAITING_CUSTOMER', 'WAITING_RND', 'RESOLVED', 'CLOSED']
interface PagedTickets { items: Ticket[]; total: number; page: number; pageSize: number; byStatus: Partial<Record<TicketStatus, number>> }

export function TicketsPage({ mine = false }: { mine?: boolean }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const search = params.get('q') ?? ''
  const status = params.get('status') ?? ''
  const page = Math.max(1, Number.parseInt(params.get('p') ?? '1', 10) || 1)
  const setFilter = (key: string, value: string) => {
    setParams(previous => { const next = new URLSearchParams(previous); value ? next.set(key, value) : next.delete(key); if (key !== 'p') next.delete('p'); return next }, { replace: true })
  }
  const setSearch = (value: string) => setFilter('q', value)
  const setStatus = (value: string) => setFilter('status', value)
  const returnTo = location.pathname + location.search
  const rememberScroll = () => queueScroll.set(returnTo, window.scrollY)
  const [creating, setCreating] = useState(params.get('create') === '1')
  // 只看我的：仅显示当前用户作为负责人的工单（服务端按 assigneeId 过滤）
  const view = params.get('view') ?? (mine ? 'assigned' : '')
  const [deleting, setDeleting] = useState<Ticket | null>(null)
  // 搜索输入防抖 300ms，避免每击键都请求
  const [debouncedSearch, setDebouncedSearch] = useState(search)
  useEffect(() => { const timer = setTimeout(() => setDebouncedSearch(search), 300); return () => clearTimeout(timer) }, [search])
  // 复合状态（等待反馈/已完成）展开为枚举列表，服务端过滤
  const serverStatus = status === 'WAITING' ? 'WAITING_CUSTOMER,WAITING_RND' : status === 'DONE' ? 'RESOLVED,CLOSED' : status
  const query = new URLSearchParams()
  if (view) query.set('view', view)
  if (debouncedSearch.trim()) query.set('search', debouncedSearch.trim())
  if (serverStatus) query.set('status', serverStatus)
  query.set('page', String(page))
  const remote = useRemote(() => api<PagedTickets>(`/tickets?${query.toString()}`), [mine, view, debouncedSearch, status, page], true)
  const tickets = remote.data?.items ?? []
  const total = remote.data?.total ?? 0
  const byStatus = remote.data?.byStatus ?? {}
  const pageSize = remote.data?.pageSize ?? 20
  const pages = Math.max(1, Math.ceil(total / pageSize))
  // 筛选后总页数收缩时自动回到最后一页
  useEffect(() => { if (remote.data && total > 0 && page > pages) setFilter('p', String(pages)) }, [remote.data]) // eslint-disable-line react-hooks/exhaustive-deps
  const metricCount = (value: string) => value === '' ? Object.values(byStatus).reduce((sum, count) => sum + (count ?? 0), 0) : value === 'WAITING' ? (byStatus.WAITING_CUSTOMER ?? 0) + (byStatus.WAITING_RND ?? 0) : value === 'DONE' ? (byStatus.RESOLVED ?? 0) + (byStatus.CLOSED ?? 0) : (byStatus[value as TicketStatus] ?? 0)
  const assignable = useRemote(() => api<Array<{ id: string; name: string }>>('/users/assignable'), [])
  const canTransferRow = (ticket: Ticket) => user?.role === 'admin' || user?.id === ticket.assignee?.id
  const canDeleteRow = (ticket: Ticket) => user?.role === 'admin' || user?.id === ticket.createdBy?.id || user?.id === ticket.assignee?.id
  const confirmBackward = (ticket: Ticket, next: TicketStatus) => states.indexOf(next) >= states.indexOf(ticket.status) || window.confirm(`确认将工单状态从「${statusLabel(ticket.status)}」变更回「${statusLabel(next)}」？`)
  const changeStatus = async (ticket: Ticket, next: TicketStatus) => { if (!confirmBackward(ticket, next)) return; try { await api(`/tickets/${ticket.id}/status`, { method: 'POST', body: JSON.stringify({ status: next }) }); await remote.refresh() } catch (reason) { window.alert(reason instanceof Error ? reason.message : '状态更新失败') } }
  const changeAssignee = async (ticket: Ticket, assigneeId: string) => { try { await api(`/tickets/${ticket.id}`, { method: 'PATCH', body: JSON.stringify({ assigneeId }) }); await remote.refresh() } catch (reason) { window.alert(reason instanceof Error ? reason.message : '负责人变更失败') } }
  useEffect(() => {
    if (!remote.loading) {
      const frame = requestAnimationFrame(() => window.scrollTo(0, queueScroll.get(returnTo) ?? 0))
      return () => cancelAnimationFrame(frame)
    }
  }, [remote.loading, returnTo])
  useEffect(() => { if (params.get('create') === '1') setCreating(true) }, [params])
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  return <div className="page-stack ticket-queue">
    <header className="page-header"><div><span className="eyebrow">{mine ? 'MY WORK' : 'TICKET QUEUE'}</span><h1>{mine ? '我的工作' : '工单管理'}</h1></div><div className="header-actions">{(user?.role === 'admin' || user?.role === 'support') && <button className="button" onClick={() => navigate('/tickets/recycle-bin')}><Trash2 size={16} />回收站</button>}<button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />新建工单</button></div></header>
    {mine && <section className="metric-strip compact personal-ticket-metrics">{[['', '全部工单', ClipboardList], ['IN_PROGRESS', '进行中', Clock3], ['WAITING', '等待反馈', MessageSquare], ['DONE', '已完成', CheckCircle2]].map(([value, label, Icon]) => { const Component = Icon as typeof ClipboardList; return <button className={`metric ${status === value ? 'selected' : ''}`} key={String(value)} onClick={() => setStatus(String(value))}><Component size={17} /><span>{String(label)}</span><strong>{metricCount(String(value))}</strong></button> })}</section>}
    <section className="toolbar"><div className="searchbox"><Search size={16} /><input placeholder="搜索编号、问题、客户或设备" value={search} onChange={(event) => setSearch(event.target.value)} /></div><select aria-label="工单状态筛选" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option>{states.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}<option value="WAITING">等待反馈</option><option value="DONE">已完成</option></select><select aria-label="工单范围" value={view || 'all'} onChange={event => setFilter('view', event.target.value)}><option value="all">全部工单</option><option value="assigned">我负责的</option><option value="collaborating">我协助的</option><option value="created">我创建的</option><option value="today-todo">今日待办</option><option value="today-done">今日已完成</option></select><button type="button" className="icon-button" title="刷新工单列表" aria-label="刷新工单列表" disabled={remote.loading} onClick={() => void remote.refresh()}><RefreshCw size={16} /></button><span className="result-count">{search !== debouncedSearch ? '搜索中…' : `${total} 张工单`}</span></section>
    {mine ? <section className="task-list personal-ticket-list">{tickets.map((ticket) => <Link className="task-row" key={ticket.id} to={`/tickets/${ticket.id}`} state={{ returnTo }} onClick={rememberScroll}><div className="task-main"><div className="task-title"><span className="mono">{ticket.number}</span><strong>{ticket.title}</strong></div><div className="task-meta"><span>{ticket.organization.name}</span><span>{ticket.cameraModel || ticket.device?.name || '未关联设备'}</span><span>{ticket.assignee?.name}</span><time>{formatDate(ticket.updatedAt)}</time></div></div><StatusBadge status={ticket.status} /><PriorityBadge priority={ticket.priority} /></Link>)}{!tickets.length && <Empty text="没有符合条件的工单" />}</section> :
    <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th className="col-fit">编号</th><th>客户 / 设备</th><th>问题</th><th>状态</th><th>优先级</th><th>负责人</th><th>更新</th><th className="col-fit">操作</th></tr></thead><tbody>{tickets.map((ticket) => <tr key={ticket.id} onClick={() => { rememberScroll(); navigate(`/tickets/${ticket.id}`, { state: { returnTo } }) }}><td className="mono col-fit">{ticket.number}</td><td>{ticket.organization.name}<small>{ticket.cameraModel || ticket.device?.name || '-'}</small></td><td><strong>{ticket.title}</strong><small>{ticketCategoryLabel(ticket.category)}</small></td><td onClick={(event) => event.stopPropagation()}>{canTransferRow(ticket) ? <select aria-label="工单状态" className={`cell-select status-${ticket.status.toLowerCase()}`} value={ticket.status} onChange={(event) => void changeStatus(ticket, event.target.value as TicketStatus)}>{states.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}</select> : <StatusBadge status={ticket.status} />}</td><td><PriorityBadge priority={ticket.priority} /></td><td onClick={(event) => event.stopPropagation()}>{canTransferRow(ticket) ? <select aria-label="工单负责人" className="cell-select" disabled={!assignable.data} value={ticket.assignee?.id ?? ''} onChange={(event) => void changeAssignee(ticket, event.target.value)}><option value="">未分配</option>{assignable.data?.map((u) => <option value={u.id} key={u.id}>{u.name}</option>)}</select> : ticket.assignee?.name ?? '未分配'}</td><td>{formatDate(ticket.updatedAt)}</td><td onClick={(event) => event.stopPropagation()}>{canDeleteRow(ticket) && <button className="icon-button danger" title="移入回收站" onClick={() => setDeleting(ticket)}><Trash2 size={16} /></button>}</td></tr>)}</tbody></table>{!tickets.length && <Empty text="没有符合条件的工单" />}</div></section>
    }
    <Pagination page={page} pageSize={pageSize} total={total} onPage={(next) => setFilter('p', String(next))} />
    {deleting && <DeleteTicketDialog ticket={deleting} onClose={() => setDeleting(null)} onDeleted={async () => { setDeleting(null); await remote.refresh() }} />}
    {creating && <CreateTicketModal defaultAssigneeId={user?.id} onClose={() => { setCreating(false); params.delete('create'); setParams(params) }} onCreated={async (ticket, notice) => { setCreating(false); await remote.refresh(); navigate(`/tickets/${ticket.id}`, { state: { notice, returnTo: location.pathname + (search ? '?q=' + encodeURIComponent(search) : '') + (status ? (search ? '&' : '?') + 'status=' + encodeURIComponent(status) : '') } }) }} />}
  </div>
}

export function TicketDetailPage() {
  const { user } = useAuth()
  const [sending, setSending] = useState(false)
  const eventLock = useRef(false)
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const [notice, setNotice] = useState<string>((location.state as { notice?: string } | null)?.notice ?? '')
  const remote = useRemote(() => api<Ticket>(`/tickets/${id}`), [id], true)
  const assignable = useRemote(() => api<Array<{ id: string; name: string }>>('/users/assignable'), [])
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deletingEvent, setDeletingEvent] = useState<{ id: string; content: string } | null>(null)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteUserIds, setInviteUserIds] = useState<string[]>([])
  const [inviteMessage, setInviteMessage] = useState('')
  const toggleInvite = (userId: string) => setInviteUserIds(previous => previous.includes(userId) ? previous.filter(item => item !== userId) : [...previous, userId])
  if (remote.loading) return <PageLoading />
  if (remote.error || !remote.data) return <PageError message={remote.error} retry={remote.refresh} />
  const ticket = remote.data
  const editable = user?.role === 'admin' || user?.id === ticket.createdBy?.id || user?.id === ticket.assignee?.id
  const canOperate = user?.role === 'admin' || user?.id === ticket.assignee?.id
  const changeStatus = async (status: TicketStatus) => { if (states.indexOf(status) < states.indexOf(ticket.status) && !window.confirm(`确认将工单状态从「${statusLabel(ticket.status)}」变更回「${statusLabel(status)}」？`)) return; try { await api(`/tickets/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) }); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '状态更新失败') } }
  const addEvent = async () => { if (!message.trim() || eventLock.current) return; eventLock.current = true; setSending(true); try { await api(`/tickets/${id}/events`, { method: 'POST', body: JSON.stringify({ type: 'INTERNAL_NOTE', visibility: 'INTERNAL', content: message }) }); setMessage(''); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '发送失败') } finally { eventLock.current = false; setSending(false) } }
  const isDeleted = Boolean(ticket.deletedAt)
  const restoreTicket = async () => { try { await api(`/tickets/${id}/restore`, { method: 'POST' }); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '恢复失败') } }
  const inviteAssist = async () => { if (!inviteUserIds.length) { setError('请选择协作人'); return } try { await api(`/tickets/${id}/assist-requests`, { method: 'POST', body: JSON.stringify({ targetUserIds: inviteUserIds, message: inviteMessage.trim() || undefined }) }); setInviteOpen(false); setInviteUserIds([]); setInviteMessage(''); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '添加失败') } }
  const removeCollaborator = async (userId: string) => { if (!window.confirm('确认移除该协作人？')) return; try { await api(`/tickets/${id}/collaborators/${userId}`, { method: 'DELETE' }); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '移除失败') } }
  return <div className="page-stack">
    <header className="detail-header"><button className="icon-button" onClick={() => { const target = (location.state as { returnTo?: string } | null)?.returnTo; navigate(target && /^\/(tickets|my-work)(\?|$)/.test(target) ? target : '/tickets') }} title="返回"><ArrowLeft size={20} /></button><div><span className="mono eyebrow">{ticket.number}</span><h1>{ticket.title}</h1><div className="inline-meta"><StatusBadge status={ticket.status} /><PriorityBadge priority={ticket.priority} /><span>{ticket.organization.name}</span></div></div>{canOperate && !isDeleted ? <select aria-label="修改工单状态" className={`status-select status-${ticket.status.toLowerCase()}`} value={ticket.status} onChange={(event) => void changeStatus(event.target.value as TicketStatus)}>{states.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}</select> : <StatusBadge status={ticket.status} />}</header>
    {deletingEvent && <DeleteTimelineDialog ticketId={id} event={deletingEvent} onClose={() => setDeletingEvent(null)} onDeleted={async () => { setDeletingEvent(null); await remote.refresh() }} />}
    {deleteOpen && <DeleteTicketDialog ticket={ticket} onClose={() => setDeleteOpen(false)} onDeleted={() => { setDeleteOpen(false); navigate('/tickets') }} />}
    {notice && <div className="form-error" style={{ borderColor: 'var(--success, #2e7d32)', background: 'rgba(46,125,50,.08)', color: 'var(--success, #2e7d32)' }}><button onClick={() => setNotice('')}><X size={14} /></button>{notice}</div>}
    {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
    {isDeleted && <div className="form-error" style={{ borderColor: 'var(--warning, #ed6c02)', background: 'rgba(237,108,2,.08)', color: 'var(--warning, #ed6c02)' }}>该工单已在回收站中{isDeleted && ticket.deletedBy ? `，由 ${ticket.deletedBy.name} 删除${ticket.deletedReason ? `，原因：${ticket.deletedReason}` : ''}` : ''}</div>}
    <div className="ticket-layout"><section className="panel"><div className="section-heading"><div><h2>处理时间线</h2><p>内部跟进记录，仅团队可见</p></div></div><div className="timeline">{ticket.events?.map((event) => <article key={event.id}><div className="timeline-dot" /><header><strong>{event.author.name}</strong><span className={`visibility ${event.visibility.toLowerCase()}`}>{event.visibility === 'INTERNAL' ? '内部' : '客户可见'}</span><time>{formatDate(event.createdAt)}</time>{(user?.role === 'admin' || event.author.id === user?.id) && <button type="button" className="icon-button danger" title="删除流程记录" aria-label="删除流程记录" onClick={() => setDeletingEvent({ id: event.id, content: event.content })}><Trash2 size={15} /></button>}</header><p>{event.type === 'STATUS_CHANGE' ? <StatusTransition content={event.content} /> : event.content}</p><small>{ticketEventTypeLabel(event.type)}</small></article>)}</div>
      {user?.role !== 'customer' && !isDeleted && <div className="composer">{!editable && <p className="readonly-hint">当前为协作只读模式：可追加跟进记录，工单状态变更仅限当前负责人或管理员</p>}<textarea rows={3} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="记录跟进情况，仅内部可见" /><button className="button primary" disabled={sending || !message.trim()} onClick={() => void addEvent()}><Send size={16} />写入时间线</button></div>}</section>
      <aside className="detail-aside"><section><h2>工单上下文</h2><dl><dt>客户</dt><dd><Link to={`/customers/${ticket.organization.id}`}>{ticket.organization.name}</Link></dd><dt>联系人</dt><dd>{ticket.contact?.name ?? '-'}</dd><dt>创建人</dt><dd>{ticket.createdBy?.name ?? '-'}</dd><dt>创建时间</dt><dd>{formatDate(ticket.createdAt)}</dd><dt>负责人</dt><dd>{ticket.assignee?.name ?? '未分配'}</dd><dt>计划完成</dt><dd>{formatDate(ticket.plannedAt)}</dd><dt>分类</dt><dd>{ticketCategoryLabel(ticket.category)}</dd></dl></section>{user?.role !== 'customer' && <section><h2>协作</h2><div className="assist-list">{(ticket.collaborators ?? []).map((collaborator) => <div className="assist-item" key={collaborator.user.id}><header><strong>{collaborator.user.name}</strong></header>{editable && !isDeleted && <div className="row-actions"><button className="button small" onClick={() => void removeCollaborator(collaborator.user.id)}>移除</button></div>}</div>)}</div>{!ticket.collaborators?.length && <p className="muted">暂无协作人</p>}{editable && !isDeleted && <div className="row-actions"><button className="button" onClick={() => setInviteOpen((previous) => !previous)}><UserPlus size={15} />添加协作人</button></div>}{inviteOpen && editable && !isDeleted && <div className="invite-box">{assignable.data?.map((item) => <label key={item.id} className="checkbox-row"><input type="checkbox" checked={inviteUserIds.includes(item.id)} onChange={() => toggleInvite(item.id)} />{item.name}</label>) ?? <span>加载中…</span>}<input value={inviteMessage} onChange={(event) => setInviteMessage(event.target.value)} placeholder="协作说明（可选）" maxLength={2000} /><div className="row-actions"><button className="button primary small" onClick={() => void inviteAssist()}>添加</button><button className="button small" onClick={() => setInviteOpen(false)}>取消</button></div></div>}</section>}<section className="recycle-actions">{!isDeleted && editable && <button className="button danger" onClick={() => setDeleteOpen(true)}><Trash2 size={15} />移入回收站</button>}{isDeleted && <button className="button" onClick={() => void restoreTicket()}><RotateCcw size={16} />恢复工单</button>}</section><section><h2>设备环境</h2><dl><dt>相机型号</dt><dd>{ticket.cameraModel || '-'}</dd><dt>SN</dt><dd className="mono">{ticket.serialNumber || '-'}</dd><dt>SDK</dt><dd>{ticket.sdkVersion || '-'}</dd><dt>系统环境</dt><dd>{ticket.systemEnvironment || '-'}</dd></dl></section><section><h2>问题描述</h2><p>{ticket.description}</p></section></aside>
    </div>
  </div>
}
