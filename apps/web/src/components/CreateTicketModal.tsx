import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Sparkles } from 'lucide-react'
import { Modal } from './Modal'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'
import { TICKET_CATEGORIES, ticketCategoryLabels } from '../lib/labels'
import { statusLabel as ticketStatusLabel } from './Status'
import type { Customer, Device, Ticket, TicketCategory, TicketStatus } from '../types'

const normalized = (value: string) => value.trim().toLocaleLowerCase()
const deviceLabel = (device: Device) => [device.name, device.serialNumber || device.id].join(' · ')

type Continuable = {
  id: string
  number: string
  title: string
  status: TicketStatus
  updatedAt: string
  assignee?: { id: string; name: string } | null
  loanOrders: { id: string }[]
  repairOrders: { id: string }[]
}

/** 接续区：复选同客户未解决工单 + 每条必填接续说明 + 自动关单/迁移关联业务开关 */
function ContinuationPicker({ customerId, selected, onChange, notes, onNote, autoClose, onAutoClose, carryLinks, onCarryLinks }: {
  customerId: string
  selected: Map<string, { id: string; number: string; title: string; activeLinks: number }>
  onChange: (next: Map<string, { id: string; number: string; title: string; activeLinks: number }>) => void
  notes: Record<string, string>
  onNote: (id: string, note: string) => void
  autoClose: boolean
  onAutoClose: (value: boolean) => void
  carryLinks: boolean
  onCarryLinks: (value: boolean) => void
}) {
  const continuable = useRemote(() => api<Continuable[]>(`/tickets/continuable?organizationId=${customerId}`), [customerId])
  if (continuable.loading || continuable.error || !continuable.data?.length) return null
  const toggle = (item: Continuable, checked: boolean) => {
    const next = new Map(selected)
    if (checked) next.set(item.id, { id: item.id, number: item.number, title: item.title, activeLinks: item.loanOrders.length + item.repairOrders.length })
    else next.delete(item.id)
    onChange(next)
  }
  const hasActiveLinks = [...selected.values()].some((item) => item.activeLinks > 0)
  return <section className="span-2 continuation-picker">
    <div className="section-heading"><div><h3>接续工单</h3><p>该客户有以下未解决工单，可勾选接续：原单时间线留痕，创建后按下方选项关闭</p></div></div>
    <div className="continuation-list">
      {continuable.data.map((item) => <div key={item.id} className={`continuation-item${selected.has(item.id) ? ' selected' : ''}`}>
        <label className="checkbox-row"><input type="checkbox" checked={selected.has(item.id)} onChange={(event) => toggle(item, event.target.checked)} />
          <strong className="mono">{item.number}</strong><span className="continuation-title" title={item.title}>{item.title}</span>
          <span className="badge">{ticketStatusLabel(item.status)}</span>
          {item.loanOrders.length + item.repairOrders.length > 0 && <span className="badge warn">进行中业务 {item.loanOrders.length + item.repairOrders.length}</span>}
        </label>
        {selected.has(item.id) && <label className="continuation-note">接续说明（必填，2-500 字）<input value={notes[item.id] ?? ''} onChange={(event) => onNote(item.id, event.target.value)} minLength={2} maxLength={500} placeholder="如：样品已寄出，待客户测试反馈" /></label>}
      </div>)}
    </div>
    {selected.size > 0 && <div className="continuation-options">
      <label className="checkbox-row"><input type="checkbox" checked={autoClose} onChange={(event) => onAutoClose(event.target.checked)} />同时关闭所选工单（接续说明将写入原单；取消勾选则仅建立关联，原单保持开放）</label>
      {autoClose && hasActiveLinks && <label className="checkbox-row"><input type="checkbox" checked={carryLinks} onChange={(event) => onCarryLinks(event.target.checked)} />将原单进行中的借测/维修单迁移到新工单（不迁移则无法关闭原单）</label>}
    </div>}
  </section>
}

