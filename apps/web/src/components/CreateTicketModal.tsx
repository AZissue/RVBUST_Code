import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Modal } from './Modal'
import { useRemote } from '../hooks/useRemote'
import { api } from '../lib/api'
import { TICKET_CATEGORIES, ticketCategoryLabels } from '../lib/labels'
import type { Customer, Device, Ticket } from '../types'

const normalized = (value: string) => value.trim().toLocaleLowerCase()
const deviceLabel = (device: Device) => [device.name, device.serialNumber || device.id].join(' · ')

export function CreateTicketModal({ onClose, onCreated, defaultAssigneeId }: { onClose: () => void; onCreated: (ticket: Ticket, notice?: string) => void; defaultAssigneeId?: string }) {
  const users = useRemote(() => api<Array<{ id: string; name: string }>>('/users/assignable'), [])
  const customers = useRemote(() => api<Customer[]>('/customers'), [])
  const [customerName, setCustomerName] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [deviceText, setDeviceText] = useState('')
  const [contactId, setContactId] = useState('')
  const [assistTargetIds, setAssistTargetIds] = useState<string[]>([])
  const [assistMessage, setAssistMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [requestKey] = useState(() => crypto.randomUUID())
  const [error, setError] = useState('')
  const customer = customers.data?.find(item => normalized(item.name) === normalized(customerName))
  const detail = useRemote(() => customer ? api<Customer>(`/customers/${customer.id}`) : Promise.resolve(null), [customer?.id])
  const currentDetail = detail.data?.id === customer?.id ? detail.data : null
  const device = currentDetail?.devices?.find(item => deviceLabel(item) === deviceText)
  const toggleAssist = (userId: string) => setAssistTargetIds(previous => previous.includes(userId) ? previous.filter(item => item !== userId) : [...previous, userId])
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
      const ticket = await api<Ticket>('/tickets', { method: 'POST', body: JSON.stringify({
        requestKey, organizationId: selected.id, contactId: contactId || undefined, deviceId: device?.id,
        assigneeId: value('assigneeId') || undefined, title: value('title'), description: value('description'),
        category: value('category') || 'OTHER', priority: value('priority') || 'MEDIUM',
        cameraModel: device?.cameraModel || value('cameraModel') || undefined,
        serialNumber: device?.serialNumber || value('serialNumber') || undefined,
        sdkVersion: device?.sdkVersion || value('sdkVersion') || undefined,
        systemEnvironment: value('systemEnvironment') || undefined,
        plannedAt: value('plannedAt') ? new Date(value('plannedAt')).toISOString() : undefined,
        assistTargetIds: assistTargetIds.length ? assistTargetIds : undefined,
        assistMessage: assistMessage.trim() || undefined,
      }) })
      onCreated(ticket, notice)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '创建失败') }
    finally { lock.current = false; setBusy(false) }
  }
  return <Modal title="创建技术支持工单" onClose={() => { if (!lock.current) onClose() }} wide>
    <form className="form-grid" onSubmit={submit}>
      <label>客户公司<input autoFocus name="customerName" required minLength={2} maxLength={200} value={customerName} onChange={event => { setCustomerName(event.target.value); setConfirmed(false) }} list="ticket-customers" placeholder="搜索客户名称" autoComplete="off" />
        <datalist id="ticket-customers">{customers.data?.map(item => <option key={item.id} value={item.name} />)}</datalist>
      </label>
      <label>负责人{users.data ? <select name="assigneeId" defaultValue={defaultAssigneeId ?? ''}><option value="">我自己</option>{users.data.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select> : <span>加载中…</span>}</label>
      {!customers.loading && !customers.error && customerName.trim() && !customer && <label className="span-2 checkbox-row"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />确认新建客户「{customerName.trim()}」</label>}
      <label>问题标题<input name="title" required minLength={3} maxLength={240} /></label>
      <label>问题分类<select name="category" defaultValue="OTHER">{TICKET_CATEGORIES.map(item => <option key={item} value={item}>{ticketCategoryLabels[item]}</option>)}</select></label>
      <label className="span-2">问题描述<textarea name="description" required minLength={3} maxLength={20000} rows={4} /></label>
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
