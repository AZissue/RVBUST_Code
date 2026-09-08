import { PrismaClient } from '@prisma/client'
const prisma = new PrismaClient()
const GARBAGE_TICKET_NUMBERS = ['TS-260907-370051', 'TS-260907-281427', 'RVC-260907-001', 'RVC-260907-002', 'RVC-260907-003', 'RVC-260908-001', 'RVC-260908-002', 'RVC-260908-003']
const GARBAGE_CUSTOMER_NAMES = ['123', '213', '仁新机器人']
async function main() {
  const tickets = await prisma.ticket.findMany({ where: { number: { in: GARBAGE_TICKET_NUMBERS } }, select: { id: true, number: true } })
  const ticketIds = tickets.map((t) => t.id)
  console.log('delete tickets', tickets.map((t) => t.number))
  // 关联清理：通知（FK 无级联）、事件/协作/附件级联删除，工作记录外键 SetNull 由数据库处理
  const removed = {
    notifications: (await prisma.notification.deleteMany()).count,
    worklog: (await prisma.worklog.deleteMany({ where: { summary: '123' } })).count,
    tickets: ticketIds.length ? (await prisma.ticket.deleteMany({ where: { id: { in: ticketIds } } })).count : 0,
    companyDevice: (await prisma.device.deleteMany({ where: { ownerType: 'COMPANY' } })).count,
    customers: (await prisma.customerOrganization.deleteMany({ where: { name: { in: GARBAGE_CUSTOMER_NAMES } } })).count,
  }
  const fixed = await prisma.ticket.updateMany({ where: { category: '网络连接' }, data: { category: '硬件故障' } })
  console.log('removed', removed, 'category fixed', fixed.count)
  console.log('remaining tickets', await prisma.ticket.findMany({ select: { number: true, title: true, category: true }, orderBy: { number: 'asc' } }))
  console.log('remaining customers', await prisma.customerOrganization.findMany({ select: { name: true } }))
  console.log('remaining worklogs', await prisma.worklog.count(), 'devices', await prisma.device.count())
}
main().finally(() => prisma.$disconnect())
