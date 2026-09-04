import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import {
  PrismaClient,
  TicketEventType,
  TicketPriority,
  TicketSource,
  TicketStatus,
  Visibility,
  WorklogSource,
} from '../apps/api/node_modules/@prisma/client/index.js';

type LegacyRecord = Record<string, unknown>;
type LegacyDatabase = {
  users?: LegacyRecord[];
  customers?: LegacyRecord[];
  tickets?: LegacyRecord[];
  worklogs?: LegacyRecord[];
};

const prisma = new PrismaClient();
const args = process.argv.slice(2);
const apply = args.includes('--apply');
const sourceArg = args.find((arg) => !arg.startsWith('--'));
const sourcePath = resolve(sourceArg ?? '../tech-support-crm/server/data/db.json');
const fallbackUsername = args.find((arg) => arg.startsWith('--owner='))?.slice('--owner='.length) || 'support';

const statusMap: Record<string, TicketStatus> = {
  pending: TicketStatus.PENDING,
  processing: TicketStatus.IN_PROGRESS,
  resolved: TicketStatus.RESOLVED,
  closed: TicketStatus.CLOSED,
};
const priorityMap: Record<string, TicketPriority> = {
  low: TicketPriority.LOW,
  medium: TicketPriority.MEDIUM,
  high: TicketPriority.HIGH,
  urgent: TicketPriority.URGENT,
};

