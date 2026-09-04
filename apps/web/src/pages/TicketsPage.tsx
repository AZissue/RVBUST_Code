import { Archive, ArrowLeft, CheckCircle2, ClipboardList, Clock3, MessageSquare, Plus, Search, Send, X } from 'lucide-react'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Modal } from '../components/Modal'
import { PriorityBadge, StatusBadge, statusLabel } from '../components/Status'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import type { Customer, Ticket, TicketStatus } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

const sources = [['CUSTOMER_INQUIRY', '客户咨询'], ['PRE_SALES_SELECTION', '售前选型'], ['AFTER_SALES_INCIDENT', '售后异常'], ['ON_SITE_DEBUGGING', '现场调试'], ['INTERNAL_TESTING', '内部测试'], ['TRAINING', '培训'], ['SDK_SOFTWARE', 'SDK/软件'], ['OTHER', '其他']]
const states: TicketStatus[] = ['PENDING', 'IN_PROGRESS', 'WAITING_CUSTOMER', 'WAITING_RND', 'RESOLVED', 'CLOSED']

export function TicketsPage({ mine = false }: { mine?: boolean }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [creating, setCreating] = useState(params.get('create') === '1')
  const remote = useRemote(() => api<Ticket[]>(mine ? '/tickets?mine=1' : '/tickets'), [mine], true)
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
    {mine ? <section className="task-list personal-ticket-list">{tickets.map((ticket) => <Link className="task-row" key={ticket.id} to={`/tickets/${ticket.id}`}><div className="task-main"><div className="task-title"><span className="mono">{ticket.number}</span><strong>{ticket.title}</strong></div><div className="task-meta"><span>{ticket.organization.name}</span><span>{ticket.cameraModel || ticket.device?.name || '未关联设备'}</span><span>{ticket.assignee?.name}</span><time>{formatDate(ticket.updatedAt)}</time></div></div><StatusBadge status={ticket.status} /><PriorityBadge priority={ticket.priority} /></Link>)}{!tickets.length && <Empty text="没有符合条件的工单" />}</section> :
    <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>编号</th><th>问题</th><th>客户 / 设备</th><th>状态</th><th>优先级</th><th>负责人</th><th>计划完成</th><th>更新</th></tr></thead><tbody>{tickets.map((ticket) => <tr key={ticket.id} onClick={() => navigate(`/tickets/${ticket.id}`)}><td className="mono">{ticket.number}</td><td><strong>{ticket.title}</strong><small>{ticket.category}</small></td><td>{ticket.organization.name}<small>{ticket.cameraModel || ticket.device?.name || '-'}</small></td><td><StatusBadge status={ticket.status} /></td><td><PriorityBadge priority={ticket.priority} /></td><td>{ticket.assignee?.name ?? '未分配'}</td><td>{formatDate(ticket.plannedAt)}</td><td>{formatDate(ticket.updatedAt)}</td></tr>)}</tbody></table>{!tickets.length && <Empty text="没有符合条件的工单" />}</div></section>
    }
    {creating && <CreateTicketModal defaultAssigneeId={user?.id} onClose={() => { setCreating(false); params.delete('create'); setParams(params) }} onCreated={async (ticket) => { setCreating(false); await remote.refresh(); navigate(`/tickets/${ticket.id}`) }} />}
  </div>
}

