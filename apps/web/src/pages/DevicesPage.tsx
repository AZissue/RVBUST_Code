import { Building2, Cpu, Database, Handshake, Package, Plus, RotateCcw, Search, Trash2, Wrench, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Modal } from '../components/Modal'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { deviceHealthLabels, deviceOwnerLabel, deviceStatusLabels, deviceStatusLabelByOwner } from '../lib/labels'
import type { Customer, Device, DeviceOwnerType, DeviceStatus, LoanOrder } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

export { deviceStatusLabels }
export function DeviceHealthBadge({ health }: { health?: Device['health'] }) {
  if (!health) return <span className="muted">-</span>
  return <span className={`badge health-${health.toLowerCase()}`}>{deviceHealthLabels[health] ?? health}</span>
}
export function DeviceStatusBadge({ status, ownerType }: { status?: DeviceStatus; ownerType?: DeviceOwnerType }) {
  const value = status ?? 'IN_STOCK'
  return <span className={`badge ${value === 'IN_STOCK' ? 'ok' : value === 'REPAIRING' ? 'warn' : value === 'RETIRED' ? '' : 'status-in_progress'}`}>{deviceStatusLabelByOwner(value, ownerType ?? 'CUSTOMER')}</span>
}

export function WarrantyCell({ until }: { until?: string | null }) {
  if (!until) return <span>-</span>
  const end = new Date(until)
  const days = Math.ceil((end.getTime() - Date.now()) / 86400000)
  if (days < 0) return <span>{formatDate(until)} <span className="mini-tag danger-tag">已过保</span></span>
  if (days <= 30) return <span>{formatDate(until)} <span className="mini-tag warn-tag">即将到期</span></span>
  return <span>{formatDate(until)}</span>
}

const STATUS_OPTIONS: { value: DeviceStatus; label: string }[] = [
  { value: 'IN_STOCK', label: '在库' },
  { value: 'LOANED', label: '借测中' },
  { value: 'REPAIRING', label: '返修中' },
  { value: 'RETIRED', label: '已报废' },
]

