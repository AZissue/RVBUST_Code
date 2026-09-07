import { ticketPriorityLabels, ticketStatusLabels } from '../lib/labels'
import type { TicketPriority, TicketStatus } from '../types'

export const statusLabel = (status: TicketStatus) => ticketStatusLabels[status]
export const priorityLabel = (priority: TicketPriority) => ticketPriorityLabels[priority]
export function StatusBadge({ status }: { status: TicketStatus }) { return <span className={`badge status-${status.toLowerCase()}`}>{ticketStatusLabels[status]}</span> }
export function PriorityBadge({ priority }: { priority: TicketPriority }) { return <span className={`badge priority-${priority.toLowerCase()}`}>{ticketPriorityLabels[priority]}</span> }