function CreateTicketModal({ onClose, onCreated, defaultAssigneeId }: { onClose: () => void; onCreated: (ticket: Ticket) => void; defaultAssigneeId?: string }) {
  const [assignee, setAssignee] = useState(defaultAssigneeId ?? '')
  const users = useRemote(() => api<Array<{ id: string; name: string }>>('/users/assignable'), [])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { void api<Customer[]>('/customers').then(setCustomers).catch((e: Error) => setError(e.message)) }, [])
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '')
    const assigneeId = value('assigneeId') || undefined
    try {
      const ticket = await api<Ticket>('/tickets', { method: 'POST', body: JSON.stringify({ assigneeId, source: value('source'), organizationId: value('organizationId'), category: value('category'), title: value('title'), description: value('description'), priority: value('priority'), cameraModel: value('cameraModel') || undefined, serialNumber: value('serialNumber') || undefined, sdkVersion: value('sdkVersion') || undefined, systemEnvironment: value('systemEnvironment') || undefined, plannedAt: value('plannedAt') ? new Date(value('plannedAt')).toISOString() : undefined }) })
      onCreated(ticket)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '创建失败') } finally { setBusy(false) }
  }
  return <Modal title="创建技术支持工单" onClose={onClose} wide><form className="form-grid" onSubmit={submit}>
    <label className="span-2">负责人<select name="assigneeId" value={assignee} onChange={(e) => setAssignee(e.target.value)}><option value="">未分配</option>{users.data?.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label>
    <label>问题来源<select name="source" defaultValue="AFTER_SALES_INCIDENT">{sources.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <label>客户公司<select name="organizationId" required defaultValue=""><option value="" disabled>选择客户</option>{customers.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select></label>
    <label>问题分类<input name="category" required placeholder="如：网络连接" /></label><label>优先级<select name="priority" defaultValue="MEDIUM"><option value="LOW">低</option><option value="MEDIUM">中</option><option value="HIGH">高</option><option value="URGENT">紧急</option></select></label>
    <label className="span-2">问题标题<input name="title" required minLength={3} /></label><label className="span-2">问题描述<textarea name="description" required rows={4} /></label>
    <label>相机型号<input name="cameraModel" /></label><label>序列号<input name="serialNumber" /></label><label>SDK 版本<input name="sdkVersion" /></label><label>计划完成时间<input name="plannedAt" type="datetime-local" /></label>
    <label className="span-2">系统环境<textarea name="systemEnvironment" rows={2} placeholder="OS、网络、SDK、运行环境" /></label>
    {error && <div className="form-error span-2">{error}</div>}<div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在创建' : '确认创建'}</button></div>
  </form></Modal>
}

export function TicketDetailPage() {
  const users = useRemote(() => api<Array<{ id: string; name: string }>>('/users/assignable'), [])
  const [saving, setSaving] = useState(false)
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const remote = useRemote(() => api<Ticket>(`/tickets/${id}`), [id], true)
  const [message, setMessage] = useState('')
  const [visibility, setVisibility] = useState<'INTERNAL' | 'CUSTOMER'>('INTERNAL')
  const [error, setError] = useState('')
  if (remote.loading) return <PageLoading />
  if (remote.error || !remote.data) return <PageError message={remote.error} retry={remote.refresh} />
  const ticket = remote.data
  const assign = async (assigneeId: string) => { setSaving(true); setError(''); try { await api(`/tickets/${id}`, { method: 'PATCH', body: JSON.stringify({ assigneeId }) }); await remote.refresh() } catch (e) { setError(e instanceof Error ? e.message : '分配失败') } finally { setSaving(false) } }
  const changeStatus = async (status: TicketStatus) => { try { await api(`/tickets/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) }); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '状态更新失败') } }
  const addEvent = async () => { if (!message.trim()) return; try { await api(`/tickets/${id}/events`, { method: 'POST', body: JSON.stringify({ type: visibility === 'CUSTOMER' ? 'CUSTOMER_REPLY' : 'INTERNAL_NOTE', visibility, content: message }) }); setMessage(''); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '发送失败') } }
  return <div className="page-stack">
    <section className="toolbar"><label>负责人<select aria-label="工单负责人" disabled={saving || !users.data} value={ticket.assignee?.id ?? ''} onChange={(e) => void assign(e.target.value)}><option disabled value="">未分配</option>{users.data?.map((u) => <option value={u.id} key={u.id}>{u.name}</option>)}</select></label>{ticket.rawText && <details><summary>原始快速输入</summary><p>{ticket.rawText}</p></details>}</section>
    <header className="detail-header"><button className="icon-button" onClick={() => navigate('/tickets')} title="返回"><ArrowLeft size={20} /></button><div><span className="mono eyebrow">{ticket.number}</span><h1>{ticket.title}</h1><div className="inline-meta"><StatusBadge status={ticket.status} /><PriorityBadge priority={ticket.priority} /><span>{ticket.organization.name}</span></div></div><select className="status-select" value={ticket.status} onChange={(event) => void changeStatus(event.target.value as TicketStatus)}>{states.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}</select></header>
    {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
    <div className="ticket-layout"><section className="panel"><div className="section-heading"><div><h2>处理时间线</h2><p>内部记录与客户回复严格区分</p></div></div><div className="timeline">{ticket.events?.map((event) => <article key={event.id}><div className="timeline-dot" /><header><strong>{event.author.name}</strong><span className={`visibility ${event.visibility.toLowerCase()}`}>{event.visibility === 'INTERNAL' ? '内部' : '客户可见'}</span><time>{formatDate(event.createdAt)}</time></header><p>{event.content}</p><small>{event.type}</small></article>)}</div>
      <div className="composer"><div className="segmented"><button className={visibility === 'INTERNAL' ? 'active' : ''} onClick={() => setVisibility('INTERNAL')}>内部备注</button><button className={visibility === 'CUSTOMER' ? 'active' : ''} onClick={() => setVisibility('CUSTOMER')}>客户回复</button></div><textarea rows={3} value={message} onChange={(event) => setMessage(event.target.value)} placeholder={visibility === 'INTERNAL' ? '记录排查过程，仅内部可见' : '填写可发送给客户的正式回复'} /><button className="button primary" onClick={() => void addEvent()}><Send size={16} />写入时间线</button></div></section>
      <aside className="detail-aside"><section><h2>工单上下文</h2><dl><dt>客户</dt><dd><Link to={`/customers/${ticket.organization.id}`}>{ticket.organization.name}</Link></dd><dt>联系人</dt><dd>{ticket.contact?.name ?? '-'}</dd><dt>负责人</dt><dd>{ticket.assignee?.name ?? '未分配'}</dd><dt>计划完成</dt><dd>{formatDate(ticket.plannedAt)}</dd><dt>来源</dt><dd>{ticket.source}</dd><dt>分类</dt><dd>{ticket.category}</dd></dl></section><section><h2>设备环境</h2><dl><dt>相机型号</dt><dd>{ticket.cameraModel || '-'}</dd><dt>SN</dt><dd className="mono">{ticket.serialNumber || '-'}</dd><dt>SDK</dt><dd>{ticket.sdkVersion || '-'}</dd><dt>系统环境</dt><dd>{ticket.systemEnvironment || '-'}</dd></dl></section><section><h2>问题描述</h2><p>{ticket.description}</p></section></aside>
    </div>
  </div>
}
