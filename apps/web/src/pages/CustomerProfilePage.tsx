import { ArrowLeft, Cpu, ExternalLink, FileClock, Pencil, Plus, Share2, UserRound, Wrench } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/Status'
import { useAuth } from '../context/AuthContext'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { deviceStatusLabelByOwner } from '../lib/labels'
import type { CustomerProfile } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'
import { DeviceStatusBadge } from './DevicesPage'
import { LoanStatusBadge } from './LoansPage'
import { RepairStatusBadge } from './RepairsPage'
import { SimpleFormModal } from './CustomersPage'

type Tab = 'tickets' | 'loans' | 'repairs' | 'devices'

export function CustomerProfilePage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const remote = useRemote(() => api<CustomerProfile>(`/customers/${id}/profile`), [id], true)
  const [tab, setTab] = useState<Tab>('tickets')
  const [editing, setEditing] = useState(false)
  const [dialog, setDialog] = useState<'contact' | 'device' | null>(null)
  const canManage = user?.role === 'admin' || user?.role === 'support'
  if (remote.loading) return <PageLoading />
  if (remote.error || !remote.data) return <PageError message={remote.error} retry={remote.refresh} />
  const { organization: customer, contacts, devices, tickets, loanOrders, repairOrders } = remote.data
  const activeTickets = tickets.filter((ticket) => !['RESOLVED', 'CLOSED'].includes(ticket.status))
  const activeLoans = loanOrders.filter((loan) => loan.status === 'ONGOING' || loan.status === 'OVERDUE')
  const activeRepairs = repairOrders.filter((repair) => repair.status !== 'CLOSED')
  const textCard = (title: string, text?: string | null) => <section className="panel"><div className="section-heading"><div><h2>{title}</h2></div></div>{text ? <p className="pre-wrap">{text}</p> : <p className="placeholder-text">待补充</p>}</section>
  return <div className="page-stack">
    <header className="detail-header"><button className="icon-button" onClick={() => navigate('/customers')}><ArrowLeft size={20} /></button>
      <div><span className="eyebrow">客户 360</span><h1>{customer.name}</h1><div className="inline-meta"><span className="level">{customer.level || '-'}</span><span>{customer.industry || '未设置行业'}</span><span>{customer.region || '未设置地区'}</span>
        {customer.websiteUrl && <a className="link-ext" href={customer.websiteUrl} target="_blank" rel="noreferrer">官网<ExternalLink size={12} /></a>}
        {customer.wikiRef && <a className="link-ext" href={customer.wikiRef} target="_blank" rel="noreferrer">百科<ExternalLink size={12} /></a>}
      </div></div>
      {canManage && <button className="button" onClick={() => setEditing(true)}><Pencil size={15} />编辑资料</button>}
    </header>
    <div className="profile-cards">{textCard('背景介绍', customer.background)}{textCard('应用场景', customer.applicationScenarios)}{textCard('项目需求', customer.projectNeeds)}</div>
    <section className="customer-summary">
      <div><span><UserRound size={12} /> 联系人（{contacts.length}）{canManage && <button className="icon-button" title="新增联系人" onClick={() => setDialog('contact')}><Plus size={13} /></button>}</span><strong>{contacts.slice(0, 3).map((item) => item.name).join('、') || '暂无联系人'}</strong></div>
      <div><span><Cpu size={12} /> 设备（{devices.length}）{canManage && <button className="icon-button" title="新增设备" onClick={() => setDialog('device')}><Plus size={13} /></button>}</span><strong>{devices.slice(0, 3).map((item) => `${item.name}·${deviceStatusLabelByOwner(item.status ?? 'IN_STOCK', item.ownerType)}`).join('，') || '暂无设备'}</strong></div>
      <div><span><FileClock size={12} /> 进行中工单（{activeTickets.length}）</span><strong>{activeTickets.slice(0, 5).map((item) => item.number).join('、') || '暂无'}</strong></div>
      <div className="wide"><span><Share2 size={12} /> 借测中 {activeLoans.length} · <Wrench size={12} /> 返修中 {activeRepairs.length}</span><strong>{[...activeLoans.map((item) => item.loanNo), ...activeRepairs.map((item) => item.repairNo)].slice(0, 5).join('、') || '暂无进行中借测/返修'}</strong></div>
    </section>
    <div className="tabs">
      <button className={tab === 'tickets' ? 'active' : ''} onClick={() => setTab('tickets')}>工单记录</button>
      <button className={tab === 'loans' ? 'active' : ''} onClick={() => setTab('loans')}>借测记录</button>
      <button className={tab === 'repairs' ? 'active' : ''} onClick={() => setTab('repairs')}>返修记录</button>
      <button className={tab === 'devices' ? 'active' : ''} onClick={() => setTab('devices')}>设备记录</button>
    </div>
    <section className="panel no-padding"><div className="table-wrap">
      {tab === 'tickets' && <table><thead><tr><th>编号</th><th>问题</th><th>状态</th><th>负责人</th><th>创建时间</th></tr></thead><tbody>{tickets.map((ticket) => <tr key={ticket.id} onClick={() => navigate(`/tickets/${ticket.id}`)}><td className="mono">{ticket.number}</td><td><strong>{ticket.title}</strong></td><td><StatusBadge status={ticket.status} /></td><td>{ticket.assignee?.name ?? '未分配'}</td><td>{formatDate(ticket.createdAt)}</td></tr>)}</tbody></table>}
      {tab === 'tickets' && !tickets.length && <Empty text="暂无工单记录" />}
      {tab === 'loans' && <table><thead><tr><th>单号</th><th>设备</th><th>借出日期</th><th>预计归还</th><th>状态</th></tr></thead><tbody>{loanOrders.map((loan) => <tr key={loan.id}><td className="mono">{loan.loanNo}</td><td className="mono">{loan.items.map((item) => item.device.serialNumber || item.device.name).join(', ')}</td><td>{formatDate(loan.loanedAt)}</td><td>{formatDate(loan.dueAt)}</td><td><LoanStatusBadge status={loan.status} /></td></tr>)}</tbody></table>}
      {tab === 'loans' && !loanOrders.length && <Empty text="暂无借测记录" />}
      {tab === 'repairs' && <table><thead><tr><th>单号</th><th>SN</th><th>故障现象</th><th>状态</th><th>收货日期</th></tr></thead><tbody>{repairOrders.map((repair) => <tr key={repair.id}><td className="mono">{repair.repairNo}</td><td className="mono">{repair.serialNumber || repair.device?.serialNumber || '-'}</td><td className="truncate-cell">{repair.symptom}</td><td><RepairStatusBadge status={repair.status} /></td><td>{formatDate(repair.receivedAt)}</td></tr>)}</tbody></table>}
      {tab === 'repairs' && !repairOrders.length && <Empty text="暂无返修记录" />}
      {tab === 'devices' && <table><thead><tr><th>名称</th><th>型号</th><th>SN</th><th>状态</th><th>保修到期</th></tr></thead><tbody>{devices.map((device) => <tr key={device.id}><td><strong>{device.name}</strong></td><td>{device.cameraModel || device.product || '-'}</td><td className="mono">{device.serialNumber || '-'}</td><td><DeviceStatusBadge status={device.status} ownerType={device.ownerType} /></td><td>{formatDate(device.warrantyUntil)}</td></tr>)}</tbody></table>}
      {tab === 'devices' && !devices.length && <Empty text="暂无设备记录" />}
    </div></section>
    {editing && <ProfileEditModal customer={customer} onClose={() => setEditing(false)} onSaved={async () => { setEditing(false); await remote.refresh() }} />}
    {dialog === 'contact' && <SimpleFormModal title="新增联系人" fields={[['name', '姓名', true], ['title', '职位'], ['phone', '电话'], ['email', '邮箱'], ['wechat', '微信']]} onClose={() => setDialog(null)} onSubmit={async (payload) => { await api(`/customers/${id}/contacts`, { method: 'POST', body: JSON.stringify(payload) }); setDialog(null); await remote.refresh() }} />}
    {dialog === 'device' && <SimpleFormModal title="新增设备" fields={[['name', '设备名称', true], ['product', '产品'], ['cameraModel', '相机型号'], ['serialNumber', '序列号'], ['sdkVersion', 'SDK 版本'], ['location', '安装位置']]} onClose={() => setDialog(null)} onSubmit={async (payload) => { await api(`/customers/${id}/devices`, { method: 'POST', body: JSON.stringify(payload) }); setDialog(null); await remote.refresh() }} />}
  </div>
}

