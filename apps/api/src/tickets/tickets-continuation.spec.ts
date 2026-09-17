import { describe, expect, it, vi } from 'vitest';
import { TicketsService } from './tickets.service.js';

/** create() 走默认 db=prisma（无外层事务），接续与创建同库顺序执行 */
function setup(options: {
  predecessor?: Record<string, unknown> | null
  existed?: { toTicket: { number: string } } | null
  activeLoans?: { id: string; loanNo: string }[]
  activeRepairs?: { id: string; repairNo: string }[]
} = {}) {
  const predecessor = options.predecessor ?? { id: 'from-1', number: 'RVC-260901-001', title: '售前评估', status: 'IN_PROGRESS', organizationId: 'org-1', deletedAt: null, assigneeId: 'owner', createdById: 'creator' };
  const prisma = {
    user: { findFirst: vi.fn().mockResolvedValue({ id: 'u1' }) },
    ticket: {
      findUnique: vi.fn().mockResolvedValue(null),
      findFirst: vi.fn().mockResolvedValue(null),
      findMany: vi.fn().mockResolvedValue(predecessor ? [predecessor] : []),
      create: vi.fn().mockResolvedValue({ id: 'new-1', number: 'RVC-260917-001', organizationId: 'org-1', linkageErrors: [] }),
      update: vi.fn().mockResolvedValue({}),
    },
    ticketEvent: { create: vi.fn().mockResolvedValue({ id: 'ev' }) },
    ticketContinuation: {
      findFirst: vi.fn().mockResolvedValue(options.existed ?? null),
      create: vi.fn().mockResolvedValue({ id: 'link-1' }),
    },
    loanOrder: { findMany: vi.fn().mockResolvedValue(options.activeLoans ?? []), update: vi.fn().mockResolvedValue({}) },
    repairOrder: { findMany: vi.fn().mockResolvedValue(options.activeRepairs ?? []), update: vi.fn().mockResolvedValue({}) },
  };
  const access = { requireCustomer: vi.fn().mockResolvedValue(undefined), ticketWhere: vi.fn().mockReturnValue({}) };
  const notifications = { notify: vi.fn().mockResolvedValue(undefined) };
  const service = new TicketsService(prisma as never, access as never, notifications as never, {} as never, { emit: vi.fn() } as never);
  const create = (overrides: Record<string, unknown> = {}) => service.create(
    { id: 'actor', name: 'Alice', role: 'admin' } as never,
    {
      organizationId: 'org-1', category: 'PRE_SALES', title: '测试反馈工单', description: '客户测试反馈描述',
      continuations: [{ fromTicketId: 'from-1', note: '样品已寄出，待测试反馈' }],
      ...overrides,
    } as never,
  );
  return { prisma, notifications, create };
}

describe('工单接续（create + continuations）', () => {
  it('默认自动关单：前置单置 CLOSED 且 solution=接续说明，双向 LINK_CREATED 时间线 + 状态变更 + 通知原负责人与创建人', async () => {
    const { prisma, notifications, create } = setup();
    await create();
    expect(prisma.ticket.update).toHaveBeenCalledWith(expect.objectContaining({ where: { id: 'from-1' }, data: expect.objectContaining({ status: 'CLOSED', solution: '样品已寄出，待测试反馈' }) }));
    const events = prisma.ticketEvent.create.mock.calls.map((call) => call[0].data);
    const fromLink = events.find((e) => e.ticketId === 'from-1' && e.type === 'LINK_CREATED');
    expect(fromLink.content).toContain('接续跟进');
    expect(fromLink.content).toContain('样品已寄出');
    const toLink = events.find((e) => e.ticketId === 'new-1' && e.type === 'LINK_CREATED');
    expect(toLink.content).toContain('接续自 RVC-260901-001');
    expect(events.some((e) => e.ticketId === 'from-1' && e.type === 'STATUS_CHANGE' && e.content.includes('已关闭'))).toBe(true);
    const recipients = notifications.notify.mock.calls.map((call) => call[0].recipientId).sort();
    expect(recipients).toEqual(['creator', 'owner']);
    expect(notifications.notify.mock.calls[0][0].body).toContain('原工单已关闭');
  });

  it('autoClose=false：仅关联不关闭，文案为「关联引用」', async () => {
    const { prisma, notifications, create } = setup();
    await create({ autoClose: false });
    expect(prisma.ticket.update).not.toHaveBeenCalled();
    const events = prisma.ticketEvent.create.mock.calls.map((call) => call[0].data);
    expect(events.find((e) => e.ticketId === 'from-1').content).toContain('关联引用');
    expect(notifications.notify.mock.calls[0][0].body).toContain('关联引用');
  });

  it('前置单已关闭时拒绝', async () => {
    const { create } = setup({ predecessor: { id: 'from-1', number: 'RVC-260901-001', title: 'x', status: 'CLOSED', organizationId: 'org-1', deletedAt: null, assigneeId: 'owner', createdById: 'creator' } });
    await expect(create()).rejects.toThrow('已关闭，不能接续');
  });

  it('不同客户的前置单拒绝', async () => {
    const { create } = setup({ predecessor: { id: 'from-1', number: 'RVC-260901-001', title: 'x', status: 'IN_PROGRESS', organizationId: 'org-OTHER', deletedAt: null, assigneeId: null, createdById: 'creator' } });
    await expect(create()).rejects.toThrow('与该客户不一致');
  });

  it('前置单已被接续过时拒绝', async () => {
    const { create } = setup({ existed: { toTicket: { number: 'RVC-260916-009' } } });
    await expect(create()).rejects.toThrow('已被 RVC-260916-009 接续');
  });

  it('存在进行中维修单且未勾选迁移时拒绝关单并给出单号', async () => {
    const { create } = setup({ activeRepairs: [{ id: 'rp-1', repairNo: 'RP-260916-001' }] });
    await expect(create()).rejects.toThrow('RP-260916-001');
    await expect(create()).rejects.toThrow('迁移关联业务到新单');
  });

  it('carryLinks=true：进行中借测单 ticketId 迁移到新单并双向留痕', async () => {
    const { prisma, create } = setup({ activeLoans: [{ id: 'ln-1', loanNo: 'LN-260916-001' }] });
    await create({ carryLinks: true });
    expect(prisma.loanOrder.update).toHaveBeenCalledWith(expect.objectContaining({ where: { id: 'ln-1' }, data: { ticketId: 'new-1' } }));
    const events = prisma.ticketEvent.create.mock.calls.map((call) => call[0].data);
    expect(events.some((e) => e.ticketId === 'from-1' && e.content.includes('LN-260916-001') && e.content.includes('接续迁移'))).toBe(true);
    expect(events.some((e) => e.ticketId === 'new-1' && e.content.includes('承接迁移自'))).toBe(true);
  });

  it('接续说明过短时服务端拒绝（2-500 字）', async () => {
    const { create } = setup();
    await expect(create({ continuations: [{ fromTicketId: 'from-1', note: '短' }] })).rejects.toThrow('接续说明需为 2-500 字');
  });
});
