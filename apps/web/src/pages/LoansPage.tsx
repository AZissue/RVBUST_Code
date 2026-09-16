import { ArrowLeft, ArrowRight, ChevronDown, ChevronRight, Download, Plus, RefreshCw, Search, X } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Fragment, useEffect, useState, type FormEvent } from 'react'
import { LoanOverdueNotice } from '../components/LoanOverdueNotice'
import { LoanPhotoPanel, uploadLoanPhoto } from '../components/LoanPhotos'
import { Modal } from '../components/Modal'
import { useRemote } from '../hooks/useRemote'
import { api, formatDate } from '../lib/api'
import { loanStatusLabels } from '../lib/labels'
import type { Device, LoanOrder, LoanScoreRule, LoanStatus, User } from '../types'
import { Empty, PageError, PageLoading } from './DashboardPage'
import './device-flow.css'

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

type Row = LoanOrder & { daysUntilDue: number | null; overdueDays: number; effectiveStatus: LoanStatus }
type Result = { items: Row[]; total: number; page: number; pageSize: number }

const date = (value: string | null | undefined) => value?.slice(0, 10) || '—'
const STATUS_FILTERS: [string, string][] = [['', '全部'], ['queued', '排队中'], ['ongoing', '借测中'], ['returned', '已归还'], ['overdue', '已逾期']]
const EFFECTIVE_LABELS: Record<string, string> = { ...loanStatusLabels, ONGOING: '借测中', OVERDUE: '已逾期' }

function Badge({ row }: { row: Row }) {
  const status = row.effectiveStatus
  return <span className={`badge flow-status flow-status-${status.toLowerCase()}`}>{EFFECTIVE_LABELS[status] || status}{row.overdueDays > 0 ? ` ${row.overdueDays} 天` : ''}</span>
}

