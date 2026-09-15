import { AlarmClock, CalendarClock, CheckCircle2, ChevronDown, ChevronRight, Download, FileClock, ListOrdered, MessageSquarePlus, Plus, Search, Share2, X } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { Fragment, useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../context/AuthContext'
import { LoanPhotoPanel } from '../components/LoanPhotos'
import { Modal } from '../components/Modal'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { loanStatusLabels } from '../lib/labels'
import type { Contact, Customer, Device, LoanOrder, LoanScoreRule, LoanStatus, User } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'

export { loanStatusLabels }
export function LoanDueBadge({ days }: { days: number }) {
  if (days < 0) return <span className="badge danger">已逾期 {-days} 天</span>
  if (days === 0) return <span className="badge warn">今天到期</span>
  if (days <= 7) return <span className="badge warn">{days} 天后到期</span>
  return <span className="badge status-in_progress">借测中</span>
}
export function LoanStatusBadge({ status }: { status: LoanStatus }) {
  return <span className={`badge ${status === 'OVERDUE' ? 'danger' : status === 'ONGOING' ? 'status-in_progress' : status === 'RETURNED' ? 'ok' : status === 'QUEUED' ? 'warn' : ''}`}>{loanStatusLabels[status]}</span>
}

const CARRIERS = ['顺丰', '京东物流', '德邦', '中通', '圆通', '申通', '韵达', '极兔', 'EMS', '邮政', '跨越速运', '安能', '其他']

export function LoansPage() {
  const [params] = useSearchParams()
  const [status, setStatus] = useState(() => Object.keys(loanStatusLabels).includes(params.get('status') ?? '') ? params.get('status')! : '')
  const [mine, setMine] = useState(() => params.get('mine') === '1')
  const [creating, setCreating] = useState(false)
  const [returning, setReturning] = useState<LoanOrder | null>(null)
  const [assigning, setAssigning] = useState<LoanOrder | null>(null)
  const [shipping, setShipping] = useState<LoanOrder | null>(null)
  const [advancing, setAdvancing] = useState<LoanOrder | null>(null)
  const [scoring, setScoring] = useState<LoanOrder | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<'default' | 'dueAsc' | 'dueDesc'>('default')
  const [error, setError] = useState('')
  const { user } = useAuth()
  const remote = useRemote(() => api<LoanOrder[]>('/loans'), [], true)
  if (remote.loading) return <PageLoading />
  if (remote.error) return <PageError message={remote.error} retry={remote.refresh} />
  const dueState = (loan: LoanOrder) => loan.dueAt ? Math.ceil((new Date(loan.dueAt).getTime() - Date.now()) / 86400000) : Number.POSITIVE_INFINITY
  const allLoans = remote.data ?? []
  const activeLoans = allLoans.filter((loan) => loan.status === 'ONGOING' || loan.status === 'OVERDUE')
  const overdueLoans = activeLoans.filter((loan) => dueState(loan) < 0)
  const dueSoonLoans = activeLoans.filter((loan) => { const d = dueState(loan); return d >= 0 && d <= 7 })
  const queuedLoans = allLoans.filter((loan) => loan.status === 'QUEUED')
  // 排队位次动态计算：手动提前优先 → 评分降序（未评分最后）→ 先创建先服务
  const queueRank = new Map([...queuedLoans].sort((a, b) => {
    if (Boolean(a.advancedAt) !== Boolean(b.advancedAt)) return a.advancedAt ? -1 : 1
    if (a.advancedAt && b.advancedAt) return a.advancedAt < b.advancedAt ? -1 : 1
    if ((a.score ?? -1) !== (b.score ?? -1)) return (b.score ?? -1) - (a.score ?? -1)
    return a.createdAt < b.createdAt ? -1 : 1
  }).map((loan, index) => [loan.id, index + 1]))
  const loans = allLoans.filter((loan) => {
    if (mine && loan.assignee?.id !== user?.id) return false
    if (status === 'DUE_SOON') { const d = dueState(loan); if (!(loan.status === 'ONGOING' && d >= 0 && d <= 7)) return false }
    else if (status && loan.status !== status) return false
    if (!search.trim()) return true
    const haystack = `${loan.loanNo} ${loan.organization.name} ${loan.contact?.name ?? ''} ${loan.assignee?.name ?? ''} ${loan.items.map((item) => `${item.device.serialNumber ?? ''} ${item.device.name} ${item.device.cameraModel ?? ''}`).join(' ')} ${loan.agreementNo ?? ''}`.toLowerCase()
    return haystack.includes(search.trim().toLowerCase())
  })
  loans.sort((a, b) => {
    if (sort === 'dueAsc') return dueState(a) - dueState(b)
    if (sort === 'dueDesc') return dueState(b) - dueState(a)
    return 0
  })
  const run = async (action: () => Promise<unknown>) => { setError(''); try { await action(); await remote.refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败') } }
  const kpi = [
    { key: '', label: '全部借测单', value: allLoans.length, icon: FileClock, hint: '' },
    { key: 'QUEUED', label: '排队中', value: queuedLoans.length, icon: ListOrdered, hint: queuedLoans.filter((loan) => loan.score == null).length ? `${queuedLoans.filter((loan) => loan.score == null).length} 单待评分` : '' },
    { key: 'ONGOING', label: '借测中', value: activeLoans.length, icon: Share2, hint: `${activeLoans.reduce((sum, loan) => sum + loan.items.length, 0)} 台设备在借` },
    { key: 'OVERDUE', label: '已逾期', value: overdueLoans.length, icon: AlarmClock, hint: overdueLoans.length ? `最长逾期 ${Math.max(...overdueLoans.map((loan) => -dueState(loan)))} 天` : '' },
    { key: 'DUE_SOON', label: '7天内到期', value: dueSoonLoans.length, icon: CalendarClock, hint: '' },
    { key: 'RETURNED', label: '已归还', value: allLoans.filter((loan) => loan.status === 'RETURNED').length, icon: CheckCircle2, hint: '' },
  ]
  return <div className="page-stack">
    <header className="page-header"><div><span className="eyebrow">LOAN ORDERS</span><h1>借测管理</h1><p>借测需求先入队，完善信息后按评分排队，借出到归还全程可追踪。</p></div><div className="header-actions"><a className="button" href="/api/loans/export" download><Download size={16} />导出数据</a><button className="button primary" onClick={() => setCreating(true)}><Plus size={16} />入队登记</button></div></header>
    {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
    <section className="metric-strip">{kpi.map((item) => <button key={item.key} className={`metric clickable ${status === item.key ? 'filter-active' : ''}`} onClick={() => setStatus(status === item.key ? '' : item.key)} title={`筛选：${item.label}`}>
      <item.icon size={17} /><span>{item.label}</span><strong>{item.value}{item.hint ? <em> {item.hint}</em> : null}</strong>
    </button>)}</section>
    <section className="toolbar">
      <div className="searchbox"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索单号、客户、SN、型号或工程师" /></div>
      <select aria-label="借测状态筛选" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option><option value="QUEUED">排队中</option><option value="ONGOING">借测中</option><option value="OVERDUE">已逾期</option><option value="DUE_SOON">7天内到期</option><option value="RETURNED">已归还</option><option value="CANCELLED">已取消</option></select>
      <select aria-label="排序方式" value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}><option value="default">默认排序</option><option value="dueAsc">最近到期优先</option><option value="dueDesc">最远到期优先</option></select>
      <label><input type="checkbox" checked={mine} onChange={(event) => setMine(event.target.checked)} />只看我的</label>
      <span className="result-count">{loans.length} 张借测单</span>
    </section>
    <section className="panel no-padding"><div className="table-wrap"><table><thead><tr><th></th><th>单号</th><th>客户</th><th>设备（SN）</th><th>跟进工程师</th><th>评分</th><th>借出日期</th><th>预计归还</th><th>状态</th><th>操作</th></tr></thead><tbody>{loans.map((loan) => <Fragment key={loan.id}>
      <tr className={loan.status === 'OVERDUE' || (loan.status === 'ONGOING' && dueState(loan) < 0) ? 'danger-row' : ''}>
        <td><button className="icon-button" onClick={() => setExpanded(expanded === loan.id ? null : loan.id)}>{expanded === loan.id ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button></td>
        <td className="mono">{loan.loanNo}{loan.status === 'QUEUED' && <span className="badge warn" style={{ marginLeft: 6 }}>队列 #{queueRank.get(loan.id) ?? '-'}</span>}</td><td>{loan.organization.name}</td>
        <td className="mono truncate-cell">{loan.items.length ? loan.items.map((item) => item.device.serialNumber || item.device.name).join(', ') : '-'}</td>
        <td>{loan.assignee?.name ?? '未指派'}</td>
        <td>{loan.score != null ? <strong>{loan.score}</strong> : <span className="placeholder-text">未评分</span>}</td>
        <td>{formatDate(loan.loanedAt ?? undefined)}</td><td>{formatDate(loan.dueAt ?? undefined)}</td><td>{loan.status === 'ONGOING' ? <LoanDueBadge days={dueState(loan)} /> : <LoanStatusBadge status={loan.status} />}</td>
        <td><div className="row-actions">
          {loan.status === 'QUEUED' && <button className="button small primary" onClick={() => setShipping(loan)}>借出</button>}
          {loan.status === 'QUEUED' && <button className="button small" onClick={() => setScoring(loan)}>评分</button>}
          {loan.status === 'QUEUED' && <button className="button small" onClick={() => setAdvancing(loan)}>提前</button>}
          {(loan.status === 'ONGOING' || loan.status === 'OVERDUE') && <button className="button small" onClick={() => setReturning(loan)}>归还</button>}
          {(loan.status === 'ONGOING' || loan.status === 'OVERDUE' || loan.status === 'QUEUED') && <button className="button small" onClick={() => setAssigning(loan)}>指派</button>}
          {(loan.status === 'ONGOING' || loan.status === 'OVERDUE' || loan.status === 'QUEUED') && <button className="button small" onClick={() => void run(() => api(`/loans/${loan.id}/cancel`, { method: 'POST' }))}>取消</button>}
        </div></td>
      </tr>
      {expanded === loan.id && <tr><td className="expanded-cell" colSpan={10}>
        <dl className="detail-aside"><section><dl>
          <dt>借测目的</dt><dd className="pre-wrap">{loan.purpose}</dd>
          <dt>评估结论</dt><dd className="pre-wrap">{loan.assessmentResult || '-'}</dd>
          {loan.scoreDetail && <><dt>评分明细</dt><dd>{Object.entries(loan.scoreDetail).map(([key, value]) => <span key={key} className="badge" style={{ marginRight: 6 }}>{key}：{value}</span>)}</dd></>}
          {loan.advanceReason && <><dt>提前借测</dt><dd>{loan.advanceReason}（{loan.advancedBy?.name ?? '-'} · {formatDate(loan.advancedAt ?? undefined)}）</dd></>}
          {loan.ticket && <><dt>关联工单</dt><dd><a href={`/tickets/${loan.ticket.id}`}>{loan.ticket.number} {loan.ticket.title}</a></dd></>}
          <dt>协议编号</dt><dd>{loan.agreementNo || '-'}</dd>
          <dt>联系人</dt><dd>{loan.contact?.name ?? '-'}</dd>
          <dt>实际归还</dt><dd>{formatDate(loan.returnedAt ?? undefined)}</dd>
          <dt>备注</dt><dd className="pre-wrap">{loan.note || '-'}</dd>
        </dl></section></dl>
        {loan.items.length > 0 && <div className="table-wrap"><table><thead><tr><th>设备</th><th>SN</th><th>配件</th><th>归还状态</th><th>归还备注</th></tr></thead><tbody>{loan.items.map((item) => <tr key={item.id}><td>{item.device.name}</td><td className="mono">{item.device.serialNumber || '-'}</td><td>{item.accessories || '-'}</td><td>{item.returnedAt ? <span className="badge ok">已归还 {formatDate(item.returnedAt)}</span> : <span className="badge warn">未归还</span>}</td><td>{item.conditionNote || '-'}</td></tr>)}</tbody></table></div>}
        {loan.items.map(item => <LoanPhotoPanel key={item.id} item={item} onChanged={remote.refresh} />)}
        {(loan.status === 'QUEUED' || loan.status === 'ONGOING' || loan.status === 'OVERDUE') && <FollowUpPanel loan={loan} onChanged={remote.refresh} />}
      </td></tr>}
    </Fragment>)}</tbody></table>{!loans.length && <Empty text="暂无借测单" />}</div></section>
    {creating && <CreateLoanModal onClose={() => setCreating(false)} onCreated={async () => { setCreating(false); await remote.refresh() }} />}
    {shipping && <ShipLoanModal loan={shipping} onClose={() => setShipping(null)} onDone={async () => { setShipping(null); await remote.refresh() }} />}
    {advancing && <AdvanceLoanModal loan={advancing} onClose={() => setAdvancing(null)} onDone={async () => { setAdvancing(null); await remote.refresh() }} />}
    {scoring && <ScoreLoanModal loan={scoring} onClose={() => setScoring(null)} onDone={async () => { setScoring(null); await remote.refresh() }} />}
    {returning && <ReturnLoanModal loan={returning} onClose={() => setReturning(null)} onDone={async () => { setReturning(null); await remote.refresh() }} />}
    {assigning && <AssignLoanModal loan={assigning} onClose={() => setAssigning(null)} onDone={async () => { setAssigning(null); await remote.refresh() }} />}
  </div>
}

/** 跟进时间线：录入跟进并同步到关联工单（后端同事务写入工单时间线） */
function FollowUpPanel({ loan, onChanged }: { loan: LoanOrder; onChanged: () => Promise<unknown> }) {
  const [content, setContent] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!content.trim() || busy) return
    setBusy(true); setError('')
    try { await api(`/loans/${loan.id}/follow-ups`, { method: 'POST', body: JSON.stringify({ content: content.trim() }) }); setContent(''); await onChanged() }
    catch (reason) { setError(reason instanceof Error ? reason.message : '跟进记录失败') }
    finally { setBusy(false) }
  }
  return <section className="followup-panel">
    <h3><MessageSquarePlus size={15} /> 跟进记录{loan.ticket ? <span className="placeholder-text">（同步写入关联工单时间线）</span> : null}</h3>
    {loan.followUps?.length ? <ol className="followup-list">{loan.followUps.map((item) => <li key={item.id}><header><strong>{item.author.name}</strong><time>{formatDate(item.occurredAt)}</time></header><p className="pre-wrap">{item.content}</p></li>)}</ol> : <p className="placeholder-text">暂无跟进记录</p>}
    <form className="followup-form" onSubmit={submit}>
      <textarea value={content} onChange={(event) => setContent(event.target.value)} rows={2} placeholder="记录跟进情况，仅内部可见" />
      <button className="button primary" disabled={busy || !content.trim()}>{busy ? '提交中' : '写入跟进'}</button>
    </form>
    {error && <div className="form-error">{error}</div>}
  </section>
}

/** 入队登记：借测需求先入队，暂不要求设备与日期 */
function CreateLoanModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => Promise<void> }) {
  const customers = useRemote(() => api<Customer[]>('/customers'), [])
  const [organizationId, setOrganizationId] = useState('')
  const [contacts, setContacts] = useState<Contact[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!organizationId) { setContacts([]); return }
    void api<Customer>(`/customers/${organizationId}`).then((customer) => setContacts(customer.contacts ?? [])).catch(() => setContacts([]))
  }, [organizationId])
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (busy) return; setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '').trim()
    try {
      await api<LoanOrder>('/loans', { method: 'POST', body: JSON.stringify({ organizationId: value('organizationId'), contactId: value('contactId') || undefined, purpose: value('purpose'), assessmentResult: value('assessmentResult') || undefined, score: value('score') ? Number(value('score')) : undefined, agreementNo: value('agreementNo') || undefined, note: value('note') || undefined }) })
      await onCreated()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '创建失败') } finally { setBusy(false) }
  }
  return <Modal title="借测入队登记" onClose={() => { if (!busy) onClose() }}><form onSubmit={submit}><fieldset className="form-grid" disabled={busy}>
    <label>客户<select name="organizationId" required value={organizationId} onChange={(event) => setOrganizationId(event.target.value)}><option value="" disabled>选择客户</option>{customers.data?.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select></label>
    <label>联系人<select name="contactId" defaultValue=""><option value="">不指定</option>{contacts.map((contact) => <option key={contact.id} value={contact.id}>{contact.name}</option>)}</select></label>
    <label className="span-2">借测目的<textarea name="purpose" required rows={2} placeholder="客户应用场景、测试内容、期望周期" /></label>
    <label className="span-2">售前评估结论<textarea name="assessmentResult" rows={2} placeholder="需求评估、方案匹配度、是否建议借测" /></label>
    <label>初始评分（0-100，可后补）<input name="score" type="number" min={0} max={100} step={1} /></label>
    <label>协议编号<input name="agreementNo" /></label>
    <label className="span-2">备注<input name="note" /></label>
    <p className="span-2 placeholder-text">保存后进入借测队列，可在列表中补充评分、手动提前，信息完善后按评分排序安排借出。</p>
    </fieldset>
    {error && <div className="form-error">{error}</div>}
    <div className="form-actions"><button type="button" className="button" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '保存中' : '确认入队'}</button></div>
  </form></Modal>
}