export function CreateTicketModal({ onClose, onCreated, defaultAssigneeId, initialCustomerName, initialTitle, presetContinuations }: {
  onClose: () => void
  onCreated: (ticket: Ticket, notice?: string) => void
  defaultAssigneeId?: string
  /** 从详情页「发起接续」打开时预填客户与标题 */
  initialCustomerName?: string
  initialTitle?: string
  /** 预置接续的前置工单（默认勾选，接续说明需填写） */
  presetContinuations?: { id: string; number: string; title: string; activeLinks?: number }[]
}) {
  const users = useRemote(() => api<Array<{ id: string; name: string }>>('/users/assignable'), [])
  const customers = useRemote(() => api<Customer[]>('/customers'), [])
  const [customerName, setCustomerName] = useState(initialCustomerName ?? '')
  const [confirmed, setConfirmed] = useState(false)
  const [deviceText, setDeviceText] = useState('')
  const [contactId, setContactId] = useState('')
  const [assistTargetIds, setAssistTargetIds] = useState<string[]>([])
  const [assistMessage, setAssistMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [summarizing, setSummarizing] = useState(false)
  const lock = useRef(false)
  const titleRef = useRef<HTMLInputElement>(null)
  const descriptionRef = useRef<HTMLTextAreaElement>(null)
  const [requestKey] = useState(() => crypto.randomUUID())
  const [error, setError] = useState('')
  const [category, setCategory] = useState<TicketCategory>('OTHER')
  const [linkageDefaults, setLinkageDefaults] = useState({ loan: false, repair: false })
  const [createLinkedLoan, setCreateLinkedLoan] = useState(false)
  const [createLinkedRepair, setCreateLinkedRepair] = useState(false)
  // 接续工单：选中的前置单 + 各单接续说明 + 自动关单（默认勾选）+ 迁移关联业务（默认勾选）
  const [selectedContinuations, setSelectedContinuations] = useState<Map<string, { id: string; number: string; title: string; activeLinks: number }>>(() => new Map((presetContinuations ?? []).map((item) => [item.id, { id: item.id, number: item.number, title: item.title, activeLinks: item.activeLinks ?? 0 }])))
  const [continuationNotes, setContinuationNotes] = useState<Record<string, string>>({})
  const [autoClose, setAutoClose] = useState(true)
  const [carryLinks, setCarryLinks] = useState(true)
  // 弹窗打开时读取联动默认配置；接口失败时静默回落 false
  useEffect(() => {
    let cancelled = false
    api<{ defaultCreate: { loan: boolean; repair: boolean } }>('/system/linkage-config')
      .then(config => { if (!cancelled) setLinkageDefaults({ loan: Boolean(config.defaultCreate?.loan), repair: Boolean(config.defaultCreate?.repair) }) })
      .catch(() => { /* 静默回落默认 false */ })
    return () => { cancelled = true }
  }, [])
  const showLoanOption = category === 'PRE_SALES' || category === 'LOAN_REQUEST'
  const showRepairOption = category === 'HARDWARE_FAILURE'
  const changeCategory = (value: TicketCategory) => { setCategory(value); setCreateLinkedLoan((value === 'PRE_SALES' || value === 'LOAN_REQUEST') && linkageDefaults.loan); setCreateLinkedRepair(value === 'HARDWARE_FAILURE' && linkageDefaults.repair) }
  const customer = customers.data?.find(item => normalized(item.name) === normalized(customerName))
  const detail = useRemote(() => customer ? api<Customer>(`/customers/${customer.id}`) : Promise.resolve(null), [customer?.id])
  const currentDetail = detail.data?.id === customer?.id ? detail.data : null
  const device = currentDetail?.devices?.find(item => deviceLabel(item) === deviceText)
  const toggleAssist = (userId: string) => setAssistTargetIds(previous => previous.includes(userId) ? previous.filter(item => item !== userId) : [...previous, userId])
  const suggestTitle = async () => {
    const description = descriptionRef.current?.value.trim() ?? ''
    if (description.length < 3) { setError('请先填写问题描述，至少 3 个字符'); return }
    setSummarizing(true); setError('')
    try {
      const result = await api<{ title: string }>('/tickets/suggest-title', { method: 'POST', body: JSON.stringify({ description: description.slice(0, 4000) }) })
      if (titleRef.current) titleRef.current.value = result.title.slice(0, 240)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '总结失败') } finally { setSummarizing(false) }
  }
  useEffect(() => { setDeviceText(''); setContactId('') }, [customer?.id])
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const value = (key: string) => String(form.get(key) ?? '').trim()
    try {
      let selected = customer
      let notice: string | undefined
      if (deviceText && !device) throw new Error('请从候选中选择设备，或清空关联设备')
      if (!selected) {
        if (!confirmed) throw new Error('请确认是否新建客户')
        selected = await api<Customer>('/customers', { method: 'POST', body: JSON.stringify({ name: customerName.trim() }) })
        customers.setData([...(customers.data ?? []), selected])
        notice = `已新建客户「${selected.name}」`
      }
      // 维修单允许先创建后补录：序列号缺失时不拦截（返修单支持无 SN 建档，后续在维修详情补填）
      const continuationList = [...selectedContinuations.values()]
      for (const item of continuationList) {
        if ((continuationNotes[item.id] ?? '').trim().length < 2) throw new Error(`请填写工单 ${item.number} 的接续说明（2-500 字）`)
      }
      const ticket = await api<Ticket>('/tickets', { method: 'POST', body: JSON.stringify({
        requestKey, organizationId: selected.id, contactId: contactId || undefined, deviceId: device?.id,
        assigneeId: value('assigneeId') || undefined, title: value('title'), description: value('description'),
        category, priority: value('priority') || 'MEDIUM',
        cameraModel: device?.cameraModel || value('cameraModel') || undefined,
        serialNumber: device?.serialNumber || value('serialNumber') || undefined,
        sdkVersion: device?.sdkVersion || value('sdkVersion') || undefined,
        systemEnvironment: value('systemEnvironment') || undefined,
        plannedAt: value('plannedAt') ? new Date(value('plannedAt')).toISOString() : undefined,
        createLinkedLoan: showLoanOption && createLinkedLoan ? true : undefined,
        createLinkedRepair: showRepairOption && createLinkedRepair ? true : undefined,
        assistTargetIds: assistTargetIds.length ? assistTargetIds : undefined,
        assistMessage: assistMessage.trim() || undefined,
        continuations: continuationList.length ? continuationList.map((item) => ({ fromTicketId: item.id, note: (continuationNotes[item.id] ?? '').trim() })) : undefined,
        autoClose: continuationList.length ? autoClose : undefined,
        carryLinks: continuationList.length ? carryLinks : undefined,
      }) })
      const linkedNotice = showLoanOption && createLinkedLoan ? '已同步创建借测单并加入排队' : showRepairOption && createLinkedRepair ? '已同步创建维修单' : undefined
      const continuationNotice = continuationList.length ? `已接续 ${continuationList.length} 张工单${autoClose ? '，原单已关闭并留痕' : '（仅关联，原单保持开放）'}` : undefined
      const notices = [notice, linkedNotice, continuationNotice, ...(ticket.linkageErrors ?? [])].filter(Boolean)
      onCreated(ticket, notices.length ? notices.join('；') : undefined)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '创建失败') }
    finally { lock.current = false; setBusy(false) }
  }
  return <Modal title="创建技术支持工单" onClose={() => { if (!lock.current) onClose() }} wide>
    <form className="form-grid" onSubmit={submit}>
      <label>客户公司<input autoFocus name="customerName" required minLength={2} maxLength={200} value={customerName} onChange={event => { setCustomerName(event.target.value); setConfirmed(false); setSelectedContinuations(new Map()); setContinuationNotes({}) }} list="ticket-customers" placeholder="搜索客户名称" autoComplete="off" />
        <datalist id="ticket-customers">{customers.data?.map(item => <option key={item.id} value={item.name} />)}</datalist>
      </label>
      <label>负责人{users.data ? <select name="assigneeId" defaultValue={defaultAssigneeId ?? ''}><option value="">我自己</option>{users.data.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select> : <span>加载中…</span>}</label>
      {!customers.loading && !customers.error && customerName.trim() && !customer && <label className="span-2 checkbox-row"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />确认新建客户「{customerName.trim()}」</label>}
      <div className="field-with-action">
        <label>问题标题<input ref={titleRef} name="title" required minLength={3} maxLength={240} defaultValue={initialTitle ?? ''} /></label>
        <button type="button" className="button" disabled={summarizing} onClick={() => void suggestTitle()}><Sparkles size={14} />{summarizing ? '正在总结' : '自动总结'}</button>
      </div>
      <label>问题分类<select name="category" value={category} onChange={event => changeCategory(event.target.value as TicketCategory)}>{TICKET_CATEGORIES.map(item => <option key={item} value={item}>{ticketCategoryLabels[item]}</option>)}</select></label>
      {showLoanOption && <label className="span-2 checkbox-row"><input type="checkbox" checked={createLinkedLoan} onChange={event => setCreateLinkedLoan(event.target.checked)} />同时创建借测单并加入排队</label>}
      {showRepairOption && <label className="span-2 checkbox-row"><input type="checkbox" checked={createLinkedRepair} onChange={event => setCreateLinkedRepair(event.target.checked)} />同时创建维修单</label>}
      {customer && <ContinuationPicker customerId={customer.id} selected={selectedContinuations} onChange={setSelectedContinuations} notes={continuationNotes} onNote={(id, note) => setContinuationNotes((previous) => ({ ...previous, [id]: note }))} autoClose={autoClose} onAutoClose={setAutoClose} carryLinks={carryLinks} onCarryLinks={setCarryLinks} />}
      <label className="span-2">问题描述<textarea ref={descriptionRef} name="description" required minLength={3} maxLength={20000} rows={4} /></label>
      <label className="span-2 checkbox-row"><input type="checkbox" checked={assistTargetIds.length > 0} onChange={event => setAssistTargetIds(event.target.checked ? (users.data ?? []).map(item => item.id) : [])} />需要协作：添加系统内同事为协作人，共同跟进处理该工单</label>
      {assistTargetIds.length > 0 && <label className="span-2">协作人<div className="assist-user-list">{users.data?.map(item => <label key={item.id} className="checkbox-row"><input type="checkbox" checked={assistTargetIds.includes(item.id)} onChange={() => toggleAssist(item.id)} />{item.name}</label>) ?? <span>加载中…</span>}</div></label>}
      {assistTargetIds.length > 0 && <label className="span-2">协助说明<input value={assistMessage} onChange={event => setAssistMessage(event.target.value)} maxLength={2000} placeholder="如：需要协助排查硬件环境问题" /></label>}
      <details className="span-2"><summary>补充信息</summary><div className="form-grid">
        <label>关联设备<input value={deviceText} onChange={event => setDeviceText(event.target.value)} list="ticket-devices" disabled={!currentDetail} placeholder="搜索设备名称或序列号" /><datalist id="ticket-devices">{currentDetail?.devices?.map(item => <option key={item.id} value={deviceLabel(item)} />)}</datalist></label>
        <label>联系人<select value={contactId} onChange={event => setContactId(event.target.value)} disabled={!currentDetail}><option value="">未关联</option>{currentDetail?.contacts?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>优先级<select name="priority" defaultValue="MEDIUM"><option value="LOW">低</option><option value="MEDIUM">普通</option><option value="HIGH">高</option><option value="URGENT">紧急</option></select></label>
        <label>计划完成时间<input name="plannedAt" type="datetime-local" /></label>
        <label>相机型号<input key={device?.id ?? 'model'} name="cameraModel" defaultValue={device?.cameraModel ?? ''} readOnly={Boolean(device?.cameraModel)} maxLength={100} /></label>
        <label>序列号<input key={device?.id ?? 'serial'} name="serialNumber" defaultValue={device?.serialNumber ?? ''} readOnly={Boolean(device?.serialNumber)} maxLength={120} /></label>
        <label>SDK 版本<input key={device?.id ?? 'sdk'} name="sdkVersion" defaultValue={device?.sdkVersion ?? ''} readOnly={Boolean(device?.sdkVersion)} maxLength={80} /></label>
        <label className="span-2">系统环境<textarea name="systemEnvironment" rows={2} maxLength={4000} /></label>
        {detail.error && <div role="alert" className="form-error span-2">{detail.error}<button type="button" onClick={() => void detail.refresh()}>重新加载客户信息</button></div>}
      </div></details>
      {(error || customers.error || users.error) && <div role="alert" className="form-error span-2">{error || customers.error || users.error}<button type="button" onClick={() => { void customers.refresh(); void users.refresh() }}>重试加载</button></div>}
      <div className="form-actions span-2"><button type="button" className="button" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy || customers.loading || users.loading || Boolean(customers.error || users.error) || (!customer && !confirmed)}>{busy ? '正在创建' : '创建工单'}</button></div>
    </form>
  </Modal>
}
