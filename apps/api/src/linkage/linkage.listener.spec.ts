import { describe, expect, it, vi } from 'vitest';
import { LinkageListener } from './linkage.listener.js';
import { LINKAGE_EVENTS, type LoanScoredPayload, type LoanStatusChangedPayload, type LoanFollowUpAddedPayload, type RepairFollowUpAddedPayload, type RepairStatusChangedPayload, type TicketCustomerReplyPayload } from './linkage.events.js';

function setup(overrides: { loans?: object[]; repairs?: object[]; activeLoans?: number; activeRepairs?: number; notifyOnOverdue?: boolean; ownerId?: string | null } = {}) {
  const prisma = {
    ticketEvent: { create: vi.fn().mockResolvedValue({ id: 'event-1' }) },
    followUp: { createMany: vi.fn().mockResolvedValue({ count: 1 }) },
    loanOrder: { findMany: vi.fn().mockResolvedValue(overrides.loans ?? []), count: vi.fn().mockResolvedValue(overrides.activeLoans ?? 0) },
    repairOrder: { findMany: vi.fn().mockResolvedValue(overrides.repairs ?? []), count: vi.fn().mockResolvedValue(overrides.activeRepairs ?? 0) },
  };
  const linkageNotify = {
    ticketOwnerId: vi.fn().mockResolvedValue(overrides.ownerId === undefined ? 'owner-1' : overrides.ownerId),
    safeNotifyUnreadOnce: vi.fn().mockResolvedValue(undefined),
  };
  const config = {
    getAll: vi.fn().mockResolvedValue({
      defaultCreate: { loan: false, repair: false },
      infoCompleteTimeoutHours: 24, repairFollowupTimeoutHours: 48,
      notifyOnOverdue: overrides.notifyOnOverdue ?? true,
    }),
  };
  const listener = new LinkageListener(prisma as never, linkageNotify as never, config as never);
  return { prisma, linkageNotify, config, listener };
}

const base = { ticketId: 'ticket-1', actorId: 'user-1' };

