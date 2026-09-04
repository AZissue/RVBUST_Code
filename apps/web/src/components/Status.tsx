import type { TicketPriority, TicketStatus } from '../types'

const statusLabels: Record<TicketStatus, string> = { PENDING: '待处理', IN_PROGRESS: '处理中', WAITING_CUSTOMER: '等待客户', WAITING_RND: '等待研发', RESOLVED: '已解决', CLOSED: '已关闭' }
const priorityLabels: Record<TicketPriority, string> = { LOW: '低', MEDIUM: '中', HIGH: '高', URGENT: '紧急' }

export const statusLabel = (status: TicketStatus) => statusLabels[status]
export const priorityLabel = (priority: TicketPriority) => priorityLabels[priority]
export function StatusBadge({ status }: { status: TicketStatus }) { return <span className={`badge status-${status.toLowerCase()}`}>{statusLabels[status]}</span> }
export function PriorityBadge({ priority }: { priority: TicketPriority }) { return <span className={`badge priority-${priority.toLowerCase()}`}>{priorityLabels[priority]}</span> }

