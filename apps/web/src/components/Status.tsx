import { ticketPriorityLabels, ticketStatusLabels } from '../lib/labels'
import type { TicketPriority, TicketStatus } from '../types'

export const statusLabel = (status: TicketStatus) => ticketStatusLabels[status]
export const priorityLabel = (priority: TicketPriority) => ticketPriorityLabels[priority]
export function StatusTransition({ content }: { content: string }) {
  const match = content.match(/^([A-Z_]+)\s*->\s*([A-Z_]+)([\s\S]*)$/)
  if (!match || !(match[1] in ticketStatusLabels) || !(match[2] in ticketStatusLabels)) return <>{content}</>
  return <span className="status-transition"><StatusBadge status={match[1] as TicketStatus} /><span aria-label="变更为"> → </span><StatusBadge status={match[2] as TicketStatus} />{match[3] && <span>{match[3]}</span>}</span>
}
export function StatusBadge({ status }: { status: TicketStatus }) { return <span className={`badge status-${status.toLowerCase()}`}>{ticketStatusLabels[status]}</span> }
export function PriorityBadge({ priority }: { priority: TicketPriority }) { return <span className={`badge priority-${priority.toLowerCase()}`}>{ticketPriorityLabels[priority]}</span> }