describe('LinkageListener 反向同步（子单 → 工单时间线）', () => {
  it('loan.scored → 写 LINK_UPDATE 评分事件与 metadata', async () => {
    const { prisma, listener } = setup();
    const payload: LoanScoredPayload = { ...base, loanId: 'loan-1', loanNo: 'LN-260916-001', score: 85, assessmentResult: null };
    await listener.onLoanScored(payload);
    expect(prisma.ticketEvent.create).toHaveBeenCalledWith({
      data: {
        ticketId: 'ticket-1', authorId: 'user-1', type: 'LINK_UPDATE', visibility: 'INTERNAL',
        content: '借测单 LN-260916-001 评分 85 分',
        metadata: { linkType: 'loan', linkId: 'loan-1', linkNo: 'LN-260916-001', syncedFrom: 'linkage' },
      },
    });
  });

  it('loan.scored 带评估结论时追加前 100 字', async () => {
    const { prisma, listener } = setup();
    const long = 'a'.repeat(150);
    await listener.onLoanScored({ ...base, loanId: 'loan-1', loanNo: 'LN-1', score: 60, assessmentResult: long });
    const content = prisma.ticketEvent.create.mock.calls[0][0].data.content as string;
    expect(content).toContain('评分 60 分，评估结论：');
    expect(content).toContain('a'.repeat(100));
    expect(content).not.toContain('a'.repeat(101));
  });

  it('loan.infoCompleted → 写信息已完善事件', async () => {
    const { prisma, listener } = setup();
    await listener.onLoanInfoCompleted({ ...base, loanId: 'loan-1', loanNo: 'LN-1' });
    expect(prisma.ticketEvent.create).toHaveBeenCalledWith(expect.objectContaining({
      data: expect.objectContaining({ type: 'LINK_UPDATE', content: '借测单 LN-1 借测信息已完善' }),
    }));
  });

  it('loan.statusChanged → 按目标状态写中文文案（已归还）', async () => {
    const { prisma, listener } = setup();
    const payload: LoanStatusChangedPayload = { ...base, loanId: 'loan-1', loanNo: 'LN-1', from: 'OVERDUE' as never, to: 'RETURNED' as never };
    await listener.onLoanStatusChanged(payload);
    expect(prisma.ticketEvent.create).toHaveBeenCalledWith(expect.objectContaining({
      data: expect.objectContaining({
        content: '借测单 LN-1 已归还',
        metadata: expect.objectContaining({ linkType: 'loan', from: 'OVERDUE', to: 'RETURNED' }),
      }),
    }));
  });

  it('repair.statusChanged → 写维修单状态文案（诊断中）', async () => {
    const { prisma, listener } = setup();
    const payload: RepairStatusChangedPayload = { ...base, repairId: 'repair-1', repairNo: 'RP-1', from: 'RECEIVED' as never, to: 'DIAGNOSING' as never };
    await listener.onRepairStatusChanged(payload);
    expect(prisma.ticketEvent.create).toHaveBeenCalledWith(expect.objectContaining({
      data: expect.objectContaining({
        content: '维修单 RP-1 诊断中',
        metadata: expect.objectContaining({ linkType: 'repair', linkId: 'repair-1', linkNo: 'RP-1', syncedFrom: 'linkage' }),
      }),
    }));
  });

  it('loan.followUpAdded（WEB）→ 写跟进事件，内容截断前 100 字', async () => {
    const { prisma, listener } = setup();
    const payload: LoanFollowUpAddedPayload = { ...base, loanId: 'loan-1', loanNo: 'LN-1', content: 'x'.repeat(150), source: 'WEB' };
    await listener.onLoanFollowUpAdded(payload);
    const content = prisma.ticketEvent.create.mock.calls[0][0].data.content as string;
    expect(content.startsWith('借测单 LN-1 跟进：')).toBe(true);
    expect(content).toContain('x'.repeat(100));
    expect(content).not.toContain('x'.repeat(101));
  });

  it('repair.followUpAdded（WEB）→ 写维修跟进事件', async () => {
    const { prisma, listener } = setup();
    const payload: RepairFollowUpAddedPayload = { ...base, repairId: 'repair-1', repairNo: 'RP-1', content: '已更换主板', source: 'WEB' };
    await listener.onRepairFollowUpAdded(payload);
    expect(prisma.ticketEvent.create).toHaveBeenCalledWith(expect.objectContaining({
      data: expect.objectContaining({ content: '维修单 RP-1 跟进：已更换主板' }),
    }));
  });

  it('ticketId 为空的子单事件一律跳过，不写时间线', async () => {
    const { prisma, listener } = setup();
    await listener.onLoanScored({ ticketId: null, actorId: 'user-1', loanId: 'l', loanNo: 'LN-1', score: 90, assessmentResult: null });
    await listener.onLoanInfoCompleted({ ticketId: null, actorId: 'user-1', loanId: 'l', loanNo: 'LN-1' });
    await listener.onLoanStatusChanged({ ticketId: null, actorId: 'user-1', loanId: 'l', loanNo: 'LN-1', from: 'QUEUED' as never, to: 'ONGOING' as never });
    await listener.onLoanFollowUpAdded({ ticketId: null, actorId: 'user-1', loanId: 'l', loanNo: 'LN-1', content: 'c', source: 'WEB' });
    await listener.onRepairStatusChanged({ ticketId: null, actorId: 'user-1', repairId: 'r', repairNo: 'RP-1', from: 'RECEIVED' as never, to: 'CLOSED' as never });
    expect(prisma.ticketEvent.create).not.toHaveBeenCalled();
  });

  it('source=SYSTEM 的跟进不回写（防 A→B→A 回声）', async () => {
    const { prisma, listener } = setup();
    await listener.onLoanFollowUpAdded({ ...base, loanId: 'l', loanNo: 'LN-1', content: '客户回复：你好', source: 'SYSTEM' });
    await listener.onRepairFollowUpAdded({ ...base, repairId: 'r', repairNo: 'RP-1', content: '客户回复：你好', source: 'SYSTEM' });
    expect(prisma.ticketEvent.create).not.toHaveBeenCalled();
  });

  it('时间线写入失败时不抛出（不影响主流程）', async () => {
    const { prisma, listener } = setup();
    prisma.ticketEvent.create.mockRejectedValue(new Error('db down'));
    await expect(listener.onLoanScored({ ...base, loanId: 'l', loanNo: 'LN-1', score: 80, assessmentResult: null })).resolves.toBeUndefined();
  });
});

