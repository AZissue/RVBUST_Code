import { Archive, ArrowLeft, CheckCircle2, ClipboardList, Clock3, MessageSquare, Plus, Search, Send, X } from 'lucide-react'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Modal } from '../components/Modal'
import { PriorityBadge, StatusBadge, statusLabel } from '../components/Status'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { statusChangeLabel, ticketEventTypeLabel, ticketSourceLabel, ticketSourceLabels } from '../lib/labels'
import type { Customer, Ticket, TicketStatus } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

const sources = Object.entries(ticketSourceLabels)
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
    {creating && <CreateTicketModal defaultAssigneeId={user?.id} onClose={() => { setCreating(false); params.delete('create'); setParams(params) }} onCreated={async (ticket, notice) => { setCreating(false); await remote.refresh(); navigate(`/tickets/${ticket.id}`, notice ? { state: { notice } } : undefined) }} />}
  </div>
}

function CreateTicketModal({ onClose, onCreated, defaultAssigneeId }: { onClose: () => void; onCreated: (ticket: Ticket, notice?: string) => void; defaultAssigneeId?: string }) {
  const [assignee, setAssignee] = useState(defaultAssigneeId ?? '')
  const users = useRemote(() => api<Array<{ id: string; name: string }>>('/users/assignable'), [])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [customerName, setCustomerName] = useState('')
  useEffect(() => { void api<Customer[]>('/customers').then(setCustomers).catch((e: Error) => setError(e.message)) }, [])
  const customerMatches = customerName.trim() ? customers.filter((c) => c.name.toLowerCase().includes(customerName.trim().toLowerCase())) : customers
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '')
    const assigneeId = value('assigneeId') || undefined
    const name = customerName.trim()
    let customer = customers.find((c) => c.name === name)
    let notice: string | undefined
    try {
      if (!customer) {
        if (name.length < 2) throw new Error('客户名称至少 2 个字符，请修正后再创建')
        customer = await api<Customer>('/customers', { method: 'POST', body: JSON.stringify({ name }) })
        setCustomers((list) => [...list, customer!])
        notice = `已新建客户「${name}」，建议到客户管理完善客户资料`
      }
      const ticket = await api<Ticket>('/tickets', { method: 'POST', body: JSON.stringify({ assigneeId, source: value('source'), organizationId: customer.id, category: value('category'), title: value('title'), description: value('description'), priority: value('priority'), cameraModel: value('cameraModel') || undefined, serialNumber: value('serialNumber') || undefined, sdkVersion: value('sdkVersion') || undefined, systemEnvironment: value('systemEnvironment') || undefined, plannedAt: value('plannedAt') ? new Date(value('plannedAt')).toISOString() : undefined }) })
      onCreated(ticket, notice)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '创建失败') } finally { setBusy(false) }
  }
  return <Modal title="创建技术支持工单" onClose={onClose} wide><form className="form-grid" onSubmit={submit}>
    <label className="span-2">负责人<select name="assigneeId" value={assignee} onChange={(e) => setAssignee(e.target.value)}><option value="">未分配</option>{users.data?.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select><small>不指定则默认为创建人（你自己）</small></label>
    <label>问题来源<select name="source" defaultValue="AFTER_SALES_INCIDENT">{sources.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <label>客户公司<input name="customerName" required value={customerName} onChange={(e) => setCustomerName(e.target.value)} list="ticket-customers" placeholder="输入客户名，可模糊匹配" autoComplete="off" /><datalist id="ticket-customers">{customerMatches.map((customer) => <option key={customer.id} value={customer.name} />)}</datalist></label>
    <label>问题分类<input name="category" required placeholder="如：网络连接" /></label><label>优先级<select name="priority" defaultValue="MEDIUM"><option value="LOW">低</option><option value="MEDIUM">中</option><option value="HIGH">高</option><option value="URGENT">紧急</option></select></label>
    <label className="span-2">问题标题<input name="title" required minLength={3} /></label><label className="span-2">问题描述<textarea name="description" required rows={4} /></label>
    <label>相机型号<input name="cameraModel" /></label><label>序列号<input name="serialNumber" /></label><label>SDK 版本<input name="sdkVersion" /></label><label>计划完成时间<input name="plannedAt" type="datetime-local" /></label>
    <label className="span-2">系统环境<textarea name="systemEnvironment" rows={2} placeholder="OS、网络、SDK、运行环境" /></label>
    {error && <div className="form-error span-2">{error}</div>}<div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在创建' : '确认创建'}</button></div>
  </form></Modal>
}

export function TicketDetailPage() {
  const { user } = useAuth()
  const users = useRemote(() => api<Array<{ id: string; name: string }>>('/users/assignable'), [])
  const [saving, setSaving] = useState(false)
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const [notice, setNotice] = useState<string>((location.state as { notice?: string } | null)?.notice ?? '')
  const remote = useRemote(() => api<Ticket>(`/tickets/${id}`), [id], true)
  const [message, setMessage] = useState('')
  const [visibility, setVisibility] = useState<'INTERNAL' | 'CUSTOMER'>('INTERNAL')
  const [error, setError] = useState('')
  if (remote.loading) return <PageLoading />
  if (remote.error || !remote.data) return <PageError message={remote.error} retry={remote.refresh} />
  const ticket = remote.data
  const editable = user?.role === 'admin' || user?.id === ticket.createdBy?.id || user?.id === ticket.assignee?.id
  const assign = async (assigneeId: string) => { setSaving(true); setError(''); try { await api(`/tickets/${id}`, { method: 'PATCH', body: JSON.stringify({ assigneeId }) }); await remote.refresh() } catch (e) { setError(e instanceof Error ? e.message : '分配失败') } finally { setSaving(false) } }
  const changeStatus = async (status: TicketStatus) => { try { await api(`/tickets/${id}/status`, { method: 'POST', body: JSON.stringify({ status }) }); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '状态更新失败') } }
  const addEvent = async () => { if (!message.trim()) return; const canReply = editable && visibility === 'CUSTOMER'; try { await api(`/tickets/${id}/events`, { method: 'POST', body: JSON.stringify({ type: canReply ? 'CUSTOMER_REPLY' : 'INTERNAL_NOTE', visibility: canReply ? 'CUSTOMER' : 'INTERNAL', content: message }) }); setMessage(''); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '发送失败') } }
  return <div className="page-stack">
    <section className="toolbar ticket-meta-bar"><span>创建人：<strong>{ticket.createdBy?.name ?? '-'}</strong></span><span>创建时间：{formatDate(ticket.createdAt)}</span><label>负责人{editable ? <select aria-label="工单负责人" disabled={saving || !users.data} value={ticket.assignee?.id ?? ''} onChange={(e) => void assign(e.target.value)}><option disabled value="">未分配</option>{users.data?.map((u) => <option value={u.id} key={u.id}>{u.name}</option>)}</select> : <strong>{ticket.assignee?.name ?? '未分配'}</strong>}</label></section>
    {ticket.rawText && <details className="raw-input"><summary>原始快速输入</summary><p>{ticket.rawText}</p></details>}
    <header className="detail-header"><button className="icon-button" onClick={() => navigate('/tickets')} title="返回"><ArrowLeft size={20} /></button><div><span className="mono eyebrow">{ticket.number}</span><h1>{ticket.title}</h1><div className="inline-meta"><StatusBadge status={ticket.status} /><PriorityBadge priority={ticket.priority} /><span>{ticket.organization.name}</span></div></div><select className="status-select" disabled={!editable} value={ticket.status} onChange={(event) => void changeStatus(event.target.value as TicketStatus)}>{states.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}</select></header>
    {notice && <div className="form-error" style={{ borderColor: 'var(--success, #2e7d32)', background: 'rgba(46,125,50,.08)', color: 'var(--success, #2e7d32)' }}><button onClick={() => setNotice('')}><X size={14} /></button>{notice}</div>}
    {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
    <div className="ticket-layout"><section className="panel"><div className="section-heading"><div><h2>处理时间线</h2><p>内部记录与客户回复严格区分</p></div></div><div className="timeline">{ticket.events?.map((event) => <article key={event.id}><div className="timeline-dot" /><header><strong>{event.author.name}</strong><span className={`visibility ${event.visibility.toLowerCase()}`}>{event.visibility === 'INTERNAL' ? '内部' : '客户可见'}</span><time>{formatDate(event.createdAt)}</time></header><p>{event.type === 'STATUS_CHANGE' ? statusChangeLabel(event.content) : event.content}</p><small>{ticketEventTypeLabel(event.type)}</small></article>)}</div>
      {user?.role !== 'customer' && <div className="composer">{!editable && <p className="readonly-hint">当前为协作只读模式：可追加内部排查备注，内容与状态的修改仅限创建人、负责人或管理员</p>}<div className="segmented">{editable ? <><button className={visibility === 'INTERNAL' ? 'active' : ''} onClick={() => setVisibility('INTERNAL')}>内部备注</button><button className={visibility === 'CUSTOMER' ? 'active' : ''} onClick={() => setVisibility('CUSTOMER')}>客户回复</button></> : <button className="active">内部备注</button>}</div><textarea rows={3} value={message} onChange={(event) => setMessage(event.target.value)} placeholder={editable && visibility === 'CUSTOMER' ? '填写可发送给客户的正式回复' : '记录排查过程，仅内部可见'} /><button className="button primary" onClick={() => void addEvent()}><Send size={16} />写入时间线</button></div>}</section>
      <aside className="detail-aside"><section><h2>工单上下文</h2><dl><dt>客户</dt><dd><Link to={`/customers/${ticket.organization.id}`}>{ticket.organization.name}</Link></dd><dt>联系人</dt><dd>{ticket.contact?.name ?? '-'}</dd><dt>创建人</dt><dd>{ticket.createdBy?.name ?? '-'}</dd><dt>负责人</dt><dd>{editable ? <select aria-label="工单负责人" disabled={saving || !users.data} value={ticket.assignee?.id ?? ''} onChange={(e) => void assign(e.target.value)}><option disabled value="">未分配</option>{users.data?.map((u) => <option value={u.id} key={u.id}>{u.name}</option>)}</select> : ticket.assignee?.name ?? '未分配'}</dd><dt>计划完成</dt><dd>{formatDate(ticket.plannedAt)}</dd><dt>来源</dt><dd>{ticketSourceLabel(ticket.source)}</dd><dt>分类</dt><dd>{ticket.category}</dd></dl></section><section><h2>设备环境</h2><dl><dt>相机型号</dt><dd>{ticket.cameraModel || '-'}</dd><dt>SN</dt><dd className="mono">{ticket.serialNumber || '-'}</dd><dt>SDK</dt><dd>{ticket.sdkVersion || '-'}</dd><dt>系统环境</dt><dd>{ticket.systemEnvironment || '-'}</dd></dl></section><section><h2>问题描述</h2><p>{ticket.description}</p></section></aside>
    </div>
  </div>
}
