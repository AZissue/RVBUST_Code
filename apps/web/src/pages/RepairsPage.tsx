import { Download, FileText, Plus, Upload, X } from 'lucide-react'
import { AttachmentPreview } from '../components/AttachmentPreview'
import { RepairStatusEditor } from '../components/RepairStatusEditor'
import { useAuth } from '../context/AuthContext'
import { useRef, useState, type FormEvent } from 'react'
import { ReturnRepairForm, downloadRepairPdf } from '../components/ReturnRepairForm'
import { Modal } from '../components/Modal'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { repairStatusLabels, statusChangeLabel, ticketEventTypeLabel } from '../lib/labels'
import type { Attachment, RepairOrder, RepairStatus, User } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

export { repairStatusLabels }
export function RepairStatusBadge({ status }: { status: RepairStatus }) {
  return <span className={`badge ${status === 'CLOSED' ? '' : status === 'SHIPPED' ? 'ok' : 'status-in_progress'}`}>{repairStatusLabels[status]}</span>
}
const nextStep: Partial<Record<RepairStatus, { status: RepairStatus; label: string }>> = {
  RECEIVED: { status: 'DIAGNOSING', label: '收货检测' },
  DIAGNOSING: { status: 'REPAIRING', label: '开始维修' },
  REPAIRING: { status: 'SHIPPED', label: '寄回' },
  SHIPPED: { status: 'CLOSED', label: '关闭' },
}

