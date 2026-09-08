import { PrismaClient } from '@prisma/client'
const prisma = new PrismaClient()
async function main() {
  const counts = {
    users: await prisma.user.count(),
    customers: await prisma.customerOrganization.count(),
    contacts: await prisma.contact.count(),
    devices: await prisma.device.count(),
    tickets: await prisma.ticket.count(),
    ticketEvents: await prisma.ticketEvent.count(),
    worklogs: await prisma.worklog.count(),
    workItems: await prisma.workItem.count(),
    loans: await prisma.loanOrder.count(),
    repairs: await prisma.repairOrder.count(),
    notifications: await prisma.notification.count(),
    attachments: await prisma.attachment.count(),
  }
  console.log('counts', counts)
  const customers = await prisma.customerOrganization.findMany({ select: { id: true, name: true, _count: { select: { tickets: true, devices: true, contacts: true, worklogs: true, loanOrders: true, repairOrders: true } } } })
  console.table(customers)
  const tickets = await prisma.ticket.findMany({ select: { id: true, number: true, title: true, category: true, status: true, organization: { select: { name: true } } }, orderBy: { createdAt: 'asc' } })
  console.table(tickets)
  const devices = await prisma.device.findMany({ select: { id: true, name: true, serialNumber: true, ownerType: true, status: true } })
  console.table(devices)
  const worklogs = await prisma.worklog.findMany({ select: { id: true, summary: true, occurredAt: true } })
  console.table(worklogs)
  const workItems = await prisma.workItem.findMany({ select: { id: true, title: true, status: true } })
  console.table(workItems)
}
main().finally(() => prisma.$disconnect())
