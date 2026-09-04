export type Role = 'admin' | 'support' | 'employee' | 'customer'
export type ThemeMode = 'light' | 'dark' | 'system'

export interface User {
  id: string
  username: string
  name: string
  email: string | null
  role: Role
  customerOrganizationId: string | null
  permissions: string[]
}

export interface Customer {
  id: string
  name: string
  region?: string
  industry?: string
  level?: string
  notes?: string
  contacts?: Contact[]
  devices?: Device[]
  projects?: Project[]
  technicalOwner?: { id: string; name: string }
  businessOwner?: { id: string; name: string }
  _count?: { devices?: number; projects?: number; tickets?: number }
}

export interface Contact { id: string; name: string; title?: string; phone?: string; email?: string; wechat?: string; isPrimary: boolean }
export interface Device { id: string; name: string; product?: string; cameraModel?: string; serialNumber?: string; sdkVersion?: string; location?: string; organization?: { id: string; name: string } }
export interface Project { id: string; name: string; application?: string; status?: string; organization?: { id: string; name: string } }

export interface WorkType { id: string; code: string; label: string; description?: string; isActive: boolean; sortOrder: number }
export type WorkItemStatus = 'TODO' | 'IN_PROGRESS' | 'WAITING_FEEDBACK' | 'COMPLETED' | 'CANCELED'
export type WorkItemPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'URGENT'

export interface WorkItem {
  convertedTicketId?: string
  id: string
  title: string
  description?: string
  priority: WorkItemPriority
  status: WorkItemStatus
  startDate?: string
  dueDate?: string
  completedAt?: string
  progress: number
  tags: string[]
  createdAt: string
  updatedAt: string
  workType: WorkType
  organization?: { id: string; name: string }
  project?: Project
  owner: { id: string; name: string }
  collaborators?: Array<{ user: { id: string; name: string } }>
  _count?: { worklogs: number }
}

export type TicketStatus = 'PENDING' | 'IN_PROGRESS' | 'WAITING_CUSTOMER' | 'WAITING_RND' | 'RESOLVED' | 'CLOSED'
export type TicketPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'URGENT'

export interface Ticket {
  rawText?: string
  id: string
  number: string
  source: string
  category: string
  title: string
  description: string
  status: TicketStatus
  priority: TicketPriority
  cameraModel?: string
  serialNumber?: string
  sdkVersion?: string
  systemEnvironment?: string
  plannedAt?: string
  resolvedAt?: string
  solution?: string
  createdAt: string
  updatedAt: string
  organization: { id: string; name: string; level?: string }
  contact?: Contact
  device?: Device
  project?: Project
  assignee?: { id: string; name: string }
  createdBy?: { id: string; name: string }
  collaborators?: Array<{ user: { id: string; name: string } }>
  events?: TicketEvent[]
}

export interface TicketEvent { id: string; type: string; visibility: 'INTERNAL' | 'CUSTOMER'; content: string; createdAt: string; author: { id: string; name: string } }
export interface Worklog { id: string; occurredAt: string; summary: string; problem?: string; actions?: string; result?: string; nextStep?: string; durationMinutes?: number; rawText?: string; aiExtractionId?: string; source: string; status: 'DRAFT' | 'CONFIRMED'; workType: WorkType; organization?: { id: string; name: string }; ticket?: { id: string; number: string; title: string }; workItem?: { id: string; title: string }; project?: Project; author: { id: string; name: string } }
