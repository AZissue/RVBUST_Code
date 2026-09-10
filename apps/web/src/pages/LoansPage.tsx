import { ChevronDown, ChevronRight, Plus, X } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { Fragment, useEffect, useRef, useState, type FormEvent } from 'react'
import { LoanPhotoPanel, PhotoPicker, uploadLoanPhoto, type PendingPhoto } from '../components/LoanPhotos'
import { Modal } from '../components/Modal'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { loanStatusLabels, deviceOwnerLabel } from '../lib/labels'
import type { Contact, Customer, Device, LoanOrder, LoanStatus, User } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

export { loanStatusLabels }
export function LoanStatusBadge({ status }: { status: LoanStatus }) {
  return <span className={`badge ${status === 'OVERDUE' ? 'danger' : status === 'ONGOING' ? 'status-in_progress' : status === 'RETURNED' ? 'ok' : ''}`}>{loanStatusLabels[status]}</span>
}

export function LoansPage() {
  const [params] = useSearchParams()
  const [status, setStatus] = useState(() => Object.keys(loanStatusLabels).includes(params.get('status') ?? '') ? params.get('status')! : '')
  const [mine, setMine] = useState(() => params.get('mine') === '1')
  const [creating, setCreating] = useState(false)
  const [returning, setReturning] = useState<LoanOrder | null>(null)
  const [assigning, setAssigning] = useState<LoanOrder | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [error, setError] = useState('')
  const remote = useRemote(() => api<LoanOrder[]>(`/loans?${status ? `status=${status}&` : ''}${mine ? 'mine=1' : ''}`), [status, mine], true)
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const loans = remote.data ?? []
  const run = async (action: () => Promise<unknown>) => { setError(''); try { await action(); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败') } }
  return <div className="page-stack">
    <header className="page-header"><div><span className="eyebrow">LOAN ORDERS</span><h1>借测管理</h1><p>设备借测从借出到归还全程可追踪。</p></div><button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />新建借测单</button></header>
    {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
    <section className="toolbar">
      <select aria-label="借测状态筛选" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option>{Object.entries(loanStatusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      <label><input type="checkbox" checked={mine} onChange={(event) => setMine(event.target.checked)} />只看我的</label>
      <span className="result-count">{loans.length} 张借测单</span>
    </section>
    <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th></th><th>单号</th><th>客户</th><th>设备（SN）</th><th>跟进工程师</th><th>借出日期</th><th>预计归还</th><th>状态</th><th>操作</th></tr></thead><tbody>{loans.map((loan) => <Fragment key={loan.id}>
      <tr className={loan.status === 'OVERDUE' ? 'danger-row' : ''}>
        <td><button className="icon-button" onClick={() => setExpanded(expanded === loan.id ? null : loan.id)}>{expanded === loan.id ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button></td>
        <td className="mono">{loan.loanNo}</td><td>{loan.organization.name}</td>
        <td className="mono truncate-cell">{loan.items.map((item) => item.device.serialNumber || item.device.name).join(', ')}</td>
        <td>{loan.assignee?.name ?? '未指派'}</td><td>{formatDate(loan.loanedAt)}</td><td>{formatDate(loan.dueAt)}</td><td><LoanStatusBadge status={loan.status} /></td>
        <td>{(loan.status === 'ONGOING' || loan.status === 'OVERDUE') && <div className="row-actions"><button className="button small" onClick={() => setReturning(loan)}>归还</button><button className="button small" onClick={() => setAssigning(loan)}>指派</button><button className="button small" onClick={() => void run(() => api(`/loans/${loan.id}/cancel`, { method: 'POST' }))}>取消</button></div>}</td>
      </tr>
      {expanded === loan.id && <tr><td className="expanded-cell" colSpan={9}>
        <dl className="detail-aside"><section><dl>
          <dt>借测目的</dt><dd className="pre-wrap">{loan.purpose}</dd>
          <dt>协议编号</dt><dd>{loan.agreementNo || '-'}</dd>
          <dt>联系人</dt><dd>{loan.contact?.name ?? '-'}</dd>
          <dt>实际归还</dt><dd>{formatDate(loan.returnedAt ?? undefined)}</dd>
          <dt>备注</dt><dd className="pre-wrap">{loan.note || '-'}</dd>
        </dl></section></dl>
        <div className="table-wrap"><table><thead><tr><th>设备</th><th>SN</th><th>归还状态</th><th>归还备注</th></tr></thead><tbody>{loan.items.map((item) => <tr key={item.id}><td>{item.device.name}</td><td className="mono">{item.device.serialNumber || '-'}</td><td>{item.returnedAt ? <span className="badge ok">已归还 {formatDate(item.returnedAt)}</span> : <span className="badge warn">未归还</span>}</td><td>{item.conditionNote || '-'}</td></tr>)}</tbody></table></div>
        {loan.items.map(item => <LoanPhotoPanel key={item.id} item={item} onChanged={remote.refresh} />)}
      </td></tr>}
    </Fragment>)}</tbody></table>{!loans.length && <Empty text="暂无借测单" />}</div></section>
    {creating && <CreateLoanModal onClose={() => setCreating(false)} onCreated={async () => { setCreating(false); await remote.refresh() }} />}
    {returning && <ReturnLoanModal loan={returning} onClose={() => setReturning(null)} onDone={async () => { setReturning(null); await remote.refresh() }} />}
    {assigning && <AssignLoanModal loan={assigning} onClose={() => setAssigning(null)} onDone={async () => { setAssigning(null); await remote.refresh() }} />}
  </div>
}

function CreateLoanModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => Promise<void> }) {
  const customers = useRemote(() => api<Customer[]>('/customers'), [])
  const [organizationId, setOrganizationId] = useState('')
  const [contacts, setContacts] = useState<Contact[]>([])
  const [devices, setDevices] = useState<Device[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [photos, setPhotos] = useState<Record<string, PendingPhoto[]>>({})
  const created = useRef<LoanOrder | null>(null)
  const lock = useRef(false)
  const completed = useRef(new Set<string>())
  const urls = useRef<string[]>([])
  useEffect(() => () => urls.current.forEach(url => URL.revokeObjectURL(url)), [])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!organizationId) { setContacts([]); setDevices([]); return }
    void api<Customer>(`/customers/${organizationId}`).then((customer) => setContacts(customer.contacts ?? [])).catch(() => setContacts([]))
    // 可借设备 = 该客户名下在库客户资产（防御，理论上借测只面向公司样机）+ 全库在库公司样机
    void Promise.all([
      api<Device[]>(`/devices?organizationId=${organizationId}&status=IN_STOCK`),
      api<Device[]>(`/devices?ownerType=COMPANY&status=IN_STOCK`),
    ]).then(([customerDevices, companyDevices]) => {
      const merged = new Map<string, Device>()
      for (const device of [...customerDevices, ...companyDevices]) merged.set(device.id, device)
      setDevices([...merged.values()])
    }).catch(() => setDevices([]))
    setSelected([])
  }, [organizationId])
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '').trim()
    if (!selected.length) { setError('请至少选择一台设备'); setBusy(false); lock.current = false; return }
    try {
      if (!created.current) created.current = await api<LoanOrder>('/loans', { method: 'POST', body: JSON.stringify({ organizationId: value('organizationId'), contactId: value('contactId') || undefined, purpose: value('purpose'), loanedAt: value('loanedAt'), dueAt: value('dueAt'), agreementNo: value('agreementNo') || undefined, note: value('note') || undefined, deviceIds: selected }) })
      for (const item of created.current!.items) {
        for (const photo of photos[item.device.id] ?? []) {
          if (!completed.current.has(photo.key)) { await uploadLoanPhoto(item.id, photo); completed.current.add(photo.key) }
        }
      }
      await onCreated()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '创建失败') } finally { setBusy(false); lock.current = false }
  }
  return <Modal title="新建借测单" onClose={() => { if (!busy) onClose() }} wide><form onSubmit={submit}><fieldset className="return-form-fields form-grid" disabled={busy || Boolean(created.current)}>
    <label>客户<select name="organizationId" required value={organizationId} onChange={(event) => setOrganizationId(event.target.value)}><option value="" disabled>选择客户</option>{customers.data?.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select></label>
    <label>联系人<select name="contactId" defaultValue=""><option value="">不指定</option>{contacts.map((contact) => <option key={contact.id} value={contact.id}>{contact.name}</option>)}</select></label>
    <label>借出日期<input name="loanedAt" type="date" required /></label>
    <label>预计归还日期<input name="dueAt" type="date" required /></label>
    <label className="span-2">借测目的<textarea name="purpose" required rows={2} /></label>
    <label>协议编号<input name="agreementNo" /></label>
    <label>备注<input name="note" /></label>
    <label className="span-2">可借设备（勾选借出）<div className="checkbox-list">{devices.map((device) => <label key={device.id}><input type="checkbox" checked={selected.includes(device.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, device.id] : current.filter((id) => id !== device.id))} />{device.name}<span className="mono">{device.serialNumber || '-'}</span>{device.cameraModel ? ` · ${device.cameraModel}` : ''} · {deviceOwnerLabel(device.ownerType)}</label>)}{organizationId && !devices.length && <span className="placeholder-text">暂无可借设备（需要在库公司样机）</span>}{!organizationId && <span className="placeholder-text">请先选择客户</span>}</div></label>
    {selected.map(id => <section className="span-2 loan-device-photos" key={id}><h3>{devices.find(d => d.id === id)?.name} · {devices.find(d => d.id === id)?.serialNumber}</h3><PhotoPicker value={photos[id] ?? []} onChange={next => { urls.current.push(...next.map(p => p.url)); setPhotos(current => ({ ...current, [id]: next })) }} disabled={busy || Boolean(created.current)} /></section>)}
    </fieldset>
    {created.current && <p className="success-text">借测单 {created.current.loanNo} 已保存，照片上传失败时可重试。</p>}
    {error && <div className="form-error">{error}</div>}
    <div className="form-actions"><button type="button" className="button" disabled={busy} onClick={onClose}>关闭</button><button className="button primary" disabled={busy}>{busy ? '保存中' : created.current ? '重试剩余照片' : '确认创建'}</button></div>
  </form></Modal>
}