/** 借出：排队单 → 进行中，选择在库公司样机或手动登记 SN（自动建档为公司样机） */
function ShipLoanModal({ loan, onClose, onDone }: { loan: LoanOrder; onClose: () => void; onDone: () => Promise<void> }) {
  const devices = useRemote(() => api<Device[]>('/devices?ownerType=COMPANY&status=IN_STOCK'), [])
  const [selected, setSelected] = useState<string[]>([])
  const [manualList, setManualList] = useState<{ serialNumber: string; cameraModel: string }[]>([])
  const [sn, setSn] = useState('')
  const [model, setModel] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const today = new Date().toISOString().slice(0, 10)
  const defaultDue = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10)
  const addManual = () => {
    const serialNumber = sn.trim()
    if (!serialNumber) return
    const duplicated = manualList.some((item) => item.serialNumber === serialNumber) || (devices.data ?? []).some((device) => device.serialNumber === serialNumber && selected.includes(device.id))
    if (duplicated) { setError(`SN ${serialNumber} 已在清单中`); return }
    setError('')
    setManualList((current) => [...current, { serialNumber, cameraModel: model.trim() }])
    setSn(''); setModel('')
  }
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (busy) return; setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '').trim()
    if (!selected.length && !manualList.length) { setError('请勾选在库样机，或在下方手动登记 SN'); setBusy(false); return }
    try {
      await api(`/loans/${loan.id}/ship`, { method: 'POST', body: JSON.stringify({ deviceIds: selected, manualDevices: manualList.length ? manualList : undefined, loanedAt: value('loanedAt'), dueAt: value('dueAt'), agreementNo: value('agreementNo') || undefined, outboundCarrier: value('outboundCarrier') || undefined, outboundTracking: value('outboundTracking') || undefined }) })
      await onDone()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '借出失败') } finally { setBusy(false) }
  }
  return <Modal title={`借出登记：${loan.loanNo}`} onClose={() => { if (!busy) onClose() }} wide><form onSubmit={submit}><fieldset className="form-grid" disabled={busy}>
    <label>借出日期<input name="loanedAt" type="date" required defaultValue={today} /></label>
    <label>预计归还日期<input name="dueAt" type="date" required defaultValue={defaultDue} /></label>
    <label>协议编号<input name="agreementNo" defaultValue={loan.agreementNo ?? ''} /></label>
    <label>承运商<select name="outboundCarrier" defaultValue=""><option value="">不填写</option>{CARRIERS.map((carrier) => <option key={carrier} value={carrier}>{carrier}</option>)}</select></label>
    <label>物流单号<input name="outboundTracking" /></label>
    <label className="span-2">在库公司样机（勾选借出）<div className="checkbox-list">{devices.data?.map((device) => <label key={device.id}><input type="checkbox" checked={selected.includes(device.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, device.id] : current.filter((id) => id !== device.id))} />{device.name}<span className="mono">{device.serialNumber || '-'}</span>{device.cameraModel ? ` · ${device.cameraModel}` : ''}</label>)}{devices.data && !devices.data.length && <span className="placeholder-text">暂无在库公司样机，可在下方手动登记 SN，保存后自动建档</span>}</div></label>
    <div className="span-2 manual-device-entry">
      <strong>手动登记新样机（SN 自动建档为公司样机）</strong>
      <div className="manual-device-inputs">
        <label>SN 码<input value={sn} onChange={(event) => setSn(event.target.value)} list="ship-device-sns" placeholder="输入或选择 SN，已建档的自动关联" /></label>
        <datalist id="ship-device-sns">{(devices.data ?? []).filter((device) => device.serialNumber).map((device) => <option key={device.id} value={device.serialNumber!}>{device.cameraModel || device.name}</option>)}</datalist>
        <label>相机型号<input value={model} onChange={(event) => setModel(event.target.value)} placeholder="如 M2600（选填）" /></label>
        <button type="button" className="button" onClick={addManual}><Plus size={14} />加入清单</button>
      </div>
      {manualList.length > 0 && <div className="manual-device-chips">{manualList.map((item) => <span key={item.serialNumber} className="badge">{item.cameraModel ? `${item.cameraModel} · ` : ''}{item.serialNumber}<button type="button" className="icon-button" aria-label={`移除 ${item.serialNumber}`} onClick={() => setManualList((current) => current.filter((entry) => entry.serialNumber !== item.serialNumber))}><X size={12} /></button></span>)}</div>}
    </div>
    </fieldset>
    {error && <div className="form-error">{error}</div>}
    <div className="form-actions"><button type="button" className="button" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '提交中' : '确认借出'}</button></div>
  </form></Modal>
}

