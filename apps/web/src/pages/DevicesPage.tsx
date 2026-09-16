import { ArrowRight, Cpu, Database, Handshake, Package, Plus, RotateCcw, Search, Trash2, Wrench, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Modal } from '../components/Modal'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { deviceHealthLabels, deviceOwnerLabel, deviceStatusLabels, deviceStatusLabelByOwner, loanStatusLabels } from '../lib/labels'
import type { Customer, Device, DeviceOwnerType, DeviceStatus, LoanStatus, RepairStatus } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'
import './device-flow.css'

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

type Dashboard = {
  counts: Record<string, number>
  modelRank: { model: string; count: number }[]
  averageDays: number | null
  recent: RecentRow[]
  month: string
  asOf: string
}
type RecentRow =
  | { kind: 'loan'; at: string | null; id: string; loanNo: string; organization: { name: string }; items: { device: { serialNumber: string | null; cameraModel: string | null; name: string } }[]; status: LoanStatus; effectiveStatus: LoanStatus; overdueDays: number }
  | { kind: 'repair'; at: string | null; id: string; no: string; status: RepairStatus; organization: { name: string }; model: string | null; sn: string | null }
type AttentionRow = {
  id: string
  loanNo: string
  organization: { name: string }
  items: { device: { serialNumber: string | null; cameraModel: string | null; name: string } }[]
  dueAt: string | null
  effectiveStatus: LoanStatus
  overdueDays: number
}
const REPAIR_STATUS_LABELS: Record<RepairStatus, string> = { RECEIVED: '维修中', DIAGNOSING: '维修中', REPAIRING: '维修中', SHIPPED: '已寄回', CLOSED: '已关闭' }

const datetime = (value: string | null | undefined) => {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(+parsed) ? '—' : `${parsed.getFullYear()}/${parsed.getMonth() + 1}/${parsed.getDate()} ${String(parsed.getHours()).padStart(2, '0')}:${String(parsed.getMinutes()).padStart(2, '0')}:${String(parsed.getSeconds()).padStart(2, '0')}`
}

function LoanBadge({ status, overdueDays }: { status: LoanStatus; overdueDays: number }) {
  const label = loanStatusLabels[status] || (status === 'ONGOING' ? '借测中' : status)
  return <span className={`badge flow-status flow-status-${status.toLowerCase()}`}>{label}{overdueDays > 0 ? ` ${overdueDays} 天` : ''}</span>
}
function RecentStatus({ row }: { row: RecentRow }) {
  if (row.kind === 'loan') return <LoanBadge status={row.effectiveStatus} overdueDays={row.overdueDays} />
  const cls = row.status === 'CLOSED' ? 'cancelled' : row.status === 'SHIPPED' ? 'returned' : 'ongoing'
  return <span className={`badge flow-status flow-status-${cls}`}>{REPAIR_STATUS_LABELS[row.status]}</span>
}

