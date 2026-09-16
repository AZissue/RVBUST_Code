import { describe, it, expect, vi } from 'vitest';
import { TicketsService } from './tickets.service.js';

function setup(count = 1) {
  const ticket = { id: 'ticket', status: 'PENDING', updatedAt: new Date(), assigneeId: 'actor' };
  const updated = { number: 'TS-1', title: 'Test', createdBy: { id: 'creator' }, assignee: { id: 'actor' }, collaborators: [{ user: { id: 'creator' } }, { user: { id: 'collaborator' } }] };
  const tx = { ticket: { updateMany: vi.fn().mockResolvedValue({ count }), findUniqueOrThrow: vi.fn().mockResolvedValue(updated) }, ticketEvent: { create: vi.fn().mockResolvedValue({ id: 'event' }) }, notification: { createMany: vi.fn().mockResolvedValue({ count: 2 }) } };
  const prisma = { $transaction: (fn: (db: typeof tx) => unknown) => fn(tx) };
  const access = { requireTicket: vi.fn().mockResolvedValue(ticket) };
  const service = new TicketsService(prisma as never, access as never, {} as never, {} as never, { emit: vi.fn() } as never);
  const change = () => service.changeStatus({ id: 'actor', name: 'Alice', role: 'employee' } as never, 'ticket', { status: 'IN_PROGRESS' });
  return { tx, change };
}

describe('ticket status notifications', () => {
  it('notifies creator and collaborators once, excluding the actor', async () => {
    const { tx, change } = setup();
    await change();
    expect(tx.notification.createMany.mock.calls[0][0].data.map((n: { recipientId: string }) => n.recipientId)).toEqual(['creator', 'collaborator']);
    expect(tx.notification.createMany.mock.calls[0][0].data[0].body).toContain('Alice');
  });
  it('does not write an event or notification after a concurrent change', async () => {
    const { tx, change } = setup(0);
    await expect(change()).rejects.toThrow('工单已被其他人修改');
    expect(tx.ticketEvent.create).not.toHaveBeenCalled();
    expect(tx.notification.createMany).not.toHaveBeenCalled();
  });
  it('fails the transaction when notification persistence fails', async () => {
    const { tx, change } = setup();
    tx.notification.createMany.mockRejectedValue(new Error('database failure'));
    await expect(change()).rejects.toThrow('database failure');
  });
});

describe('ticket create with loan/repair linkage', () => {
  function setupCreate(linkageOverrides: Record<string, unknown> = {}) {
    const ticket = { id: 'ticket-1', number: 'RVC-260916-001' };
    const prisma = {
      ticket: {
        findUnique: vi.fn().mockResolvedValue(null),
        findFirst: vi.fn().mockResolvedValue(null),
        create: vi.fn().mockResolvedValue(ticket),
      },
    };
    const access = { requireCustomer: vi.fn().mockResolvedValue({ id: 'org-1' }) };
    const linkage = {
      createLoanFromTicket: vi.fn().mockResolvedValue({ created: true }),
      createRepairFromTicket: vi.fn().mockResolvedValue({ created: true }),
      ...linkageOverrides,
    };
    const service = new TicketsService(prisma as never, access as never, {} as never, linkage as never, { emit: vi.fn() } as never);
    const dto: import('./dto/ticket.dto.js').CreateTicketDto = { organizationId: 'org-1', title: '有效标题', description: '有效的问题描述内容', category: 'OTHER' as never };
    const user = { id: 'user-1', name: 'Alice', role: 'employee' } as never;
    return { service, dto, user, linkage, ticket };
  }

  it('does not touch linkage when no flags are set', async () => {
    const { service, dto, user, linkage } = setupCreate();
    await service.create(user, dto);
    expect(linkage.createLoanFromTicket).not.toHaveBeenCalled();
    expect(linkage.createRepairFromTicket).not.toHaveBeenCalled();
  });

  it('creates linked loan and repair when both flags are set', async () => {
    const { service, dto, user, linkage, ticket } = setupCreate();
    await service.create(user, { ...dto, createLinkedLoan: true, createLinkedRepair: true });
    expect(linkage.createLoanFromTicket).toHaveBeenCalledWith(user, ticket.id);
    expect(linkage.createRepairFromTicket).toHaveBeenCalledWith(user, ticket.id);
  });

  it('only creates the linked loan when only createLinkedLoan is set', async () => {
    const { service, dto, user, linkage } = setupCreate();
    await service.create(user, { ...dto, createLinkedLoan: true });
    expect(linkage.createLoanFromTicket).toHaveBeenCalledTimes(1);
    expect(linkage.createRepairFromTicket).not.toHaveBeenCalled();
  });

  it('keeps the ticket when a linkage creation fails', async () => {
    const { service, dto, user, linkage, ticket } = setupCreate({
      createLoanFromTicket: vi.fn().mockRejectedValue(new Error('客户组织不存在')),
    });
    const created = await service.create(user, { ...dto, createLinkedLoan: true, createLinkedRepair: true });
    expect(created).toMatchObject({ id: ticket.id });
    expect(linkage.createRepairFromTicket).toHaveBeenCalledWith(user, ticket.id);
  });
});