export function LoansPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('search') || '')
  const [error, setError] = useState('')
  const [returning, setReturning] = useState<Row | null>(null)
  const [assigning, setAssigning] = useState<Row | null>(null)
  const [shipping, setShipping] = useState<Row | null>(null)
  const [advancing, setAdvancing] = useState<Row | null>(null)
  const [scoring, setScoring] = useState<Row | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const remote = useRemote(() => api<Result>(`/loans/list?${params}`), [params.toString()], true)
  useEffect(() => setSearch(params.get('search') || ''), [params])
  const change = (key: string, value: string) => setParams((old) => {
    const next = new URLSearchParams(old)
    value ? next.set(key, value) : next.delete(key)
    if (key !== 'page') next.delete('page')
    return next
  })
  const refresh = async () => remote.refresh()
  const run = async (action: () => Promise<unknown>) => { setError(''); try { await action(); await refresh() } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败') } }
  async function download() {
    setError('')
    try {
      const response = await fetch(`/api/loans/export?${params}`, { credentials: 'include' })
      if (!response.ok) throw new Error('导出失败，请缩小筛选范围后重试')
      const url = URL.createObjectURL(await response.blob()), anchor = document.createElement('a')
      anchor.href = url; anchor.download = '借测记录导出.xlsx'; anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (reason) { setError((reason as Error).message) }
  }
  const rows = remote.data?.items ?? []
  const isQueuedView = params.get('status') === 'queued'
  const taskView = params.get('status')
  return <div className="page-stack">
    <LoanOverdueNotice onReview={() => { setSearch(''); setParams({ status: 'overdue', sort: 'due_soon' }) }} />
    <header className="page-header"><div><span className="eyebrow">LOAN ORDERS</span><h1>借测管理</h1><p>借测需求先入队，完善信息后按评分排队，借出到归还全程可追踪。</p></div><div className="header-actions"><button className="button" onClick={() => void download()}><Download size={16} />导出数据</button><Link className="button primary" to="/loans/new"><Plus size={16} />新建借测工单</Link></div></header>
    {error && <div className="form-error"><button onClick={() => setError('')}><X size={14} /></button>{error}</div>}
    <form className="toolbar" onSubmit={(event) => { event.preventDefault(); change('search', search) }}>
      <div className="searchbox"><Search size={16} /><input aria-label="搜索借测记录" placeholder="单号、客户、SN、型号、物流单号或跟进内容" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
      <button className="button" type="submit">查询</button>
      <select aria-label="借测状态筛选" value={STATUS_FILTERS.some(([value]) => value === taskView) ? taskView! : ''} onChange={(event) => change('status', event.target.value)}>
        {STATUS_FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <input className="toolbar-month" type="month" aria-label="月份" value={params.get('month') || ''} onChange={(event) => change('month', event.target.value)} />
      <select aria-label="日期口径" value={params.get('dateField') || 'loaned'} onChange={(event) => change('dateField', event.target.value)}>
        <option value="loaned">借出月份</option>
        <option value="returned">归还月份</option>
      </select>
      <select aria-label="排序" value={params.get('sort') || ''} onChange={(event) => change('sort', event.target.value)}>
        <option value="">最近借出</option>
        <option value="due_soon">应还日期优先</option>
      </select>
      <label className="mine-toggle"><input type="checkbox" checked={params.get('mine') === '1'} onChange={(event) => change('mine', event.target.checked ? '1' : '')} />只看我的</label>
      <button className="icon-button" type="button" title="清除筛选" onClick={() => { setParams({}); setSearch('') }}><RefreshCw size={17} /></button>
    </form>
    {['due', 'stale', 'active'].includes(taskView || '') && <div className="flow-task-filter">任务视图：{{ due: '七天内到期', stale: '久未跟进', active: '未归还（含逾期）' }[taskView as 'due' | 'stale' | 'active']}<button className="button small" onClick={() => change('status', '')}>清除</button></div>}
    {remote.loading ? <PageLoading /> : remote.error ? <PageError message={remote.error} retry={refresh} /> : <>
      <section className="panel no-padding"><div className="table-wrap flow-table"><table><thead><tr><th></th><th>工单</th><th>设备</th><th>客户</th><th>物流</th><th>状态</th><th>最后跟进</th><th>操作</th></tr></thead><tbody>
        {rows.map((loan, index) => <Fragment key={loan.id}>
          <tr className={loan.effectiveStatus === 'OVERDUE' ? 'flow-overdue-row' : ''}>
            <td><button className="icon-button" onClick={() => setExpanded(expanded === loan.id ? null : loan.id)}>{expanded === loan.id ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button></td>
            <td><strong><Link to={`/loans/${loan.id}`}>{loan.loanNo}</Link></strong>{isQueuedView && <span className="badge warn" style={{ marginLeft: 6 }}>队列 #{(remote.data!.page - 1) * remote.data!.pageSize + index + 1}</span>}{loan.score != null && <span className="badge" style={{ marginLeft: 6 }}>评分 {loan.score}</span>}<div className="muted">借出 {date(loan.loanedAt)}</div><div className="muted">应还 {date(loan.dueAt)}</div></td>
            <td className="flow-sn">{loan.items.length ? <strong>{loan.items[0].device.cameraModel || loan.items[0].device.name}</strong> : <span className="placeholder-text">待借出登记</span>}{loan.items.map((item) => <div key={item.id}>{item.device.serialNumber || item.device.name}</div>)}</td>
            <td><strong>{loan.organization.name}</strong><div className="muted">{loan.contact?.name ?? '—'} {loan.contact?.phone ?? ''}</div><div className="muted">工程师：{loan.assignee?.name ?? '未指派'}</div></td>
            <td><div>寄出：{[loan.outboundCarrier, loan.outboundTracking].filter(Boolean).join(' ') || '—'}</div><div className="muted">归还：{[loan.returnCarrier, loan.returnTracking].filter(Boolean).join(' ') || '—'}</div></td>
            <td><Badge row={loan} /></td>
            <td className="flow-follow-summary">{loan.followUps?.length ? <><div>{loan.followUps[0].content}</div><small className="muted">{loan.followUps[0].author.name} · {date(loan.followUps[0].occurredAt)}</small></> : '—'}</td>
            <td><div className="row-actions">
              <button className="button small" onClick={() => navigate(`/loans/${loan.id}`)}>详情</button>
              {loan.status === 'QUEUED' && <button className="button small primary" onClick={() => setShipping(loan)}>借出</button>}
              {loan.status === 'QUEUED' && <button className="button small" onClick={() => setScoring(loan)}>评分</button>}
              {loan.status === 'QUEUED' && <button className="button small" onClick={() => setAdvancing(loan)}>提前</button>}
              {(loan.status === 'ONGOING' || loan.status === 'OVERDUE') && <button className="button small" onClick={() => setReturning(loan)}>归还</button>}
              {(loan.status === 'ONGOING' || loan.status === 'OVERDUE' || loan.status === 'QUEUED') && <button className="button small" onClick={() => setAssigning(loan)}>指派</button>}
              {(loan.status === 'ONGOING' || loan.status === 'OVERDUE' || loan.status === 'QUEUED') && <button className="button small" onClick={() => void run(() => api(`/loans/${loan.id}/cancel`, { method: 'POST' }))}>取消</button>}
            </div></td>
          </tr>
          {expanded === loan.id && <tr><td className="expanded-cell" colSpan={8}>
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
            {loan.items.length > 0 && <div className="table-wrap"><table><thead><tr><th>设备</th><th>SN</th><th>配件</th><th>归还状态</th><th>归还备注</th></tr></thead><tbody>{loan.items.map((item) => <tr key={item.id}><td>{item.device.name}</td><td className="mono">{item.device.serialNumber || '-'}</td><td>{(item as { accessories?: string }).accessories || '-'}</td><td>{item.returnedAt ? <span className="badge ok">已归还 {formatDate(item.returnedAt)}</span> : <span className="badge warn">未归还</span>}</td><td>{item.conditionNote || '-'}</td></tr>)}</tbody></table></div>}
            {loan.items.map((item) => <LoanPhotoPanel key={item.id} item={item} onChanged={refresh} />)}
            {(loan.status === 'QUEUED' || loan.status === 'ONGOING' || loan.status === 'OVERDUE') && <FollowUpPanel loan={loan} onChanged={refresh} />}
          </td></tr>}
        </Fragment>)}
      </tbody></table>{!rows.length && <Empty text="暂无借测单" />}</div></section>
      <footer className="flow-pager">
        <span>共 {remote.data?.total ?? 0} 条</span>
        <select aria-label="每页条数" value={remote.data?.pageSize ?? 20} onChange={(event) => change('pageSize', event.target.value)}>
          <option value="20">20 条 / 页</option><option value="30">30 条 / 页</option><option value="50">50 条 / 页</option>
        </select>
        <button className="icon-button" title="上一页" disabled={(remote.data?.page ?? 1) <= 1} onClick={() => change('page', String((remote.data?.page ?? 1) - 1))}><ArrowLeft size={18} /></button>
        <span>{remote.data?.page ?? 1} / {Math.max(1, Math.ceil((remote.data?.total ?? 0) / (remote.data?.pageSize ?? 20)))}</span>
        <button className="icon-button" title="下一页" disabled={(remote.data?.page ?? 1) * (remote.data?.pageSize ?? 20) >= (remote.data?.total ?? 0)} onClick={() => change('page', String((remote.data?.page ?? 1) + 1))}><ArrowRight size={18} /></button>
      </footer>
    </>}
    {shipping && <ShipLoanModal loan={shipping} onClose={() => setShipping(null)} onDone={async () => { setShipping(null); await refresh() }} />}
    {advancing && <AdvanceLoanModal loan={advancing} onClose={() => setAdvancing(null)} onDone={async () => { setAdvancing(null); await refresh() }} />}
    {scoring && <ScoreLoanModal loan={scoring} onClose={() => setScoring(null)} onDone={async () => { setScoring(null); await refresh() }} />}
    {returning && <ReturnLoanModal loan={returning} onClose={() => setReturning(null)} onDone={async () => { setReturning(null); await refresh() }} />}
    {assigning && <AssignLoanModal loan={assigning} onClose={() => setAssigning(null)} onDone={async () => { setAssigning(null); await refresh() }} />}
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
    <h3>跟进记录{loan.ticket ? <span className="placeholder-text">（同步写入关联工单时间线）</span> : null}</h3>
    {loan.followUps?.length ? <ol className="followup-list">{loan.followUps.map((item) => <li key={item.id}><header><strong>{item.author.name}</strong><time>{formatDate(item.occurredAt)}</time></header><p className="pre-wrap">{item.content}</p></li>)}</ol> : <p className="placeholder-text">暂无跟进记录</p>}
    <form className="followup-form" onSubmit={submit}>
      <textarea value={content} onChange={(event) => setContent(event.target.value)} rows={2} placeholder="记录跟进情况，仅内部可见" />
      <button className="button primary" disabled={busy || !content.trim()}>{busy ? '提交中' : '写入跟进'}</button>
    </form>
    {error && <div className="form-error">{error}</div>}
  </section>
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
  const [agreement, setAgreement] = useState<File | null>(null)
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
  const chooseAgreement = (file?: File) => {
    if (file && !(file.type === 'application/pdf' || ['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) ) { setError('借测协议仅支持 PDF 或 JPG、PNG、WebP 图片'); return }
    if (file && file.size > 10 * 1024 * 1024) { setError('协议文件不能超过 10 MB'); return }
    setError('')
    setAgreement(file ?? null)
  }
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (busy) return; setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '').trim()
    if (!selected.length && !manualList.length) { setError('请勾选在库样机，或在下方手动登记 SN'); setBusy(false); return }
    try {
      const shipped = await api<LoanOrder>(`/loans/${loan.id}/ship`, { method: 'POST', body: JSON.stringify({ deviceIds: selected, manualDevices: manualList.length ? manualList : undefined, loanedAt: value('loanedAt'), dueAt: value('dueAt'), agreementNo: value('agreementNo') || undefined, outboundCarrier: value('outboundCarrier') || undefined, outboundTracking: value('outboundTracking') || undefined }) })
      if (agreement && shipped.items.length) await uploadLoanPhoto(shipped.items[0].id, { key: crypto.randomUUID(), category: 'AGREEMENT', file: agreement, url: '' })
      await onDone()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '借出失败') } finally { setBusy(false) }
  }
  return <Modal title={`借出登记：${loan.loanNo}`} onClose={() => { if (!busy) onClose() }} wide><form onSubmit={submit}><fieldset className="form-grid" disabled={busy}>
    <label>借出日期<input name="loanedAt" type="date" required defaultValue={today} /></label>
    <label>预计归还日期<input name="dueAt" type="date" required defaultValue={defaultDue} /></label>
    <label>协议编号<input name="agreementNo" defaultValue={loan.agreementNo ?? ''} /></label>
    <label>借测协议（PDF/JPG/PNG/WebP，≤10MB）<input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={(event) => chooseAgreement(event.target.files?.[0])} />{agreement && <small className="placeholder-text">已选择：{agreement.name}</small>}</label>
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
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('')
    const reason = String(new FormData(event.currentTarget as HTMLFormElement).get('reason') ?? '').trim()
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