export function DevicesPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [ownerType, setOwnerType] = useState('')
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Device | null>(null)
  const [error, setError] = useState('')
  const remote = useRemote(() => api<Device[]>('/devices'), [], true)
  const dashboardRemote = useRemote(() => api<Dashboard>('/loans/dashboard'), [], true)
  const attentionRemote = useRemote(() => api<{ items: AttentionRow[] }>('/loans/list?status=attention&sort=due_soon&pageSize=8'), [], true)
  if (remote.loading || dashboardRemote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  if (dashboardRemote.error) return <PageError message={dashboardRemote.error} retry={dashboardRemote.refresh} />
  const data = dashboardRemote.data!
  const allDevices = remote.data ?? []
  const countBy = (predicate: (item: Device) => boolean) => allDevices.filter(predicate).length
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
  const metrics: [string, string, string, string][] = [
    ['monthLoan', '本月借出', '按借出日期统计', `month=${data.month}`],
    ['monthRepair', '本月维修', '按收货日期统计', ''],
    ['active', '当前借测中', '当前未归还设备', 'status=active'],
    ['due', '7天内到期', '含今天到期', 'status=due'],
  ]
  const recent = [...data.recent].sort((a, b) => +new Date(b.at ?? 0) - +new Date(a.at ?? 0)).slice(0, 6)
  return <div className="page-stack prototype-overview">
    <header className="page-header"><div><span className="eyebrow">DEVICE OVERVIEW</span><h1>设备总览</h1><span className="muted">截至 {data.asOf}</span></div>
      <div className="header-actions"><Link className="button" to="/loans">借测记录<ArrowRight size={16} /></Link><button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />新增设备</button></div></header>
    {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
    <div className="flow-metrics">
      {metrics.map(([key, label, caption, query]) => <Link key={key} to={key === 'monthRepair' ? '/repairs' : `/loans?${query}`} className="flow-metric"><span>{label}</span><strong>{data.counts[key] ?? 0}</strong><small>{caption}</small></Link>)}
    </div>
    <div className="prototype-dashboard-main">
      <section className="panel">
        <div className="section-heading"><div><h2>需要关注</h2><p>优先显示逾期和 7 天内即将到期的借测设备</p></div><Link to="/loans?status=overdue">查看全部</Link></div>
        <div className="attention-list">
          {attentionRemote.loading ? <PageLoading /> : attentionRemote.error ? <PageError message={attentionRemote.error} retry={attentionRemote.refresh} /> : attentionRemote.data?.items.map((row) => {
            const sn = row.items.map((item) => item.device.serialNumber || item.device.name).join(' / ')
            const model = row.items[0]?.device.cameraModel || '未登记型号'
            return <button key={row.id} className={`attention-card ${row.effectiveStatus === 'OVERDUE' ? 'attention-overdue' : ''}`} onClick={() => navigate(`/loans/${row.id}`)}>
              <div><strong>{row.organization.name} · {model}</strong><small>SN: {sn || '未关联设备'} · {row.loanNo}</small></div>
              <LoanBadge status={row.effectiveStatus} overdueDays={row.overdueDays} />
            </button>
          })}
          {!attentionRemote.loading && !attentionRemote.data?.items.length && <div className="empty-compact">暂无逾期或临期借测</div>}
        </div>
      </section>
      <aside className="prototype-operations">
        <section className="panel"><div className="section-heading"><div><h2>本月运营统计</h2></div></div><div className="prototype-ops-grid">
          <div className="ops-card"><span>本月归还</span><strong>{data.counts.monthReturned ?? 0}</strong></div>
          <div className="ops-card"><span>平均借测天数</span><strong>{data.averageDays != null ? `${data.averageDays} 天` : '—'}</strong></div>
          <div className="ops-card"><span>当前逾期</span><strong>{data.counts.overdue ?? 0}</strong></div>
          <div className="ops-card"><span>借测最多型号</span><strong>{data.modelRank[0]?.model || '—'}</strong></div>
        </div></section>
        <section className="panel"><div className="section-heading"><div><h2>本月借测型号分布</h2></div></div>
          {data.modelRank.map((rank) => <div className="prototype-rank" key={rank.model}><span>{rank.model}</span><div className="rank-track"><div className="rank-fill" style={{ width: `${Math.round((rank.count / (data.modelRank[0]?.count || 1)) * 100)}%` }} /></div><b>{rank.count} 台</b></div>)}
          {!data.modelRank.length && <div className="empty-compact">本月暂无借测</div>}
        </section>
      </aside>
    </div>
    <section className="panel">
      <div className="section-heading"><div><h2>最近流转</h2></div></div>
      <div className="table-wrap"><table className="recent-table"><thead><tr><th>类型</th><th>客户</th><th>设备</th><th>状态</th><th>时间</th></tr></thead><tbody>
        {recent.map((row) => <tr key={`${row.kind}-${row.id}`}>
          <td><strong>{row.kind === 'loan' ? '借测' : '维修'}</strong><div className="muted mono">{row.kind === 'loan' ? row.loanNo : row.no}</div></td>
          <td>{row.organization.name}</td>
          <td className="flow-sn">{row.kind === 'loan' ? <><strong>{row.items[0]?.device.cameraModel || '—'}</strong>{row.items.map((item, index) => <div key={index}>{item.device.serialNumber || item.device.name}</div>)}</> : <><strong>{row.model || '—'}</strong><div>{row.sn || '—'}</div></>}</td>
          <td><RecentStatus row={row} /></td>
          <td className="muted nowrap">{datetime(row.at)}</td>
        </tr>)}
        {!recent.length && <tr><td colSpan={5}><Empty text="暂无流转记录" /></td></tr>}
      </tbody></table></div>
    </section>
    {/* 设备台账：KPI 全部为设备表筛选卡，点击即过滤下方列表 */}
    <section className="metric-strip">{([
      ['', '设备总数', allDevices.length, Database, !status && !ownerType, resetFilters],
      ['IN_STOCK', '在库', countBy((item) => item.status === 'IN_STOCK'), Package, status === 'IN_STOCK', () => setStatus(status === 'IN_STOCK' ? '' : 'IN_STOCK')],
      ['LOANED', '借测中', countBy((item) => item.status === 'LOANED'), Handshake, status === 'LOANED', () => setStatus(status === 'LOANED' ? '' : 'LOANED')],
      ['REPAIRING', '返修中', countBy((item) => item.status === 'REPAIRING'), Wrench, status === 'REPAIRING', () => setStatus(status === 'REPAIRING' ? '' : 'REPAIRING')],
      ['RETIRED', '已报废', countBy((item) => item.status === 'RETIRED'), Trash2, status === 'RETIRED', () => setStatus(status === 'RETIRED' ? '' : 'RETIRED')],
      ['COMPANY', '公司样机', countBy((item) => item.ownerType === 'COMPANY'), Database, ownerType === 'COMPANY', () => setOwnerType(ownerType === 'COMPANY' ? '' : 'COMPANY')],
    ] as [string, string, number, typeof Cpu, boolean, () => void][]).map(([key, label, value, Icon, active, run]) => <button key={key} className={`metric clickable ${active ? 'filter-active' : ''}`} onClick={run} title={`筛选：${label}`}>
      <Icon size={17} /><span>{label}</span><strong>{value}</strong>
    </button>)}</section>
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
