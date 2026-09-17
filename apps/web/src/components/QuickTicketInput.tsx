import { Plus, Sparkles, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api, formatDate } from '../lib/api'
import { ticketCategoryLabels, ticketPriorityLabels, ticketStatusLabels } from '../lib/labels'
import type { Customer, Device, Ticket, TicketCategory, TicketPriority, TicketStatus } from '../types'
import { Modal } from './Modal'
import { StatusBadge } from './Status'
import { SimpleFormModal } from '../pages/CustomersPage'

interface Candidate { id: string; name: string; score: number }
type Similar = Ticket & { similarity: number }
interface Parsed {
  parser?: 'rule'; fallbackReason?: string
  rawText: string; issue: string; title: string; priority: TicketPriority; deviceText: string
  matchedCustomer: Candidate | null; customerCandidates: Candidate[]; customerText: string
  matchedAssignee: Candidate | null; assigneeCandidates: Candidate[]; assigneeText: string; assigneeDefaulted: boolean
  matchedDevice: Device | null
  /** 解析时一并返回的相似工单（无该字段时回退到确认页内的防抖查询） */
  similarTickets?: Similar[]
  /** 解析出的工单时间（本地日期 YYYY-MM-DD），null 表示当天 */
  occurredAt: string | null
  /** 解析出的初始状态（已解决/处理中/等待客户等），null 表示待处理 */
  status: TicketStatus | null
}

/** 快速记录按关键词推断问题分类枚举（与后端 TicketCategory 对应） */
const CATEGORY_KEYWORDS: Array<[TicketCategory, readonly string[]]> = [
  ['PRE_SALES', ['售前', '选型', '报价', '购买']],
  ['LOAN_REQUEST', ['借测', '试用']],
  ['TRAINING', ['培训', '教程', '教学']],
  ['POINTCLOUD_DEBUG', ['点云', '拍摄', '无点云', '深度图', '标定数据']],
  ['SDK_DEVELOPMENT', ['sdk', 'api', '接口', '开发', '代码', '调试程序']],
  ['HAND_EYE_CALIBRATION', ['手眼', '标定', 'eye-to-hand', 'eye-in-hand']],
  ['HARDWARE_FAILURE', ['硬件', '故障', '维修', '损坏', '连不上', '超时', '掉线']],
]
const inferCategory = (text: string): TicketCategory => {
  const lower = text.toLocaleLowerCase()
  for (const [category, keywords] of CATEGORY_KEYWORDS) if (keywords.some((keyword) => lower.includes(keyword))) return category
  return 'OTHER'
}

export function QuickTicketInput({ embedded = false, heading = '快速记录', defaultDate, onSaved }: { embedded?: boolean; heading?: string; defaultDate?: string; onSaved?: (ticket: Ticket, updated: boolean, notice?: string) => void }) {
  const { user } = useAuth()
  const [rawText, setRawText] = useState('')
  const [parsed, setParsed] = useState<Parsed | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState<{ ticket: Ticket; updated: boolean; notice?: string } | null>(null)
  const parse = async () => {
    setBusy(true); setError(''); setSuccess(null)
    try { setParsed(await api<Parsed>('/tickets/quick/parse', { method: 'POST', body: JSON.stringify({ rawText }) })) }
    catch (e) { setError(e instanceof Error ? e.message : '解析失败') } finally { setBusy(false) }
  }
  const canParse = !busy && rawText.trim().length >= 3
  const inner = <>{!embedded && <div className="section-heading"><h2>{heading}</h2></div>}
    <textarea aria-label="快速工单输入" maxLength={4000} value={rawText} onChange={(e) => setRawText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (canParse) void parse() } }} rows={7} placeholder={'开头可写工单时间补录历史单：0907 / 本周一 / 9月7日 / 昨天，可带状态：已解决 / 处理中 / 等待客户反馈\n浙江智享机器人 M2600拍摄3D无点云，负责人张伟，紧急'} />
    {error && <div role="alert" className="form-error">{error}</div>}
    <button className="button primary" disabled={!canParse} onClick={() => void parse()}><Plus size={15} />{busy ? '正在解析' : '智能解析'}</button>
    {success && <div className="quick-success" role="status">工单 {success.ticket.number} {success.updated ? '更新' : '创建'}成功{success.notice ? ` · ${success.notice}` : ''} <Link to={`/tickets/${success.ticket.id}`}>查看工单</Link></div>}
    {parsed && <QuickTicketConfirm parsed={parsed} defaultDate={defaultDate} canCreateCustomer={user?.role === 'admin' || user?.role === 'support'} onClose={() => setParsed(null)} onSaved={(ticket, updated, notice) => { setSuccess({ ticket, updated, notice }); setParsed(null); setRawText(''); onSaved?.(ticket, updated, notice) }} />}
  </>
  if (embedded) return <div className="quick-capture-embedded">{inner}</div>
  return <section className="workspace-section quick-capture-panel">{inner}</section>
}