function ProfileEditModal({ customer, onClose, onSaved }: { customer: CustomerProfile['organization']; onClose: () => void; onSaved: () => Promise<void> }) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '').trim()
    try { await api(`/customers/${customer.id}`, { method: 'PATCH', body: JSON.stringify({ name: value('name'), websiteUrl: value('websiteUrl') || null, wikiRef: value('wikiRef') || null, background: value('background') || null, applicationScenarios: value('applicationScenarios') || null, projectNeeds: value('projectNeeds') || null }) }); await onSaved() } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') } finally { setBusy(false) }
  }
  return <Modal title="编辑客户资料" onClose={onClose} wide><form className="form-grid" onSubmit={submit}>
    <label className="span-2">客户名称<input name="name" required minLength={2} maxLength={200} defaultValue={customer.name} /></label>
    <label>官网链接<input name="websiteUrl" type="url" defaultValue={customer.websiteUrl ?? ''} placeholder="https://" /></label>
    <label>百科链接<input name="wikiRef" type="url" defaultValue={customer.wikiRef ?? ''} placeholder="https://" /></label>
    <label className="span-2">背景介绍<textarea name="background" rows={4} defaultValue={customer.background ?? ''} /></label>
    <label className="span-2">应用场景<textarea name="applicationScenarios" rows={4} defaultValue={customer.applicationScenarios ?? ''} /></label>
    <label className="span-2">项目需求<textarea name="projectNeeds" rows={4} defaultValue={customer.projectNeeds ?? ''} /></label>
    {error && <div className="form-error span-2">{error}</div>}
    <div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在保存' : '保存'}</button></div>
  </form></Modal>
}