function ReturnLoanModal({ loan, onClose, onDone }: { loan: LoanOrder; onClose: () => void; onDone: () => Promise<void> }) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const pending = loan.items.filter((item) => !item.returnedAt)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const items = pending.map((item) => ({ deviceId: item.device.id, conditionNote: String(form.get(`note-${item.id}`) ?? '').trim() || undefined }))
    try { await api(`/loans/${loan.id}/return`, { method: 'POST', body: JSON.stringify({ items }) }); await onDone() } catch (reason) { setError(reason instanceof Error ? reason.message : '归还失败') } finally { setBusy(false) }
  }
  return <Modal title={`归还登记：${loan.loanNo}`} onClose={onClose}><form className="form-grid" onSubmit={submit}>
    {pending.map((item) => <label className="span-2" key={item.id}>{item.device.name}（{item.device.serialNumber || '无 SN'}）归还备注<input name={`note-${item.id}`} placeholder="设备外观/功能状况" /></label>)}
    {!pending.length && <p className="span-2 placeholder-text">全部设备均已归还</p>}
    {error && <div className="form-error span-2">{error}</div>}
    <div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy || !pending.length}>{busy ? '正在提交' : '确认归还'}</button></div>
  </form></Modal>
}

function AssignLoanModal({ loan, onClose, onDone }: { loan: LoanOrder; onClose: () => void; onDone: () => Promise<void> }) {
  const users = useRemote(() => api<User[]>('/users'), [])
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const assigneeId = String(new FormData(event.currentTarget).get('assigneeId') ?? '')
    try { await api(`/loans/${loan.id}/assign`, { method: 'POST', body: JSON.stringify({ assigneeId }) }); await onDone() } catch (reason) { setError(reason instanceof Error ? reason.message : '指派失败') } finally { setBusy(false) }
  }
  return <Modal title={`指派工程师：${loan.loanNo}`} onClose={onClose}><form className="form-grid" onSubmit={submit}>
    <label className="span-2">跟进工程师<select name="assigneeId" required defaultValue={loan.assignee?.id ?? ''}><option value="" disabled>选择工程师</option>{users.data?.filter((item) => !item.status || item.status === 'ACTIVE').map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    {error && <div className="form-error span-2">{error}</div>}
    <div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '正在指派' : '确认指派'}</button></div>
  </form></Modal>
}