describe('LinkageListener 正向同步（工单客户回复 → 子单跟进）', () => {
  it('为进行中借测单与维修单各生成一条 SYSTEM FollowUp，不回写工单', async () => {
    const { prisma, listener } = setup({ loans: [{ id: 'loan-1' }], repairs: [{ id: 'repair-1' }] });
    const payload: TicketCustomerReplyPayload = { ticketId: 'ticket-1', actorId: 'user-1', content: 'y'.repeat(250) };
    await listener.onTicketCustomerReply(payload);
    expect(prisma.loanOrder.findMany).toHaveBeenCalledWith(expect.objectContaining({
      where: expect.objectContaining({ ticketId: 'ticket-1', deletedAt: null }),
    }));
    expect(prisma.followUp.createMany).toHaveBeenCalledTimes(1);
    const data = prisma.followUp.createMany.mock.calls[0][0].data as Array<Record<string, unknown>>;
    expect(data).toHaveLength(2);
    expect(data[0]).toMatchObject({ loanOrderId: 'loan-1', ticketId: 'ticket-1', authorId: 'user-1', source: 'SYSTEM' });
    expect(data[1]).toMatchObject({ repairOrderId: 'repair-1', ticketId: 'ticket-1', authorId: 'user-1', source: 'SYSTEM' });
    for (const row of data) {
      expect(String(row.content).startsWith('客户回复：')).toBe(true);
      expect(String(row.content)).toContain('y'.repeat(200));
      expect(String(row.content)).not.toContain('y'.repeat(201));
      expect(row.occurredAt).toBeInstanceOf(Date);
    }
    expect(prisma.ticketEvent.create).not.toHaveBeenCalled();
  });

  it('没有进行中子单时不做任何写入', async () => {
    const { prisma, listener } = setup();
    await listener.onTicketCustomerReply({ ticketId: 'ticket-1', actorId: 'user-1', content: 'hello' });
    expect(prisma.followUp.createMany).not.toHaveBeenCalled();
    expect(prisma.ticketEvent.create).not.toHaveBeenCalled();
  });

  it('查询失败时不抛出（不影响主流程）', async () => {
    const { prisma, listener } = setup();
    prisma.loanOrder.findMany.mockRejectedValue(new Error('db down'));
    await expect(listener.onTicketCustomerReply({ ticketId: 'ticket-1', actorId: 'user-1', content: 'hello' })).resolves.toBeUndefined();
  });
});

describe('LinkageListener 维修闭环事件', () => {
  it('repair CLOSED 带 resolution → 写「已完结并返回客户，结论：前200字」', async () => {
    const { prisma, listener } = setup();
    const resolution = 'r'.repeat(250);
    await listener.onRepairStatusChanged({ ...base, repairId: 'repair-1', repairNo: 'RP-1', from: 'SHIPPED' as never, to: 'CLOSED' as never, resolution });
    const content = prisma.ticketEvent.create.mock.calls[0][0].data.content as string;
    expect(content).toContain('维修单 RP-1 已完结并返回客户，结论：');
    expect(content).toContain('r'.repeat(200));
    expect(content).not.toContain('r'.repeat(201));
  });

  it('repair CLOSED 无 resolution → 保持「已关闭」文案', async () => {
    const { prisma, listener } = setup();
    await listener.onRepairStatusChanged({ ...base, repairId: 'repair-1', repairNo: 'RP-1', from: 'SHIPPED' as never, to: 'CLOSED' as never });
    expect(prisma.ticketEvent.create).toHaveBeenCalledWith(expect.objectContaining({
      data: expect.objectContaining({ content: '维修单 RP-1 已关闭' }),
    }));
  });
});