export function RepairsPage() {
  const [status, setStatus] = useState('')
  const [creating, setCreating] = useState(false)
  const [detailId, setDetailId] = useState<string | null>(null)
  const remote = useRemote(() => api<RepairOrder[]>(`/repairs${status ? `?status=${status}` : ''}`), [status], true)
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const repairs = remote.data ?? []
  return <div className="page-stack">
    <header className="page-header"><div><span className="eyebrow">REPAIR ORDERS</span><h1>返修管理</h1><p>从收货、检测、维修到寄回关闭的完整返修流水。</p></div><button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />新建返厂单</button></header>
    <section className="toolbar"><select aria-label="返修状态筛选" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option>{Object.entries(repairStatusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><span className="result-count">{repairs.length} 张返修单</span></section>
    <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th>单号</th><th>SN</th><th>型号</th><th>客户</th><th>故障现象</th><th>状态</th><th>跟进工程师</th><th>收货日期</th><th>操作</th></tr></thead><tbody>{repairs.map((repair) => <tr key={repair.id}>
      <td className="mono">{repair.repairNo}</td><td className="mono">{repair.serialNumber || repair.device?.serialNumber || '-'}</td><td>{repair.device?.cameraModel || '-'}</td><td>{repair.organization.name}</td><td className="truncate-cell" title={repair.symptom}>{repair.symptom}</td><td><RepairStatusBadge status={repair.status} /></td><td>{repair.assignee?.name ?? '未指派'}</td><td>{formatDate(repair.receivedAt)}</td>
      <td><button className="button small" onClick={() => setDetailId(repair.id)}>详情</button></td>
    </tr>)}</tbody></table>{!repairs.length && <Empty text="暂无返修单" />}</div></section>
    {creating && <ReturnRepairForm onClose={() => setCreating(false)} onSaved={async () => { setCreating(false); await remote.refresh() }} />}
    {detailId && <RepairDetailDrawer id={detailId} onClose={() => setDetailId(null)} onChanged={remote.refresh} />}
  </div>
}

function RepairDetailDrawer({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => Promise<void> }) {
  const { user } = useAuth()
  const canEdit = user?.role === 'admin' || user?.role === 'support'
  const detail = useRemote(() => api<RepairOrder>(`/repairs/${id}`), [id], true)
  const users = useRemote(() => api<User[]>('/users'), [])
  const fileInput = useRef<HTMLInputElement>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [shipping, setShipping] = useState(false)
  const [editingReturn, setEditingReturn] = useState(false)
  const [uploaded, setUploaded] = useState<Attachment[]>([])
  if (!detail.data) return <div className="drawer-backdrop" onClick={onClose}><aside className="drawer" onClick={(event) => event.stopPropagation()}><PageLoading /></aside></div>
  const repair = detail.data
  const refresh = async () => { await detail.refresh(); await onChanged() }
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '').trim()
    try { await api(`/repairs/${id}`, { method: 'PATCH', body: JSON.stringify({ faultCause: value('faultCause') || undefined, resolution: value('resolution') || undefined, trackingNo: value('trackingNo') || undefined, note: value('note') || undefined, inWarranty: value('inWarranty') ? value('inWarranty') === 'true' : undefined, contactId: value('contactId') || undefined }) }); await refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') } finally { setBusy(false) }
  }
  const transition = async (target: RepairStatus, trackingNo?: string) => { setError(''); try { await api(`/repairs/${id}/transition`, { method: 'POST', body: JSON.stringify({ status: target, trackingNo }) }); await refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '状态流转失败') } }
  const assign = async (assigneeId: string) => { setError(''); try { await api(`/repairs/${id}/assign`, { method: 'POST', body: JSON.stringify({ assigneeId }) }); await refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '指派失败') } }
  const upload = async (file: File) => { setError(''); try { const body = new FormData(); body.append('file', file); const attachment = await api<Attachment>(`/files/repairs/${id}`, { method: 'POST', body }); setUploaded((current) => [...current, attachment]); await refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '上传失败') } }
  const next = nextStep[repair.status]
  const attachments = [...new Map([...(repair.attachments ?? []), ...uploaded].map(item => [item.id, item])).values()]
  return <div className="drawer-backdrop" onClick={onClose}><aside className="drawer" onClick={(event) => event.stopPropagation()}>
    <header><div><span className="mono eyebrow">{repair.repairNo}</span><h2>{repair.device?.name ?? '手动登记设备'}（{repair.serialNumber || repair.device?.serialNumber || '无 SN'}）</h2><div className="inline-meta"><RepairStatusBadge status={repair.status} /><span>{repair.organization.name}</span><span>{repair.inWarranty == null ? '保修待判定' : repair.inWarranty ? '保内' : '保外'}</span></div></div><button className="icon-button" title="关闭" onClick={onClose}><X size={19} /></button></header>
    {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
    {canEdit && <RepairStatusEditor key={repair.status} repair={repair} onSaved={refresh} />}
    <div className="drawer-actions"><button className="button" onClick={() => setEditingReturn(true)} disabled={!canEdit}><FileText size={15} />填写返厂表单</button><button className="button primary" disabled={busy || !repair.returnForm} onClick={async () => { setBusy(true); setError(''); try { await downloadRepairPdf(id); await refresh() } catch (e) { setError(e instanceof Error ? e.message : '导出失败') } finally { setBusy(false) } }}><Download size={15} />生成 PDF</button></div>
    {editingReturn && <ReturnRepairForm repair={repair} onClose={() => setEditingReturn(false)} onSaved={async () => { setEditingReturn(false); await refresh() }} />}
    <section className="drawer-logs"><div className="section-heading"><div><h3>状态时间线</h3><p>{repair.events?.length ?? 0} 条记录</p></div></div><div className="timeline">{repair.events?.map((event) => <article key={event.id}><div className="timeline-dot" /><header><strong>{ticketEventTypeLabel(event.type)}</strong><time>{formatDate(event.createdAt)}</time></header><p>{event.type === 'STATUS_CHANGE' ? statusChangeLabel(event.content) : event.content}</p></article>)}{!repair.events?.length && <Empty text="暂无记录" />}</div></section>
    <form onSubmit={save} className="drawer-form">
      <label>跟进工程师<select name="assigneeId" value={repair.assignee?.id ?? ''} onChange={(event) => void assign(event.target.value)}><option value="" disabled>未指派</option>{users.data?.filter((item) => !item.status || item.status === 'ACTIVE').map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>故障原因<textarea name="faultCause" rows={2} defaultValue={repair.faultCause ?? ''} /></label>
      <label>处理结果<textarea name="resolution" rows={2} defaultValue={repair.resolution ?? ''} /></label>
      <div className="form-grid"><label>物流单号<input name="trackingNo" defaultValue={repair.trackingNo ?? ''} /></label><label>保内/保外<select name="inWarranty" defaultValue={repair.inWarranty == null ? '' : String(repair.inWarranty)}><option value="">待判定</option><option value="true">保内</option><option value="false">保外</option></select></label></div>
      <label>备注<textarea name="note" rows={2} defaultValue={repair.note ?? ''} /></label>
      <div className="drawer-actions"><button className="button primary" disabled={busy}>{busy ? '保存中' : '保存修改'}</button></div>
    </form>
    <section className="drawer-logs"><div className="section-heading"><div><h3>附件与返厂 PDF</h3><p>上传返修设备外观照片</p></div><button className="button small" onClick={() => fileInput.current?.click()}><Upload size={14} />上传</button></div>
      <input ref={fileInput} type="file" accept="image/*" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = '' }} />
      <div className="attachment-gallery">{attachments.map((item) => <AttachmentPreview key={item.id} item={item} />)}{!attachments.length && <Empty text="暂无图片" />}</div>
    </section>
    <footer>
      {next && (next.status === 'SHIPPED' ? <button className="button primary" onClick={() => setShipping(true)}>{next.label}</button> : <button className="button primary" onClick={() => void transition(next.status)}>{next.label}</button>)}
    </footer>
    {shipping && <ShipModal onClose={() => setShipping(false)} onDone={async (trackingNo) => { setShipping(false); await transition('SHIPPED', trackingNo) }} />}
  </aside></div>
}

function ShipModal({ onClose, onDone }: { onClose: () => void; onDone: (trackingNo: string) => Promise<void> }) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const trackingNo = String(new FormData(event.currentTarget).get('trackingNo') ?? '').trim()
    try { await onDone(trackingNo) } catch (reason) { setError(reason instanceof Error ? reason.message : '寄回失败') } finally { setBusy(false) }
  }
  return <Modal title="填写物流单号" onClose={onClose}><form className="form-grid" onSubmit={submit}>
    <label className="span-2">物流单号<input name="trackingNo" required autoFocus /></label>
    {error && <div className="form-error span-2">{error}</div>}
    <div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在提交' : '确认寄回'}</button></div>
  </form></Modal>
}