function text(value: unknown, fallback = '') {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

function date(value: unknown, fallback = new Date()) {
  const parsed = new Date(typeof value === 'string' || typeof value === 'number' ? value : fallback);
  return Number.isNaN(parsed.getTime()) ? fallback : parsed;
}

async function main() {
  const raw = JSON.parse(await readFile(sourcePath, 'utf8')) as LegacyDatabase;
  const customers = Array.isArray(raw.customers) ? raw.customers : [];
  const tickets = Array.isArray(raw.tickets) ? raw.tickets : [];
  const worklogs = Array.isArray(raw.worklogs) ? raw.worklogs : [];
  const users = Array.isArray(raw.users) ? raw.users : [];
  const invalidTickets = tickets.filter((item) => !text(item.id) || !text(item.customerId) || !text(item.title));
  const invalidWorklogs = worklogs.filter((item) => !text(item.content) || !item.time);

  console.log(JSON.stringify({
    mode: apply ? 'APPLY' : 'DRY_RUN',
    sourcePath,
    discovered: { users: users.length, customers: customers.length, tickets: tickets.length, worklogs: worklogs.length },
    skipped: { legacyUsers: users.length, invalidTickets: invalidTickets.length, invalidWorklogs: invalidWorklogs.length },
    note: 'V1 users and plaintext passwords are never imported. Internal work must be created as Work Items, not Tickets.',
  }, null, 2));

  if (!apply) {
    console.log('Dry run complete. Review the source, then rerun with --apply.');
    return;
  }

  const fallbackOwner = await prisma.user.findUnique({ where: { username: fallbackUsername } });
  if (!fallbackOwner) throw new Error(`V2 owner account not found: ${fallbackUsername}`);
  const otherWorkType = await prisma.workType.findUnique({ where: { code: 'other' } });
  if (!otherWorkType) throw new Error('Run db:seed before importing so the work type dictionary exists.');

  const userMap = new Map<string, string>();
  for (const legacyUser of users) {
    const username = text(legacyUser.username);
    if (!username) continue;
    const current = await prisma.user.findUnique({ where: { username } });
    if (current) userMap.set(text(legacyUser.id), current.id);
  }

  const customerMap = new Map<string, string>();
  for (const legacyCustomer of customers) {
    const name = text(legacyCustomer.name);
    if (!name) continue;
    const customer = await prisma.customerOrganization.upsert({
      where: { name },
      update: {},
      create: {
        name,
        industry: text(legacyCustomer.industry) || undefined,
        level: text(legacyCustomer.level) || undefined,
        notes: text(legacyCustomer.address) ? `V1 地址：${text(legacyCustomer.address)}` : '从 V1 导入',
        contacts: text(legacyCustomer.contact) ? { create: {
          name: text(legacyCustomer.contact),
          phone: text(legacyCustomer.phone) || undefined,
          email: text(legacyCustomer.email) || undefined,
          isPrimary: true,
        } } : undefined,
      },
    });
    customerMap.set(text(legacyCustomer.id), customer.id);

    const devices = Array.isArray(legacyCustomer.devices) ? legacyCustomer.devices as LegacyRecord[] : [];
    for (const device of devices) {
      const serialNumber = text(device.sn) || undefined;
      const existing = serialNumber
        ? await prisma.device.findFirst({ where: { organizationId: customer.id, serialNumber } })
        : null;
      if (!existing) await prisma.device.create({ data: {
        organizationId: customer.id,
        name: text(device.name, text(device.model, 'V1 设备')),
        cameraModel: text(device.model) || undefined,
        serialNumber,
      } });
    }
  }

  const ticketMap = new Map<string, string>();
  for (const legacyTicket of tickets) {
    const legacyId = text(legacyTicket.id);
    const organizationId = customerMap.get(text(legacyTicket.customerId));
    if (!legacyId || !organizationId || !text(legacyTicket.title)) continue;
    const assigneeId = userMap.get(text(legacyTicket.engineerId)) ?? fallbackOwner.id;
    const createdById = userMap.get(text(legacyTicket.creatorId)) ?? fallbackOwner.id;
    const status = statusMap[text(legacyTicket.status).toLowerCase()] ?? TicketStatus.PENDING;
    const ticket = await prisma.ticket.upsert({
      where: { number: legacyId },
      update: {},
      create: {
        number: legacyId,
        source: TicketSource.OTHER,
        organizationId,
        category: text(legacyTicket.category, 'V1 导入'),
        title: text(legacyTicket.title),
        description: text(legacyTicket.description, '从 V1 导入'),
        priority: priorityMap[text(legacyTicket.priority).toLowerCase()] ?? TicketPriority.MEDIUM,
        status,
        assigneeId,
        createdById,
        plannedAt: legacyTicket.dueDate ? date(legacyTicket.dueDate) : undefined,
        resolvedAt: status === TicketStatus.RESOLVED || status === TicketStatus.CLOSED ? date(legacyTicket.updatedAt) : undefined,
      },
    });
    ticketMap.set(legacyId, ticket.id);

    const comments = Array.isArray(legacyTicket.comments) ? legacyTicket.comments as LegacyRecord[] : [];
    if (comments.length && await prisma.ticketEvent.count({ where: { ticketId: ticket.id } }) === 0) {
      await prisma.ticketEvent.createMany({ data: comments.map((comment) => ({
        ticketId: ticket.id,
        authorId: userMap.get(text(comment.userId)) ?? fallbackOwner.id,
        type: TicketEventType.INTERNAL_NOTE,
        visibility: Visibility.INTERNAL,
        content: text(comment.content, 'V1 空备注'),
        createdAt: date(comment.createdAt),
      })) });
    }
  }

  let importedWorklogs = 0;
  for (const legacyWorklog of worklogs) {
    const summary = text(legacyWorklog.content);
    if (!summary || !legacyWorklog.time) continue;
    const legacyId = text(legacyWorklog.id);
    const marker = legacyId ? `v1:${legacyId}` : undefined;
    if (marker && await prisma.worklog.findFirst({ where: { aiExtractionId: marker } })) continue;
    await prisma.worklog.create({ data: {
      authorId: userMap.get(text(legacyWorklog.userId)) ?? fallbackOwner.id,
      workTypeId: otherWorkType.id,
      organizationId: customerMap.get(text(legacyWorklog.customerId)),
      ticketId: ticketMap.get(text(legacyWorklog.ticketId)),
      occurredAt: date(legacyWorklog.time),
      summary: summary.slice(0, 240),
      rawText: summary,
      aiExtractionId: marker,
      source: WorklogSource.IMPORT,
    } });
    importedWorklogs += 1;
  }

  console.log(`Import complete: ${customerMap.size} customers, ${ticketMap.size} tickets, ${importedWorklogs} work logs.`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
}).finally(() => prisma.$disconnect());