describe('LinkageListener 联动通知', () => {
  const overduePayload: LoanStatusChangedPayload = { ...base, loanId: 'loan-1', loanNo: 'LN-1', from: 'ONGOING' as never, to: 'OVERDUE' as never };

  it('loan OVERDUE → 通知工单负责人（借测单已逾期，需联系客户）', async () => {
    const { linkageNotify, listener } = setup();
    await listener.onLoanStatusChanged(overduePayload);
    expect(linkageNotify.ticketOwnerId).toHaveBeenCalledWith('ticket-1');
    expect(linkageNotify.safeNotifyUnreadOnce).toHaveBeenCalledWith(expect.objectContaining({
      recipientId: 'owner-1', ticketId: 'ticket-1', type: 'LINK_LOAN_OVERDUE', severity: 'WARNING',
      body: expect.stringContaining('借测单 LN-1 已逾期，需联系客户'),
    }));
  });

  it('linkage.notifyOnOverdue=false 时 OVERDUE 不通知', async () => {
    const { linkageNotify, listener } = setup({ notifyOnOverdue: false });
    await listener.onLoanStatusChanged(overduePayload);
    expect(linkageNotify.safeNotifyUnreadOnce).not.toHaveBeenCalled();
  });

  it('工单无负责人且无创建人时 OVERDUE 不通知', async () => {
    const { linkageNotify, listener } = setup({ ownerId: null });
    await listener.onLoanStatusChanged(overduePayload);
    expect(linkageNotify.safeNotifyUnreadOnce).not.toHaveBeenCalled();
  });

  it('借测单归还且无进行中子单 → 通知负责人可关单', async () => {
    const { linkageNotify, listener } = setup();
    await listener.onLoanStatusChanged({ ...base, loanId: 'loan-1', loanNo: 'LN-1', from: 'OVERDUE' as never, to: 'RETURNED' as never });
    expect(linkageNotify.safeNotifyUnreadOnce).toHaveBeenCalledWith(expect.objectContaining({
      recipientId: 'owner-1', type: 'LINK_ALL_COMPLETED',
      body: expect.stringContaining('工单关联业务已完结，可标记解决并关闭工单'),
    }));
  });

  it('仍有进行中维修单时归还借测单 → 不发全部完结通知', async () => {
    const { linkageNotify, listener } = setup({ activeRepairs: 1 });
    await listener.onLoanStatusChanged({ ...base, loanId: 'loan-1', loanNo: 'LN-1', from: 'OVERDUE' as never, to: 'RETURNED' as never });
    expect(linkageNotify.safeNotifyUnreadOnce).not.toHaveBeenCalled();
  });

  it('维修单 CLOSED 且无进行中子单 → 通知负责人可关单', async () => {
    const { linkageNotify, listener } = setup();
    await listener.onRepairStatusChanged({ ...base, repairId: 'repair-1', repairNo: 'RP-1', from: 'SHIPPED' as never, to: 'CLOSED' as never, resolution: 'ok' });
    expect(linkageNotify.safeNotifyUnreadOnce).toHaveBeenCalledWith(expect.objectContaining({
      recipientId: 'owner-1', type: 'LINK_ALL_COMPLETED',
    }));
  });
});

describe('LINKAGE_EVENTS 事件名', () => {
  it('与需求约定一致', () => {
    expect(LINKAGE_EVENTS).toEqual({
      loanScored: 'loan.scored',
      loanInfoCompleted: 'loan.infoCompleted',
      loanStatusChanged: 'loan.statusChanged',
      loanFollowUpAdded: 'loan.followUpAdded',
      repairStatusChanged: 'repair.statusChanged',
      repairFollowUpAdded: 'repair.followUpAdded',
      ticketCustomerReply: 'ticket.customerReply',
    });
  });
});
