import { ArrowLeft, Download, Pencil } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { LoanPhotoPanel } from '../components/LoanPhotos'
import { Modal } from '../components/Modal'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { loanStatusLabels } from '../lib/labels'
import type { Contact, Customer, LoanOrder, LoanStatus } from '../types'
import { PageError, PageLoading } from './DashboardPage'
import './device-flow.css'

const date = (value: string | null | undefined) => value?.slice(0, 10) || '—'
const ACTIVE: LoanStatus[] = ['ONGOING', 'OVERDUE']

function statusOf(loan: LoanOrder) {
  if (ACTIVE.includes(loan.status) && loan.dueAt) {
    const days = Math.round((+new Date(loan.dueAt) - +new Date(new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' }) + 'T00:00:00Z')) / 86400000)
    if (days < 0) return { status: 'OVERDUE' as LoanStatus, overdueDays: -days }
  }
  return { status: loan.status, overdueDays: 0 }
}

export function LoanDetailPage() {
  const { id } = useParams()
  const [editing, setEditing] = useState(false)
  const [content, setContent] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const remote = useRemote(() => api<LoanOrder>(`/loans/${id}`), [id])
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const loan = remote.data!
  const display = statusOf(loan)
  const label = loanStatusLabels[display.status] || (display.status === 'ONGOING' ? '借测中' : display.status)
  const agreements = loan.items.flatMap((item) => (item.attachments ?? []).filter((a) => a.photoCategory === 'AGREEMENT'))

  async function follow(event: FormEvent) {
    event.preventDefault()
    if (!content.trim() || busy) return
    setBusy(true); setError('')
    try { await api(`/loans/${loan.id}/follow-ups`, { method: 'POST', body: JSON.stringify({ content: content.trim() }) }); setContent(''); await remote.refresh() }
    catch (reason) { setError(reason instanceof Error ? reason.message : '跟进记录失败') }
    finally { setBusy(false) }
  }

  return <div className="page-stack flow-loan-detail">
    <header className="page-header">
      <div><Link to="/loans"><ArrowLeft size={16} />借测记录</Link>
        <h1>{loan.organization.name}</h1>
        <span className={`badge flow-status flow-status-${display.status.toLowerCase()}`}>{label}{display.overdueDays > 0 ? ` ${display.overdueDays} 天` : ''}</span></div>
      <button className="button" onClick={() => setEditing(true)}><Pencil size={15} />编辑档案</button>
    </header>
    <div className="flow-detail">
      <section><h2>设备与借测</h2>
        <dl className="flow-fields">
          {([
            ['工单号', loan.loanNo], ['型号', loan.items[0]?.device.cameraModel || '—'], ['客户', loan.organization.name],
            ['联系人', [loan.contact?.name, loan.contact?.phone].filter(Boolean).join(' · ') || '—'], ['跟进工程师', loan.assignee?.name ?? '未指派'],
            ['借出日期', date(loan.loanedAt)], ['预计归还', date(loan.dueAt)], ['实际归还', date(loan.returnedAt)],
            ['寄出物流', [loan.outboundCarrier, loan.outboundTracking].filter(Boolean).join(' ') || '—'],
            ['归还物流', [loan.returnCarrier, loan.returnTracking].filter(Boolean).join(' ') || '—'],
            ['协议编号', loan.agreementNo || '—'],
            ['借测目的', loan.purpose], ['评估结论', loan.assessmentResult || '—'], ['备注', loan.note || '—'],
          ] as [string, string][]).map(([key, value]) => (
            <div key={key} className={['借测目的', '评估结论', '备注'].includes(key) ? 'flow-field-wide' : undefined}><dt>{key}</dt><dd>{value || '—'}</dd></div>
          ))}
        </dl>
        {loan.items.length > 0 && <div className="table-wrap"><table><thead><tr><th>设备</th><th>SN</th><th>归还状态</th><th>归还备注</th></tr></thead><tbody>{loan.items.map((item) => <tr key={item.id}><td>{item.device.name}</td><td className="mono">{item.device.serialNumber || '-'}</td><td>{item.returnedAt ? <span className="badge ok">已归还 {date(item.returnedAt)}</span> : <span className="badge warn">未归还</span>}</td><td>{item.conditionNote || '-'}</td></tr>)}</tbody></table></div>}
      </section>
      <section><h2>跟进记录</h2>
        <form onSubmit={follow} className="flow-follow-form">
          <label>跟进内容<textarea required maxLength={2000} value={content} onChange={(event) => setContent(event.target.value)} /></label>
          <div className="button-row"><button className="button primary" disabled={busy || !content.trim()}>{busy ? '提交中' : '添加跟进'}</button></div>
        </form>
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="flow-timeline">
          {loan.followUps?.map((item) => <article key={item.id}><header><strong>{item.author.name}</strong><span className="muted">{formatDate(item.occurredAt)}</span></header><p>{item.content}</p></article>)}
          {!loan.followUps?.length && <div className="empty-compact">暂无跟进记录</div>}
        </div>
      </section>
    </div>
    <section><h2>借测协议</h2>
      {agreements.length ? <div className="prototype-photos">{agreements.map((attachment) => <article key={attachment.id}>
        <a className="button" href={`/api/files/${attachment.id}?preview=1`} target="_blank" rel="noreferrer">查看协议</a>
        <div className="flow-file-name">{attachment.originalName}</div>
        <a href={`/api/files/${attachment.id}`} className="button small"><Download size={14} />下载</a>
      </article>)}</div> : <div className="empty-compact">暂无协议文件</div>}
    </section>
    <section><h2>设备图片</h2>{loan.items.map((item) => <LoanPhotoPanel key={item.id} item={item} onChanged={remote.refresh} />)}</section>
    {editing && <EditLoanModal loan={loan} onClose={() => setEditing(false)} onSaved={async () => { setEditing(false); await remote.refresh() }} />}
  </div>
}

function EditLoanModal({ loan, onClose, onSaved }: { loan: LoanOrder; onClose: () => void; onSaved: () => Promise<void> }) {
  const contacts = useRemote(() => api<Customer>(`/customers/${loan.organization.id}`), [])
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (busy) return; setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '').trim()
    try {
      await api(`/loans/${loan.id}`, { method: 'PATCH', body: JSON.stringify({ purpose: value('purpose'), assessmentResult: value('assessmentResult') || undefined, agreementNo: value('agreementNo') || undefined, note: value('note') || undefined, contactId: value('contactId') || undefined, dueAt: value('dueAt') || undefined }) })
      await onSaved()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败') } finally { setBusy(false) }
  }
  return <Modal title={`编辑借测档案：${loan.loanNo}`} onClose={onClose} wide><form onSubmit={submit}>
    <div className="flow-edit">
      <label>客户<input defaultValue={loan.organization.name} disabled /></label>
      <label>联系人<select name="contactId" defaultValue={loan.contact?.id ?? ''}><option value="">不指定</option>{(contacts.data?.contacts ?? [] as Contact[]).map((contact) => <option key={contact.id} value={contact.id}>{contact.name}</option>)}</select></label>
      <label>借出日期<input type="date" defaultValue={loan.loanedAt?.slice(0, 10) ?? ''} disabled /></label>
      <label>预计归还<input name="dueAt" type="date" defaultValue={loan.dueAt?.slice(0, 10) ?? ''} /></label>
      <label>协议编号<input name="agreementNo" defaultValue={loan.agreementNo ?? ''} /></label>
      <label className="flow-field-wide">借测目的<textarea name="purpose" defaultValue={loan.purpose} /></label>
      <label className="flow-field-wide">评估结论<textarea name="assessmentResult" defaultValue={loan.assessmentResult ?? ''} /></label>
      <label className="flow-field-wide">备注<textarea name="note" defaultValue={loan.note ?? ''} /></label>
    </div>
    {error && <div className="form-error" role="alert">{error}</div>}
    <div className="button-row"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '保存中' : '保存'}</button></div>
  </form></Modal>
}
