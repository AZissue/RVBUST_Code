import { describe, expect, it, vi } from 'vitest';
import { LinkageService } from './linkage.service.js';

const user = { id: 'user-1', name: 'Alice', role: 'employee' } as never;
const ticket = {
  id: 'ticket-1', organizationId: 'org-1', contactId: 'contact-1', deviceId: 'device-1',
  serialNumber: 'SN123', description: '点云异常，需要借测与返修排查',
};

function setup(overrides: { activeLoan?: object | null; activeRepair?: object | null } = {}) {
  const prisma = {
    loanOrder: {
      findFirst: vi.fn().mockResolvedValue(overrides.activeLoan ?? null),
      findFirstOrThrow: vi.fn().mockResolvedValue(overrides.activeLoan ?? { id: 'loan-existing', loanNo: 'LN-260916-001', status: 'QUEUED' }),
      findMany: vi.fn().mockResolvedValue([]),
    },
    repairOrder: {
      findFirst: vi.fn().mockResolvedValue(overrides.activeRepair ?? null),
      findFirstOrThrow: vi.fn().mockResolvedValue(overrides.activeRepair ?? { id: 'repair-existing', repairNo: 'RP-260916-001', status: 'RECEIVED' }),
      findMany: vi.fn().mockResolvedValue([]),
    },
    ticketEvent: { create: vi.fn().mockResolvedValue({ id: 'event-1' }) },
  };
  const loans = { create: vi.fn().mockResolvedValue({ id: 'loan-new', loanNo: 'LN-260916-002', status: 'QUEUED' }) };
  const repairs = { create: vi.fn().mockResolvedValue({ id: 'repair-new', repairNo: 'RP-260916-002', status: 'RECEIVED' }) };
  const access = { requireTicket: vi.fn().mockResolvedValue(ticket) };
  const service = new LinkageService(prisma as never, loans as never, repairs as never, access as never);
  return { prisma, loans, repairs, service };
}

describe('LinkageService.createLoanFromTicket', () => {
  it('creates a loan with prefilled fields from the ticket and records LINK_CREATED', async () => {
    const { prisma, loans, service } = setup();
    const result = await service.createLoanFromTicket(user, ticket.id);
    expect(loans.create).toHaveBeenCalledWith(user, {
      organizationId: 'org-1', contactId: 'contact-1', ticketId: 'ticket-1',
      purpose: ticket.description.slice(0, 200),
    });
    expect(result.created).toBe(true);
    expect(prisma.ticketEvent.create).toHaveBeenCalledWith(expect.objectContaining({
      data: expect.objectContaining({
        type: 'LINK_CREATED', visibility: 'INTERNAL', ticketId: 'ticket-1',
        content: expect.stringContaining('LN-260916-002'),
        metadata: { linkType: 'loan', linkId: 'loan-new', linkNo: 'LN-260916-002' },
      }),
    }));
  });

  it('returns the existing active loan without creating a new one', async () => {
    const active = { id: 'loan-existing', loanNo: 'LN-260916-001', status: 'QUEUED' };
    const { prisma, loans, service } = setup({ activeLoan: active });
    const result = await service.createLoanFromTicket(user, ticket.id);
    expect(result).toEqual({ loan: active, created: false });
    expect(loans.create).not.toHaveBeenCalled();
    expect(prisma.ticketEvent.create).not.toHaveBeenCalled();
  });

  it('falls back to the existing loan when a concurrent create hits the unique index (P2002)', async () => {
    const { prisma, loans, service } = setup();
    loans.create.mockRejectedValue(Object.assign(new Error('unique'), { code: 'P2002' }));
    const result = await service.createLoanFromTicket(user, ticket.id);
    expect(result.created).toBe(false);
    expect(result.loan.loanNo).toBe('LN-260916-001');
    expect(prisma.ticketEvent.create).not.toHaveBeenCalled();
  });

  it('rethrows non-P2002 errors from loans.create', async () => {
    const { loans, service } = setup();
    loans.create.mockRejectedValue(new Error('客户组织不存在'));
    await expect(service.createLoanFromTicket(user, ticket.id)).rejects.toThrow('客户组织不存在');
  });
});

describe('LinkageService.createRepairFromTicket', () => {
  it('creates a repair with prefilled fields from the ticket and records LINK_CREATED', async () => {
    const { prisma, repairs, service } = setup();
    const result = await service.createRepairFromTicket(user, ticket.id);
    expect(repairs.create).toHaveBeenCalledWith(user, expect.objectContaining({
      organizationId: 'org-1', contactId: 'contact-1', deviceId: 'device-1',
      serialNumber: 'SN123', ticketId: 'ticket-1', symptom: ticket.description,
    }));
    expect(result.created).toBe(true);
    expect(prisma.ticketEvent.create).toHaveBeenCalledWith(expect.objectContaining({
      data: expect.objectContaining({
        type: 'LINK_CREATED',
        content: expect.stringContaining('RP-260916-002'),
        metadata: { linkType: 'repair', linkId: 'repair-new', linkNo: 'RP-260916-002' },
      }),
    }));
  });

  it('returns the existing active repair without creating a new one', async () => {
    const active = { id: 'repair-existing', repairNo: 'RP-260916-001', status: 'DIAGNOSING' };
    const { prisma, repairs, service } = setup({ activeRepair: active });
    const result = await service.createRepairFromTicket(user, ticket.id);
    expect(result).toEqual({ repair: active, created: false });
    expect(repairs.create).not.toHaveBeenCalled();
    expect(prisma.ticketEvent.create).not.toHaveBeenCalled();
  });
});

describe('LinkageService.listLinks', () => {
  it('returns loans and repairs for a visible ticket, newest first', async () => {
    const { prisma, service } = setup();
    await service.listLinks(user, ticket.id);
    expect(prisma.loanOrder.findMany).toHaveBeenCalledWith(expect.objectContaining({
      where: { ticketId: 'ticket-1', deletedAt: null },
      orderBy: { createdAt: 'desc' },
    }));
    expect(prisma.repairOrder.findMany).toHaveBeenCalledWith(expect.objectContaining({
      where: { ticketId: 'ticket-1', deletedAt: null },
      orderBy: { createdAt: 'desc' },
    }));
  });
});
