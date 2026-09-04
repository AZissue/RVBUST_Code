import { Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import type { Customer, Device, Ticket, TicketPriority } from '../types'
import { Modal } from './Modal'
import { StatusBadge } from './Status'
import { SimpleFormModal } from '../pages/CustomersPage'

interface Candidate { id: string; name: string; score: number }
interface Parsed {
  parser?: 'ai' | 'rule'; fallbackReason?: string; model?: string
  rawText: string; issue: string; title: string; priority: TicketPriority; deviceText: string
  matchedCustomer: Candidate | null; customerCandidates: Candidate[]; customerText: string
  matchedAssignee: Candidate | null; assigneeCandidates: Candidate[]; assigneeText: string; assigneeDefaulted: boolean
  matchedDevice: Device | null
}
type Similar = Ticket & { similarity: number }

export function QuickTicketInput() {
  const { user } = useAuth()
  const [rawText, setRawText] = useState('')
  const [parsed, setParsed] = useState<Parsed | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState<{ ticket: Ticket; updated: boolean } | null>(null)
  const parse = async () => {
    setBusy(true); setError(''); setSuccess(null)
    try { setParsed(await api<Parsed>('/tickets/quick/parse', { method: 'POST', body: JSON.stringify({ rawText }) })) }
    catch (e) { setError(e instanceof Error ? e.message : '解析失败') } finally { setBusy(false) }
  }
  return <section className="workspace-section quick-capture-panel"><div className="section-heading"><h2>快速记录</h2></div>
    <textarea aria-label="快速工单输入" maxLength={4000} value={rawText} onChange={(e) => setRawText(e.target.value)} rows={7} placeholder="浙江智享机器人 M2600拍摄3D无点云，负责人张伟，紧急" />
    {error && <div role="alert" className="form-error">{error}</div>}
    <button className="button primary" disabled={busy || rawText.trim().length < 3} onClick={() => void parse()}><Plus size={15} />{busy ? '正在解析' : '解析并创建工单'}</button>
    {success && <div className="quick-success" role="status">工单 {success.ticket.number} {success.updated ? '更新' : '创建'}成功 <Link to={`/tickets/${success.ticket.id}`}>查看工单</Link></div>}
    {parsed && <QuickTicketConfirm parsed={parsed} canCreateCustomer={user?.role === 'admin' || user?.role === 'support'} onClose={() => setParsed(null)} onSaved={(ticket, updated) => { setSuccess({ ticket, updated }); setParsed(null); setRawText('') }} />}
  </section>
}

function QuickTicketConfirm({ parsed, canCreateCustomer, onClose, onSaved }: { parsed: Parsed; canCreateCustomer: boolean; onClose: () => void; onSaved: (ticket: Ticket, updated: boolean) => void }) {
  const [customers, setCustomers] = useState<Customer[]>([])
  const [users, setUsers] = useState<Array<{ id: string; name: string }>>([])
  const [devices, setDevices] = useState<Device[]>([])
  const [organizationId, setOrganizationId] = useState(parsed.matchedCustomer?.id ?? '')
  const [assigneeId, setAssigneeId] = useState(parsed.matchedAssignee?.id ?? '')
  const [deviceId, setDeviceId] = useState(parsed.matchedDevice?.id ?? '')
  const [issue, setIssue] = useState(parsed.issue)
  const [title, setTitle] = useState(parsed.title)
  const [priority, setPriority] = useState(parsed.priority)
  const [model, setModel] = useState(parsed.deviceText)
  const [similar, setSimilar] = useState<Similar[]>([])
  const [checkedKey, setCheckedKey] = useState('')
  const [error, setError] = useState('')
  const [lookupError, setLookupError] = useState('')
  const [busy, setBusy] = useState(false)
  const [creatingCustomer, setCreatingCustomer] = useState(false)
  const [retry, setRetry] = useState(0)
  const [requestKey] = useState(() => crypto.randomUUID())
  const key = JSON.stringify([organizationId, issue, model])
  useEffect(() => {
    let current = true
    Promise.all([api<Customer[]>('/customers'), api<Array<{ id: string; name: string }>>('/users/assignable')]).then(([c, u]) => { if (current) { setCustomers(c); setUsers(u) } }).catch((e: Error) => { if (current) setError(e.message) })
    return () => { current = false }
  }, [retry])
  useEffect(() => {
    let current = true
    setDevices([])
    if (organizationId) void api<Customer>(`/customers/${organizationId}`).then((c) => { if (current) setDevices(c.devices ?? []) }).catch((e: Error) => { if (current) setError(e.message) })
    return () => { current = false }
  }, [organizationId, retry])
  useEffect(() => {
    let current = true
    setCheckedKey(''); setLookupError(''); setSimilar([])
    const timer = window.setTimeout(() => {
      if (!organizationId || !issue.trim()) return
      void api<Similar[]>('/tickets/quick/similar', { method: 'POST', body: JSON.stringify({ organizationId, issue, cameraModel: model }) }).then((items) => { if (current) { setSimilar(items); setCheckedKey(key) } }).catch((e: Error) => { if (current) setLookupError(e.message) })
    }, 250)
    return () => { current = false; window.clearTimeout(timer) }
  }, [organizationId, issue, model, retry, key])
  const ready = Boolean(organizationId && assigneeId && issue.trim().length >= 3 && title.trim().length >= 3 && checkedKey === key && !busy)
  const save = async (existing?: Similar) => {
    if (!ready) return
    if (existing && !window.confirm(`确认更新 ${existing.number}？将追加内部处理记录，并更新负责人和优先级；原描述和状态保持不变。`)) return
    setBusy(true); setError('')
    try {
      const ticket = existing ? await api<Ticket>(`/tickets/${existing.id}/quick-update`, { method: 'POST', body: JSON.stringify({ organizationId, assigneeId, priority, issue, rawText: parsed.rawText, expectedUpdatedAt: existing.updatedAt }) }) : await api<Ticket>('/tickets', { method: 'POST', body: JSON.stringify({ source: 'AFTER_SALES_INCIDENT', category: '技术问题', organizationId, assigneeId, priority, title: title.trim(), description: issue.trim(), rawText: parsed.rawText, requestKey, cameraModel: model || undefined, deviceId: deviceId || undefined }) })
      onSaved(ticket, Boolean(existing))
    } catch (e) { setError(e instanceof Error ? e.message : '保存失败'); setRetry((n) => n + 1) } finally { setBusy(false) }
  }
  return <Modal title="解析结果确认" onClose={() => { if (!busy) onClose() }} wide><div className="quick-confirm">
    <div role="status" className="muted">{parsed.parser === 'ai' ? `AI 解析 · ${parsed.model}` : `规则解析${parsed.fallbackReason ? ` · ${parsed.fallbackReason}` : ''}`}</div>
    <fieldset disabled={busy} className="form-grid">
      <label>客户<select aria-label="确认客户" value={organizationId} onChange={(e) => { setOrganizationId(e.target.value); setDeviceId('') }}><option value="">选择现有客户</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
      <label>负责人<select aria-label="确认负责人" value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}><option value="">负责人：未匹配</option>{users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select>{parsed.assigneeDefaulted && parsed.matchedAssignee && <small>默认当前用户：{parsed.matchedAssignee.name}</small>}</label>
      {!parsed.matchedCustomer && <div className="span-2 match-options">{parsed.customerCandidates.length ? <><strong>可能的客户</strong>{parsed.customerCandidates.map((c) => <label key={c.id}><input type="radio" name="customer-candidate" checked={organizationId === c.id} onChange={() => { setOrganizationId(c.id); setDeviceId('') }} />{c.name}</label>)}</> : <strong>未匹配到现有客户{parsed.customerText ? `：${parsed.customerText}` : ''}</strong>}{canCreateCustomer && <button type="button" className="button" onClick={() => setCreatingCustomer(true)}><Plus size={14} />创建新客户</button>}</div>}
      {!parsed.matchedAssignee && <div className="span-2 match-options"><strong>负责人：未匹配{parsed.assigneeText ? `（${parsed.assigneeText}）` : ''}</strong>{parsed.assigneeCandidates.map((u) => <label key={u.id}><input type="radio" name="assignee-candidate" checked={assigneeId === u.id} onChange={() => setAssigneeId(u.id)} />{u.name}</label>)}</div>}
      <label className="span-2">问题标题<input aria-label="确认标题" maxLength={240} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <label className="span-2">问题描述<textarea aria-label="确认问题" rows={3} maxLength={4000} value={issue} onChange={(e) => setIssue(e.target.value)} /></label>
      <label>优先级<select aria-label="确认优先级" value={priority} onChange={(e) => setPriority(e.target.value as TicketPriority)}><option value="LOW">低</option><option value="MEDIUM">普通</option><option value="HIGH">高</option><option value="URGENT">紧急</option></select></label>
      <label>设备型号<input maxLength={100} value={model} onChange={(e) => { setModel(e.target.value); setDeviceId('') }} /></label>
      <label className="span-2">关联设备<select value={deviceId} onChange={(e) => setDeviceId(e.target.value)}><option value="">不关联设备</option>{devices.map((d) => <option key={d.id} value={d.id}>{d.name} {d.serialNumber ?? ''}</option>)}</select></label>
    </fieldset>
    {lookupError && <div role="alert" className="form-error">相似工单检查失败：{lookupError}<button className="button" onClick={() => setRetry((n) => n + 1)}>重试</button></div>}
    {organizationId && issue.trim() && !lookupError && checkedKey !== key && <p role="status">正在检查相似工单…</p>}
    {similar.length > 0 && <section className="similar-tickets"><h3>发现可能相关的现有工单</h3>{similar.map((t) => <article key={t.id}><Link to={`/tickets/${t.id}`} target="_blank">{t.number} · {t.title}</Link><p>{t.organization.name} · {t.cameraModel || t.device?.name || '未关联设备'} · 相似度 {t.similarity}%</p><div className="header-actions"><StatusBadge status={t.status} /><button className="button" disabled={!ready} onClick={() => void save(t)}>更新现有工单</button></div></article>)}</section>}
    {error && <div role="alert" className="form-error">{error}<button className="button" onClick={() => { setError(''); setRetry((n) => n + 1) }}>重试加载</button></div>}
    {(issue.trim().length < 3 || title.trim().length < 3) && <div role="status" className="form-error">请补充问题标题和描述，至少 3 个字符。</div>}
    <div className="form-actions"><button className="button" disabled={busy} onClick={onClose}>重新编辑</button><button className="button primary" disabled={!ready} onClick={() => void save()}>{busy ? '正在保存' : similar.length ? '仍然创建新工单' : '确认创建工单'}</button></div>
    {creatingCustomer && <SimpleFormModal title="创建新客户" fields={[[ 'name', '公司名称', true ]]} onClose={() => setCreatingCustomer(false)} onSubmit={async (payload) => { const c = await api<Customer>('/customers', { method: 'POST', body: JSON.stringify(payload) }); setCustomers((list) => [...list, c]); setOrganizationId(c.id); setDeviceId(''); setCreatingCustomer(false) }} />}
  </div></Modal>
}