/** 手动提前：必须填写提前原因，留痕操作人与时间 */
function AdvanceLoanModal({ loan, onClose, onDone }: { loan: LoanOrder; onClose: () => void; onDone: () => Promise<void> }) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const reason = String(new FormData(event.currentTarget).get('reason') ?? '').trim()
    try { await api(`/loans/${loan.id}/advance`, { method: 'POST', body: JSON.stringify({ reason }) }); await onDone() } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败') } finally { setBusy(false) }
  }
  return <Modal title={`提前借测：${loan.loanNo}`} onClose={onClose}><form className="form-grid" onSubmit={submit}>
    <p className="span-2 placeholder-text">将该需求提前到队首（优先于评分排序），需填写提前原因留痕。</p>
    <label className="span-2">提前原因<textarea name="reason" required rows={3} minLength={2} placeholder="例如：客户交付节点紧张，承诺本周提供样机实测" /></label>
    {error && <div className="form-error span-2">{error}</div>}
    <div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy}>{busy ? '提交中' : '确认提前'}</button></div>
  </form></Modal>
}

/** 评分：按当前启用规则逐维度打分，总分自动汇总，可重复完善 */
function ScoreLoanModal({ loan, onClose, onDone }: { loan: LoanOrder; onClose: () => void; onDone: () => Promise<void> }) {
  const rule = useRemote(() => api<LoanScoreRule>('/loans/score-rule'), [])
  const dimensions = Array.isArray(rule.data?.dimensions) ? rule.data!.dimensions as { key: string; label: string; weight: number; standard?: string }[] : []
  const [values, setValues] = useState<Record<string, number | undefined>>({})
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const total = dimensions.reduce((sum, dimension) => sum + Math.min(dimension.weight, Math.max(0, values[dimension.key] ?? 0)), 0)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (busy) return; setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const scoreDetail: Record<string, number> = {}
    for (const dimension of dimensions) { const v = values[dimension.key]; if (v != null) scoreDetail[dimension.key] = v }
    try {
      await api(`/loans/${loan.id}/score`, { method: 'POST', body: JSON.stringify({ score: total, scoreDetail, infoComplete: true, assessmentResult: String(form.get('assessmentResult') ?? '').trim() || undefined }) })
      await onDone()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '评分失败') } finally { setBusy(false) }
  }
  return <Modal title={`借测评分：${loan.loanNo}`} onClose={onClose} wide><form className="form-grid" onSubmit={submit}>
    {rule.loading && <p className="span-2 placeholder-text">评分规则加载中…</p>}
    {rule.error && <p className="span-2 form-error">{rule.error}</p>}
    {dimensions.map((dimension) => <label key={dimension.key}>{dimension.label}（满分 {dimension.weight}）<input type="number" min={0} max={dimension.weight} step={1} value={values[dimension.key] ?? ''} onChange={(event) => setValues((current) => ({ ...current, [dimension.key]: event.target.value === '' ? undefined : Number(event.target.value) }))} />{dimension.standard ? <small className="placeholder-text">{dimension.standard}</small> : null}</label>)}
    <p className="span-2">综合评分：<strong>{total}</strong> 分{loan.score != null ? `（当前 ${loan.score} 分，保存后更新）` : ''}</p>
    <label className="span-2">评估结论<textarea name="assessmentResult" rows={2} defaultValue={loan.assessmentResult ?? ''} /></label>
    {error && <div className="form-error span-2">{error}</div>}
    <div className="form-actions span-2"><button type="button" className="button" onClick={onClose}>取消</button><button className="button primary" disabled={busy || !!rule.error}>{busy ? '保存中' : '保存评分'}</button></div>
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
