export type Role = 'admin' | 'support' | 'employee' | 'customer'
export type ThemeMode = 'light' | 'dark' | 'system'
export type UserStatus = 'PENDING' | 'ACTIVE' | 'DISABLED'

export interface User {
  id: string
  username: string
  name: string
  email: string | null
  role: Role
  status?: UserStatus
  department?: string | null
  phone?: string | null
  createdAt?: string
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
  websiteUrl?: string | null
  wikiRef?: string | null
  background?: string | null
  applicationScenarios?: string | null
  projectNeeds?: string | null
  contacts?: Contact[]
  devices?: Device[]
  projects?: Project[]
  technicalOwner?: { id: string; name: string }
  businessOwner?: { id: string; name: string }
  _count?: { devices?: number; projects?: number; tickets?: number }
}

export interface Contact { id: string; name: string; title?: string; phone?: string; email?: string; wechat?: string; isPrimary: boolean }
export type DeviceStatus = 'IN_STOCK' | 'LOANED' | 'REPAIRING' | 'RETIRED'
export type DeviceOwnerType = 'COMPANY' | 'CUSTOMER'
export interface Device { id: string; name: string; product?: string; cameraModel?: string; serialNumber?: string; sdkVersion?: string; location?: string; status?: DeviceStatus; ownerType: DeviceOwnerType; organizationId?: string | null; purchaseDate?: string; warrantyUntil?: string; notes?: string; organization?: { id: string; name: string } | null }
export interface Project { id: string; name: string; application?: string; status?: string; organization?: { id: string; name: string } }

export type LoanStatus = 'ONGOING' | 'OVERDUE' | 'RETURNED' | 'CANCELLED'
export interface LoanItem { id: string; returnedAt?: string | null; conditionNote?: string | null; device: { id: string; name: string; serialNumber?: string | null; cameraModel?: string | null } }
export interface LoanOrder {
  id: string
  loanNo: string
  purpose: string
  status: LoanStatus
  loanedAt: string
  dueAt: string
  returnedAt?: string | null
  agreementNo?: string | null
  note?: string | null
  organization: { id: string; name: string }
  contact?: { id: string; name: string } | null
  assignee?: { id: string; name: string } | null
  items: LoanItem[]
}

export type RepairStatus = 'RECEIVED' | 'DIAGNOSING' | 'REPAIRING' | 'SHIPPED' | 'CLOSED'
export interface RepairEvent { id: string; type: string; content: string; createdAt: string }
export interface Attachment { id: string; originalName: string; mimeType: string; sizeBytes: number; createdAt: string }
export interface RepairOrder {
  id: string
  repairNo: string
  symptom: string
  faultCause?: string | null
  resolution?: string | null
  trackingNo?: string | null
  note?: string | null
  inWarranty?: boolean | null
  status: RepairStatus
  receivedAt: string
  shippedAt?: string | null
  closedAt?: string | null
  device: { id: string; name: string; serialNumber?: string | null; cameraModel?: string | null }
  organization: { id: string; name: string }
  contact?: { id: string; name: string } | null
  assignee?: { id: string; name: string } | null
  events?: RepairEvent[]
  attachments?: Attachment[]
}

export interface CustomerProfile {
  organization: Customer
  contacts: Contact[]
  devices: Device[]
  tickets: Ticket[]
  loanOrders: LoanOrder[]
  repairOrders: RepairOrder[]
}

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
export type TicketCategory = 'PRE_SALES' | 'TRAINING' | 'POINTCLOUD_DEBUG' | 'SDK_DEVELOPMENT' | 'HAND_EYE_CALIBRATION' | 'HARDWARE_FAILURE' | 'OTHER'

export interface Ticket {
  rawText?: string
  id: string
  number: string
  category: TicketCategory
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
