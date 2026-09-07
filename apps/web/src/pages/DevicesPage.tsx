import { Cpu, Plus, Search, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Modal } from '../components/Modal'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import type { Customer, Device, DeviceStatus } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

const statusLabels: Record<DeviceStatus, string> = { IN_STOCK: '在库', LOANED: '借出', REPAIRING: '返修中', RETIRED: '已报废' }
export const deviceStatusLabels = statusLabels
export function DeviceStatusBadge({ status }: { status?: DeviceStatus }) {
  const value = status ?? 'IN_STOCK'
  return <span className={`badge ${value === 'IN_STOCK' ? 'ok' : value === 'REPAIRING' ? 'warn' : value === 'RETIRED' ? '' : 'status-in_progress'}`}>{statusLabels[value]}</span>
}

export function DevicesPage() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Device | null>(null)
  const [error, setError] = useState('')
  const remote = useRemote(() => api<Device[]>('/devices'), [], true)
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const devices = (remote.data ?? []).filter((item) => {
    const matches = `${item.name} ${item.cameraModel ?? ''} ${item.serialNumber ?? ''} ${item.organization?.name ?? ''}`.toLowerCase().includes(search.toLowerCase())
    return matches && (!status || item.status === status)
  })
  const changeStatus = async (item: Device, next: DeviceStatus) => { setError(''); try { await api(`/devices/${item.id}/status`, { method: 'PATCH', body: JSON.stringify({ status: next }) }); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '状态流转失败') } }
  return <div className="page-stack">
    <header className="page-header"><div><span className="eyebrow">DEVICE INVENTORY</span><h1>设备台账</h1><p>统一管理库存、借出、返修与报废设备。</p></div><button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />新增设备</button></header>
    {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
    <section className="toolbar"><div className="searchbox"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索名称、型号、SN 或客户" /></div><select aria-label="设备状态筛选" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><span className="result-count">{devices.length} 台设备</span></section>
    <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>名称</th><th>型号</th><th>SN</th><th>所属客户</th><th>状态</th><th>保修到期</th><th>操作</th></tr></thead><tbody>{devices.map((item) => <tr key={item.id}>
      <td><strong className="with-icon"><Cpu size={15} />{item.name}</strong></td><td>{item.cameraModel || item.product || '-'}</td><td className="mono">{item.serialNumber || '-'}</td><td>{item.organization?.name ?? '-'}</td><td><DeviceStatusBadge status={item.status} /></td><td>{formatDate(item.warrantyUntil)}</td>
      <td><div className="row-actions">
        <button className="button small" onClick={() => setEditing(item)}>编辑</button>
        {item.status !== 'LOANED' && <button className="button small" onClick={() => void changeStatus(item, 'LOANED')}>借出</button>}
        {item.status !== 'REPAIRING' && <button className="button small" onClick={() => void changeStatus(item, 'REPAIRING')}>返修</button>}
        {item.status !== 'IN_STOCK' && <button className="button small" onClick={() => void changeStatus(item, 'IN_STOCK')}>回库</button>}
        {item.status !== 'RETIRED' && <button className="button small" onClick={() => void changeStatus(item, 'RETIRED')}>报废</button>}
      </div></td>
    </tr>)}</tbody></table>{!devices.length && <Empty text="暂无设备" />}</div></section>
    {creating && <DeviceFormModal title="新增设备" onClose={() => setCreating(false)} onSubmit={async (payload) => { await api('/devices', { method: 'POST', body: JSON.stringify(payload) }); setCreating(false); await remote.refresh() }} />}
    {editing && <DeviceFormModal title={`编辑设备：${editing.name}`} initial={editing} onClose={() => setEditing(null)} onSubmit={async (payload) => { await api(`/devices/${editing.id}`, { method: 'PATCH', body: JSON.stringify(payload) }); setEditing(null); await remote.refresh() }} />}
  </div>
}

function DeviceFormModal({ title, initial, onClose, onSubmit }: { title: string; initial?: Device; onClose: () => void; onSubmit: (payload: Record<string, string>) => Promise<void> }) {
  const customers = useRemote(() => api<Customer[]>('/customers'), [])
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const payload = Object.fromEntries(['name', 'organizationId', 'product', 'cameraModel', 'serialNumber', 'location', 'purchaseDate', 'warrantyUntil', 'notes'].map((key) => [key, String(form.get(key) ?? '').trim()]).filter(([, value]) => value))
    try { await onSubmit(payload as Record<string, string>) } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') } finally { setBusy(false) }
  }
  return <Modal title={title} onClose={onClose} wide><form className="form-grid" onSubmit={submit}>
    <label>设备名称<input name="name" required defaultValue={initial?.name} /></label>
    <label>所属客户<select name="organizationId" required defaultValue={initial?.organizationId ?? ''}><option value="" disabled>选择客户</option>{customers.data?.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select></label>
    <label>产品<input name="product" defaultValue={initial?.product ?? ''} /></label>
    <label>相机型号<input name="cameraModel" defaultValue={initial?.cameraModel ?? ''} /></label>
    <label>序列号<input name="serialNumber" defaultValue={initial?.serialNumber ?? ''} /></label>
    <label>位置<input name="location" defaultValue={initial?.location ?? ''} /></label>
    <label>采购日期<input name="purchaseDate" type="date" defaultValue={initial?.purchaseDate?.slice(0, 10)} /></label>
    <label>保修到期<input name="warrantyUntil" type="date" defaultValue={initial?.warrantyUntil?.slice(0, 10)} /></label>
    <label className="span-2">备注<textarea name="notes" rows={3} defaultValue={initial?.notes ?? ''} /></label>
    {error && <div className="form-error span-2">{error}</div>}
    <div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在保存' : '保存'}</button></div>
  </form></Modal>
}