function QuickTicketConfirm({ parsed, defaultDate, canCreateCustomer, onClose, onSaved }: { parsed: Parsed; defaultDate?: string; canCreateCustomer: boolean; onClose: () => void; onSaved: (ticket: Ticket, updated: boolean, notice?: string) => void }) {
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
  const [date, setDate] = useState(parsed.occurredAt ?? defaultDate ?? '')
  const [status, setStatus] = useState<TicketStatus>(parsed.status ?? 'PENDING')
  const [category, setCategory] = useState<TicketCategory>(() => inferCategory(parsed.rawText))
  const [linkageDefaults, setLinkageDefaults] = useState({ loan: false, repair: false })
  const [createLinkedLoan, setCreateLinkedLoan] = useState(false)
  const [createLinkedRepair, setCreateLinkedRepair] = useState(false)
  const [similar, setSimilar] = useState<Similar[]>([])
  const [checkedKey, setCheckedKey] = useState('')
  const [error, setError] = useState('')
  const [lookupError, setLookupError] = useState('')
  const [busy, setBusy] = useState(false)
  const [summarizing, setSummarizing] = useState(false)
  const [creatingCustomer, setCreatingCustomer] = useState(false)
  const [retry, setRetry] = useState(0)
  const [dismissedDup, setDismissedDup] = useState(false)
  const [showCompare, setShowCompare] = useState(false)
  const [requestKey] = useState(() => crypto.randomUUID())
  const containerRef = useRef<HTMLDivElement>(null)
  const key = JSON.stringify([organizationId, issue, model])
  useEffect(() => { containerRef.current?.focus() }, [])
  useEffect(() => {
    let current = true
    Promise.all([api<Customer[]>('/customers'), api<Array<{ id: string; name: string }>>('/users/assignable')]).then(([c, u]) => { if (current) { setCustomers(c); setUsers(u) } }).catch((e: Error) => { if (current) setError(e.message) })
    return () => { current = false }
  }, [retry])
  // 联动默认配置（管理员在系统设置维护），接口失败时静默回落 false
  useEffect(() => {
    let current = true
    api<{ defaultCreate: { loan: boolean; repair: boolean } }>('/system/linkage-config')
      .then(config => { if (current) setLinkageDefaults({ loan: Boolean(config.defaultCreate?.loan), repair: Boolean(config.defaultCreate?.repair) }) })
      .catch(() => { /* 静默回落默认 false */ })
    return () => { current = false }
  }, [])
  // 默认配置加载完成后按当前分类应用默认勾选（与创建工单弹窗一致）；用户手动改过的勾选不覆盖
  useEffect(() => {
    setCreateLinkedLoan(previous => previous || ((category === 'PRE_SALES' || category === 'LOAN_REQUEST') && linkageDefaults.loan))
    setCreateLinkedRepair(previous => previous || (category === 'HARDWARE_FAILURE' && linkageDefaults.repair))
  }, [category, linkageDefaults])
  const changeCategory = (value: TicketCategory) => { setCategory(value); setCreateLinkedLoan((value === 'PRE_SALES' || value === 'LOAN_REQUEST') && linkageDefaults.loan); setCreateLinkedRepair(value === 'HARDWARE_FAILURE' && linkageDefaults.repair) }
  useEffect(() => {
    let current = true
    setDevices([])
    if (organizationId) void api<Customer>(`/customers/${organizationId}`).then((c) => { if (current) setDevices(c.devices ?? []) }).catch((e: Error) => { if (current) setError(e.message) })
    return () => { current = false }
  }, [organizationId, retry])
  useEffect(() => {
    let current = true
    setLookupError('')
    // 600ms 防抖；重查期间保留旧列表不清空，避免输入过程 UI 跳动
    const timer = window.setTimeout(() => {
      if (!organizationId || !issue.trim()) { if (current) { setSimilar([]); setCheckedKey(key) } return }
      void api<Similar[]>('/tickets/quick/similar', { method: 'POST', body: JSON.stringify({ organizationId, issue, cameraModel: model }) }).then((items) => { if (current) { setSimilar(items); setCheckedKey(key) } }).catch((e: Error) => { if (current) setLookupError(e.message) })
    }, 600)
    return () => { current = false; window.clearTimeout(timer) }
  }, [organizationId, issue, model, retry, key])
  const createCustomer = async () => {
    const name = parsed.customerText?.trim()
    if (!name) { setCreatingCustomer(true); return }
    setBusy(true); setError('')
    try {
      const c = await api<Customer>('/customers', { method: 'POST', body: JSON.stringify({ name }) })
      setCustomers((list) => [...list, c]); setOrganizationId(c.id); setDeviceId('')
    } catch (e) { setError(e instanceof Error ? e.message : '创建客户失败') } finally { setBusy(false) }
  }
  const suggestTitle = async () => {
    const description = issue.trim() || parsed.rawText.trim()
    if (description.length < 3) return
    setSummarizing(true); setError('')
    try {
      const result = await api<{ title: string }>('/tickets/suggest-title', { method: 'POST', body: JSON.stringify({ description: description.slice(0, 4000) }) })
      setTitle(result.title.slice(0, 240))
    } catch (e) { setError(e instanceof Error ? e.message : '总结失败') } finally { setSummarizing(false) }
  }
  const ready = Boolean(organizationId && assigneeId && issue.trim().length >= 3 && title.trim().length >= 3 && checkedKey === key && !busy)
  const save = async (existing?: Similar) => {
    if (!ready) return
    if (existing && !window.confirm(`确认更新 ${existing.number}？将追加内部处理记录，并更新负责人和优先级；原描述和状态保持不变。`)) return
    setBusy(true); setError('')
    try {
      const ticket = existing ? await api<Ticket>(`/tickets/${existing.id}/quick-update`, { method: 'POST', body: JSON.stringify({ organizationId, assigneeId, priority, issue, rawText: parsed.rawText, expectedUpdatedAt: existing.updatedAt }) }) : await api<Ticket>('/tickets', { method: 'POST', body: JSON.stringify({ category, organizationId, assigneeId, priority, title: title.trim(), description: issue.trim(), rawText: parsed.rawText, requestKey, cameraModel: model || undefined, deviceId: deviceId || undefined, occurredAt: date || undefined, status: status === 'PENDING' ? undefined : status, createLinkedLoan: createLinkedLoan ? true : undefined, createLinkedRepair: createLinkedRepair ? true : undefined }) })
      // 别名学习：用户把原文中的客户词改选为其他客户时记录，失败静默不阻塞主流程
      const alias = parsed.customerText?.trim()
      if (alias && organizationId !== parsed.matchedCustomer?.id) void api('/customer-aliases', { method: 'POST', body: JSON.stringify({ alias, organizationId }) }).catch(() => {})
      // 联动提示：入队/建单成功说明与联动失败原因都反馈给用户（失败信息由后端 linkageErrors 携带，工单本身已创建成功）
      const linkNotice = !existing && createLinkedLoan ? '已同步创建借测单并加入排队' : !existing && createLinkedRepair ? '已同步创建维修单' : undefined
      const notice = [linkNotice, ...(ticket.linkageErrors ?? [])].filter(Boolean).join('；') || undefined
      onSaved(ticket, Boolean(existing), notice)
    } catch (e) { setError(e instanceof Error ? e.message : '保存失败'); setRetry((n) => n + 1) } finally { setBusy(false) }
  }
  // 相似工单：优先用解析接口随附的结果，旧后端无该字段时回退到确认页内的防抖查询结果
  const dupList = (parsed.similarTickets?.length ? parsed.similarTickets : similar).slice().sort((a, b) => b.similarity - a.similarity)
  const topDup = dupList[0]
  // 待确认区：客户/负责人未自动绑定时需人工检查，其余字段进「已自动填写」折叠区
  const needsReview = !parsed.matchedCustomer || !parsed.matchedAssignee
  const autoCount = (parsed.matchedCustomer ? 1 : 0) + (parsed.matchedAssignee ? 1 : 0) + 4 + (model.trim() ? 1 : 0) + (devices.length ? 1 : 0)
  const isInteractive = (target: EventTarget | null) => target instanceof HTMLElement && Boolean(target.closest('input, textarea, select, button, a, summary, label'))
  const onConfirmKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (creatingCustomer) return
    if (e.key === 'Escape') { if (!busy) { e.stopPropagation(); onClose() } return }
    if (e.key !== 'Enter') return
    // 焦点在输入控件上时 Enter 保持原生行为（换行/下拉/点击），仅 Ctrl/Cmd+Enter 触发保存
    if (!(e.ctrlKey || e.metaKey) && isInteractive(e.target)) return
    if (busy || !ready) return
    e.preventDefault()
    void save()
  }
  return <Modal title="解析结果确认" onClose={() => { if (!busy) onClose() }} wide><div className="quick-confirm" ref={containerRef} tabIndex={-1} onKeyDown={onConfirmKeyDown}>
    {!dismissedDup && topDup && <div role="alert" className="quick-dup-bar">
      <TriangleAlert size={15} />
      <strong>疑似重复：{topDup.number}（相似度 {Math.round(topDup.similarity)}）{dupList.length > 1 ? ` 等 ${dupList.length} 条` : ''}</strong>
      <span className="header-actions">
        <button type="button" className="button" onClick={() => setShowCompare((v) => !v)}>{showCompare ? '收起对比' : '展开对比'}</button>
        <button type="button" className="button" onClick={() => setDismissedDup(true)}>非重复</button>
      </span>
      {showCompare && <ul className="quick-dup-list">{dupList.slice(0, 3).map((t) => <li key={t.id}>
        <Link to={`/tickets/${t.id}`} target="_blank">{t.number} · {t.title}</Link>
        <span className="muted">{t.organization?.name ?? '未知客户'} · {formatDate(t.createdAt)} · 相似度 {Math.round(t.similarity)}</span>
      </li>)}</ul>}
    </div>}
    <div role="status" className="muted">智能语义解析（本地规则引擎）{parsed.fallbackReason ? ` · ${parsed.fallbackReason}` : ''}</div>
    <fieldset disabled={busy} className="form-grid">
      <section className="span-2 quick-review" aria-label="待确认字段">
        <h3>待确认</h3>
        {!parsed.matchedCustomer && <>
          <label>客户<select aria-label="确认客户" value={organizationId} onChange={(e) => { setOrganizationId(e.target.value); setDeviceId('') }}><option value="">选择现有客户</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          <div className="span-2 match-options">{parsed.customerCandidates.length ? <><strong>可能的客户</strong>{parsed.customerCandidates.map((c) => <label key={c.id}><input type="radio" name="customer-candidate" checked={organizationId === c.id} onChange={() => { setOrganizationId(c.id); setDeviceId('') }} />{c.name}</label>)}</> : <strong>未匹配到现有客户{parsed.customerText ? `：${parsed.customerText}` : ''}</strong>}{canCreateCustomer && <button type="button" className="button" disabled={busy} onClick={() => void createCustomer()}><Plus size={14} />创建新客户</button>}</div>
        </>}
        {!parsed.matchedAssignee && <>
          <label>负责人<select aria-label="确认负责人" value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}><option value="">负责人：未匹配</option>{users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label>
          <div className="span-2 match-options"><strong>负责人：未匹配{parsed.assigneeText ? `（${parsed.assigneeText}）` : ''}</strong>{parsed.assigneeCandidates.map((u) => <label key={u.id}><input type="radio" name="assignee-candidate" checked={assigneeId === u.id} onChange={() => setAssigneeId(u.id)} />{u.name}</label>)}</div>
        </>}
        <div className="span-2 field-with-action">
          <label>问题标题<input aria-label="确认标题" maxLength={240} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
          <button type="button" className="button" disabled={summarizing || busy || issue.trim().length < 3} onClick={() => void suggestTitle()}><Sparkles size={14} />{summarizing ? '正在总结' : '自动总结'}</button>
        </div>
        {!needsReview && <p className="span-2 muted quick-review-hint">字段均已自动识别，请确认标题。</p>}
      </section>
      <details className="span-2 quick-auto">
        <summary>已自动填写 {autoCount} 项</summary>
        <div className="form-grid">
          {parsed.matchedCustomer && <label>客户<select aria-label="确认客户" value={organizationId} onChange={(e) => { setOrganizationId(e.target.value); setDeviceId('') }}><option value="">选择现有客户</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
          {parsed.matchedAssignee && <label>负责人<select aria-label="确认负责人" value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}><option value="">负责人：未匹配</option>{users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select>{parsed.assigneeDefaulted && parsed.matchedAssignee && <small>默认当前用户：{parsed.matchedAssignee.name}</small>}</label>}
          <label>问题分类<select aria-label="确认问题分类" value={category} onChange={(e) => changeCategory(e.target.value as TicketCategory)}>{Object.entries(ticketCategoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><small>按关键词初步识别，可修改</small></label>
          {(category === 'PRE_SALES' || category === 'LOAN_REQUEST') && <label className="span-2 checkbox-row"><input type="checkbox" checked={createLinkedLoan} onChange={(e) => setCreateLinkedLoan(e.target.checked)} />同时创建借测单并加入排队</label>}
          {category === 'HARDWARE_FAILURE' && <label className="span-2 checkbox-row"><input type="checkbox" checked={createLinkedRepair} onChange={(e) => setCreateLinkedRepair(e.target.checked)} />同时创建维修单</label>}
          <label>优先级<select aria-label="确认优先级" value={priority} onChange={(e) => setPriority(e.target.value as TicketPriority)}>{Object.entries(ticketPriorityLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>状态<select aria-label="确认状态" value={status} onChange={(e) => setStatus(e.target.value as TicketStatus)}>{Object.entries(ticketStatusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><small>识别「已解决/处理中/等待客户反馈」等关键词</small></label>
          <label>工单时间<input aria-label="确认工单时间" type="date" value={date} onChange={(e) => setDate(e.target.value)} /><small>{date ? '编号按此日期生成，留空为今天' : '未指定，按今天记录'}</small></label>
          <label className="span-2">设备型号<input maxLength={100} value={model} onChange={(e) => { setModel(e.target.value); setDeviceId('') }} /></label>
          {devices.length > 0 && <label className="span-2">关联设备<select value={deviceId} onChange={(e) => setDeviceId(e.target.value)}><option value="">不关联设备</option>{devices.map((d) => <option key={d.id} value={d.id}>{d.name} {d.serialNumber ?? ''}</option>)}</select></label>}
        </div>
      </details>
      <label className="span-2">问题描述<textarea aria-label="确认问题" rows={3} maxLength={4000} value={issue} onChange={(e) => setIssue(e.target.value)} /></label>
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