export function DevicesPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [ownerType, setOwnerType] = useState('')
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Device | null>(null)
  const [error, setError] = useState('')
  const remote = useRemote(() => api<Device[]>('/devices'), [], true)
  const loansRemote = useRemote(() => api<LoanOrder[]>('/loans'), [], false)
  const [todoTab, setTodoTab] = useState<'overdue' | 'dueSoon' | 'stale'>('overdue')
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const allDevices = remote.data ?? []
  const allLoans = loansRemote.data ?? []
  const activeLoans = allLoans.filter((loan) => loan.status === 'ONGOING' || loan.status === 'OVERDUE')
  const dueState = (loan: LoanOrder) => loan.dueAt ? Math.ceil((new Date(loan.dueAt).getTime() - Date.now()) / 86400000) : Number.POSITIVE_INFINITY
  const overdueLoans = activeLoans.filter((loan) => dueState(loan) < 0).sort((a, b) => dueState(a) - dueState(b))
  const dueSoonLoans = activeLoans.filter((loan) => { const d = dueState(loan); return d >= 0 && d <= 7 }).sort((a, b) => dueState(a) - dueState(b))
  const staleLoans = activeLoans.filter((loan) => !loan.updatedAt || Date.now() - new Date(loan.updatedAt).getTime() >= 14 * 86400000)
  const countBy = (predicate: (item: Device) => boolean) => allDevices.filter(predicate).length
  const todoLists = { overdue: overdueLoans, dueSoon: dueSoonLoans, stale: staleLoans }
  const todoLabels = { overdue: '已逾期', dueSoon: '7天内到期', stale: '久未跟进' }
  const todoRoutes = { overdue: '/loans?status=OVERDUE', dueSoon: '/loans?status=ONGOING', stale: '/loans' }
  const todoList = todoLists[todoTab]
  const hasFilter = Boolean(search || status || ownerType)
  const resetFilters = () => { setSearch(''); setStatus(''); setOwnerType('') }
  const devices = allDevices.filter((item) => {
    const matches = `${item.name} ${item.cameraModel ?? ''} ${item.serialNumber ?? ''} ${item.organization?.name ?? ''}`.toLowerCase().includes(search.toLowerCase())
    return matches && (!status || item.status === status) && (!ownerType || item.ownerType === ownerType)
  })
  const changeStatus = async (item: Device, next: DeviceStatus) => {
    if (next === item.status) return
    if (next === 'RETIRED' && !window.confirm(`确认将「${item.name}」报废？报废后设备退出流转。`)) return
    setError(''); try { await api(`/devices/${item.id}/status`, { method: 'PATCH', body: JSON.stringify({ status: next }) }); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '状态流转失败') }
  }
  // KPI 全部为设备表筛选卡：点击即过滤下方列表，避免「有的跳转有的筛选」的混用逻辑
  const kpi: { key: string; label: string; value: number; icon: typeof Cpu; active: boolean; run: () => void }[] = [
    { key: '', label: '设备总数', value: allDevices.length, icon: Database, active: !status && !ownerType, run: resetFilters },
    { key: 'IN_STOCK', label: '在库', value: countBy((item) => item.status === 'IN_STOCK'), icon: Package, active: status === 'IN_STOCK', run: () => setStatus(status === 'IN_STOCK' ? '' : 'IN_STOCK') },
    { key: 'LOANED', label: '借测中', value: countBy((item) => item.status === 'LOANED'), icon: Handshake, active: status === 'LOANED', run: () => setStatus(status === 'LOANED' ? '' : 'LOANED') },
    { key: 'REPAIRING', label: '返修中', value: countBy((item) => item.status === 'REPAIRING'), icon: Wrench, active: status === 'REPAIRING', run: () => setStatus(status === 'REPAIRING' ? '' : 'REPAIRING') },
    { key: 'RETIRED', label: '已报废', value: countBy((item) => item.status === 'RETIRED'), icon: Trash2, active: status === 'RETIRED', run: () => setStatus(status === 'RETIRED' ? '' : 'RETIRED') },
    { key: 'COMPANY', label: '公司样机', value: countBy((item) => item.ownerType === 'COMPANY'), icon: Building2, active: ownerType === 'COMPANY', run: () => setOwnerType(ownerType === 'COMPANY' ? '' : 'COMPANY') },
  ]
  return <div className="page-stack">
    <header className="page-header"><div><span className="eyebrow">DEVICE OVERVIEW</span><h1>设备总览</h1><p>统一管理中心库存、客户资产、借测与返修中的设备。</p></div><button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />新增设备</button></header>
    {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
    <section className="metric-strip">{kpi.map((item) => <button key={item.key} className={`metric clickable ${item.active ? 'filter-active' : ''}`} onClick={item.run} title={`筛选：${item.label}`}>
      <item.icon size={17} /><span>{item.label}</span><strong>{item.value}</strong>
    </button>)}</section>
    <div className="two-columns overview-columns">
      <section className="panel"><div className="section-heading"><div><h2>借测待办</h2><p>逾期与临期借测需要优先跟进</p></div><button className="button small" onClick={() => navigate('/loans')}>进入借测管理</button></div>
        <div className="action-tabs">{(['overdue', 'dueSoon', 'stale'] as const).map((key) => <button key={key} className={`action-tab ${todoTab === key ? 'active' : ''}`} onClick={() => setTodoTab(key)}>{todoLabels[key]}<span className="count-badge">{todoLists[key].length}</span></button>)}</div>
        {!todoList.length && <Empty text={`当前没有${todoLabels[todoTab]}的借测单`} />}
        <div className="compact-list">{todoList.slice(0, 8).map((loan) => { const d = dueState(loan); const sn = loan.items.map((item) => item.device.serialNumber || item.device.name).join(', '); return <button className="compact-item" key={loan.id} onClick={() => navigate(todoRoutes[todoTab])}>
          <div><strong>{loan.organization.name} · {loan.items[0]?.device.cameraModel || '未登记型号'}</strong><span className="mono">{sn || '未关联设备'} · {loan.loanNo} · {loan.assignee?.name ?? '未指派'}</span></div>
          <span className={`mini-tag ${d < 0 ? 'danger-tag' : d <= 7 ? 'warn-tag' : ''}`}>{d < 0 ? `已逾期 ${-d} 天` : d === 0 ? '今天到期' : `${d} 天后到期`}</span>
        </button> })}</div>
      </section>
      <section className="panel"><div className="section-heading"><div><h2>健康度分布</h2><p>按借测/返修周转自动评估</p></div></div>
        {(['CHECK', 'ATTENTION', 'OK'] as const).map((key) => { const count = allDevices.filter((item) => item.health === key).length; const colors = { OK: 'var(--success)', ATTENTION: 'var(--warning)', CHECK: 'var(--brand)' }; return <div className="donut-row" key={key}><span className="donut-dot" style={{ background: colors[key] }} />{deviceHealthLabels[key]}<strong>{count} 台</strong></div> })}
        <div className="section-heading" style={{ marginTop: 16 }}><div><h2>归属分布</h2></div></div>
        <div className="donut-row"><span className="donut-dot" style={{ background: 'var(--brand)' }} />客户资产<strong>{allDevices.filter((item) => item.ownerType === 'CUSTOMER').length} 台</strong></div>
        <div className="donut-row"><span className="donut-dot" style={{ background: 'var(--muted)' }} />公司样机<strong>{allDevices.filter((item) => item.ownerType === 'COMPANY').length} 台</strong></div>
      </section>
    </div>
    <section className="toolbar">
      <div className="searchbox"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索名称、型号、SN 或客户" /></div>
      <select aria-label="设备状态筛选" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option>{Object.entries(deviceStatusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      <select aria-label="设备归属筛选" value={ownerType} onChange={(event) => setOwnerType(event.target.value)}><option value="">全部归属</option><option value="COMPANY">公司样机</option><option value="CUSTOMER">客户资产</option></select>
      {hasFilter && <button className="button small" onClick={resetFilters}><RotateCcw size={13} />重置</button>}
      <span className="result-count">{devices.length} 台设备</span>
    </section>
    <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>名称</th><th>型号</th><th>SN</th><th>归属</th><th>状态</th><th>周转（借测/维修）</th><th>健康度</th><th>保修到期</th><th>操作</th></tr></thead><tbody>{devices.map((item) => <tr key={item.id} className="clickable-row" onClick={() => navigate(`/devices/${item.id}`)}>
      <td><strong className="with-icon"><Cpu size={15} />{item.name}</strong></td><td>{item.cameraModel || item.product || '-'}</td><td className="mono">{item.serialNumber || '-'}</td>
      <td>{item.ownerType === 'COMPANY' ? <span>{deviceOwnerLabel('COMPANY')}</span> : <span>{item.organization?.name ?? <span className="muted">客户资产 · 未关联客户</span>}</span>}</td>
      <td><DeviceStatusBadge status={item.status} ownerType={item.ownerType} /></td><td className="muted">借测 {item.loanCount ?? 0} 次 / 维修 {item.repairCount ?? 0} 次</td><td><DeviceHealthBadge health={item.health} /></td>
      <td><WarrantyCell until={item.warrantyUntil} /></td>
      <td><div className="row-actions" onClick={(event) => event.stopPropagation()}>
        <select className="cell-select" aria-label="修改设备状态" value={item.status ?? 'IN_STOCK'} onChange={(event) => void changeStatus(item, event.target.value as DeviceStatus)}>{STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
        <button className="button small" onClick={() => setEditing(item)}>编辑</button>
      </div></td>
    </tr>)}</tbody></table>{!devices.length && <Empty text={hasFilter ? '没有符合筛选条件的设备' : '暂无设备，点击右上角新增'} />}</div></section>
    {creating && <DeviceFormModal title="新增设备" onClose={() => setCreating(false)} onSubmit={async (payload) => { await api('/devices', { method: 'POST', body: JSON.stringify(payload) }); setCreating(false); await remote.refresh() }} />}
    {editing && <DeviceFormModal title={`编辑设备：${editing.name}`} initial={editing} onClose={() => setEditing(null)} onSubmit={async (payload) => { await api(`/devices/${editing.id}`, { method: 'PATCH', body: JSON.stringify(payload) }); setEditing(null); await remote.refresh() }} />}
  </div>
}

export function DeviceFormModal({ title, initial, onClose, onSubmit }: { title: string; initial?: Device; onClose: () => void; onSubmit: (payload: Record<string, string>) => Promise<void> }) {
  const customers = useRemote(() => api<Customer[]>('/customers'), [])
  const [ownerType, setOwnerType] = useState<DeviceOwnerType>(initial?.ownerType ?? 'CUSTOMER')
  const [organizationId, setOrganizationId] = useState(initial?.organizationId ?? '')
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const switchOwnerType = (next: DeviceOwnerType) => { setOwnerType(next); if (next === 'COMPANY') setOrganizationId('') }
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    if (ownerType === 'CUSTOMER' && !organizationId) { setError('客户资产必须选择所属客户'); setBusy(false); return }
    const form = new FormData(event.currentTarget)
    const payload = Object.fromEntries(['name', 'product', 'cameraModel', 'serialNumber', 'assetNo', 'location', 'purchaseDate', 'warrantyUntil', 'notes'].map((key) => [key, String(form.get(key) ?? '').trim()]).filter(([, value]) => value))
    payload.ownerType = ownerType
    if (organizationId) payload.organizationId = organizationId
    try { await onSubmit(payload as Record<string, string>) } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') } finally { setBusy(false) }
  }
  return <Modal title={title} onClose={onClose} wide><form className="form-grid" onSubmit={submit}>
    <label>设备名称<input name="name" required defaultValue={initial?.name} /></label>
    <label>归属<select name="ownerType" value={ownerType} onChange={(event) => switchOwnerType(event.target.value as DeviceOwnerType)}><option value="CUSTOMER">客户资产</option><option value="COMPANY">公司样机</option></select></label>
    <label>所属客户<select name="organizationId" required={ownerType === 'CUSTOMER'} value={organizationId} onChange={(event) => setOrganizationId(event.target.value)}><option value="">{ownerType === 'COMPANY' ? '公司库存（不关联客户）' : '选择客户'}</option>{customers.data?.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select></label>
    <label>产品<input name="product" defaultValue={initial?.product ?? ''} /></label>
    <label>相机型号<input name="cameraModel" defaultValue={initial?.cameraModel ?? ''} /></label>
    <label>序列号<input name="serialNumber" defaultValue={initial?.serialNumber ?? ''} /></label>
    <label>资产编号<input name="assetNo" defaultValue={initial?.assetNo ?? ''} placeholder="仅公司样机填写" /></label>
    <label>位置<input name="location" defaultValue={initial?.location ?? ''} /></label>
    <label>采购日期<input name="purchaseDate" type="date" defaultValue={initial?.purchaseDate?.slice(0, 10)} /></label>
    <label>保修到期<input name="warrantyUntil" type="date" defaultValue={initial?.warrantyUntil?.slice(0, 10)} /></label>
    <label className="span-2">备注<textarea name="notes" rows={3} defaultValue={initial?.notes ?? ''} /></label>
    {error && <div className="form-error span-2">{error}</div>}
    <div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在保存' : '保存'}</button></div>
  </form></Modal>
}
