import { describe, it, expect, vi } from 'vitest';
import { TicketsService } from './tickets.service.js';

function setup(count = 1) {
  const ticket = { id: 'ticket', status: 'PENDING', updatedAt: new Date(), assigneeId: 'actor' };
  const updated = { number: 'TS-1', title: 'Test', createdBy: { id: 'creator' }, assignee: { id: 'actor' }, collaborators: [{ user: { id: 'creator' } }, { user: { id: 'collaborator' } }] };
  const tx = { ticket: { updateMany: vi.fn().mockResolvedValue({ count }), findUniqueOrThrow: vi.fn().mockResolvedValue(updated) }, ticketEvent: { create: vi.fn().mockResolvedValue({ id: 'event' }) }, notification: { createMany: vi.fn().mockResolvedValue({ count: 2 }) } };
  const prisma = { $transaction: (fn: (db: typeof tx) => unknown) => fn(tx) };
  const access = { requireTicket: vi.fn().mockResolvedValue(ticket) };
  const service = new TicketsService(prisma as never, access as never, {} as never);
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
