import { describe, expect, it, vi } from 'vitest';
import { LinkageTasks } from './linkage.tasks.js';

const HOUR_MS = 60 * 60 * 1000;

function setup(overrides: {
  loans?: object[];
  repairs?: object[];
  latestRepairEvent?: Date | null;
  latestFollowUp?: Date | null;
  ownerId?: string | null;
  admins?: string[];
  notifiedRecently?: boolean;
  infoCompleteTimeoutHours?: number;
  repairFollowupTimeoutHours?: number;
} = {}) {
  const prisma = {
    loanOrder: { findMany: vi.fn().mockResolvedValue(overrides.loans ?? []) },
    repairOrder: { findMany: vi.fn().mockResolvedValue(overrides.repairs ?? []) },
    repairEvent: { findFirst: vi.fn().mockResolvedValue(overrides.latestRepairEvent === undefined ? { createdAt: new Date(Date.now() - 100 * HOUR_MS) } : overrides.latestRepairEvent ? { createdAt: overrides.latestRepairEvent } : null) },
    followUp: { findFirst: vi.fn().mockResolvedValue(overrides.latestFollowUp === undefined ? null : overrides.latestFollowUp ? { createdAt: overrides.latestFollowUp } : null) },
  };
  const config = {
    getAll: vi.fn().mockResolvedValue({
      defaultCreate: { loan: false, repair: false },
      infoCompleteTimeoutHours: overrides.infoCompleteTimeoutHours ?? 24,
      repairFollowupTimeoutHours: overrides.repairFollowupTimeoutHours ?? 48,
      notifyOnOverdue: true,
    }),
  };
  const linkageNotify = {
    ticketOwnerId: vi.fn().mockResolvedValue(overrides.ownerId === undefined ? 'owner-1' : overrides.ownerId),
    adminIds: vi.fn().mockResolvedValue(overrides.admins ?? []),
    hasNotifiedSince: vi.fn().mockResolvedValue(overrides.notifiedRecently ?? false),
    notifyUnreadOnce: vi.fn().mockResolvedValue(undefined),
  };
  const tasks = new LinkageTasks(prisma as never, config as never, linkageNotify as never);
  return { prisma, config, linkageNotify, tasks };
}

const staleLoan = { id: 'loan-1', loanNo: 'LN-260916-001', ticketId: 'ticket-1' };
const staleRepair = { id: 'repair-1', repairNo: 'RP-260916-001', assigneeId: 'engineer-1', ticketId: 'ticket-1', createdAt: new Date(Date.now() - 100 * HOUR_MS) };

describe('LinkageTasks 借测信息完善超时', () => {
  it('超时未完善 → 通知工单负责人，body 含小时数与单号', async () => {
    const { prisma, linkageNotify, tasks } = setup({ loans: [staleLoan] });
    await tasks.checkTimeouts();
    expect(prisma.loanOrder.findMany).toHaveBeenCalledWith(expect.objectContaining({
      where: expect.objectContaining({ status: 'QUEUED', infoComplete: false, deletedAt: null }),
    }));
    expect(linkageNotify.notifyUnreadOnce).toHaveBeenCalledWith(expect.objectContaining({
      recipientId: 'owner-1', ticketId: 'ticket-1', type: 'LINK_INFO_TIMEOUT', severity: 'WARNING',
      body: expect.stringContaining('借测单 LN-260916-001 信息超过 24 小时未完善，请尽快补全并评分'),
    }));
  });

  it('未超时的单子不会出现在扫描结果中（findMany 已按 createdAt 过滤）', async () => {
    const { linkageNotify, tasks } = setup({ loans: [] });
    await tasks.checkTimeouts();
    expect(linkageNotify.notifyUnreadOnce).not.toHaveBeenCalled();
  });

  it('近 20 小时内已提醒过 → 跳过', async () => {
    const { linkageNotify, tasks } = setup({ loans: [staleLoan], notifiedRecently: true });
    await tasks.checkTimeouts();
    expect(linkageNotify.hasNotifiedSince).toHaveBeenCalled();
    expect(linkageNotify.notifyUnreadOnce).not.toHaveBeenCalled();
  });

  it('自定义阈值写入提醒文案', async () => {
    const { linkageNotify, tasks } = setup({ loans: [staleLoan], infoCompleteTimeoutHours: 12 });
    await tasks.checkTimeouts();
    expect(linkageNotify.notifyUnreadOnce).toHaveBeenCalledWith(expect.objectContaining({
      body: expect.stringContaining('超过 12 小时未完善'),
    }));
  });
});

describe('LinkageTasks 维修无跟进超时', () => {
  it('最新事件/跟进均已超时 → 通知维修单负责人', async () => {
    const { prisma, linkageNotify, tasks } = setup({ repairs: [staleRepair] });
    await tasks.checkTimeouts();
    expect(prisma.repairOrder.findMany).toHaveBeenCalledWith(expect.objectContaining({
      where: expect.objectContaining({ status: { in: ['RECEIVED', 'DIAGNOSING', 'REPAIRING'] }, deletedAt: null }),
    }));
    expect(linkageNotify.notifyUnreadOnce).toHaveBeenCalledWith(expect.objectContaining({
      recipientId: 'engineer-1', type: 'LINK_REPAIR_NO_FOLLOWUP', severity: 'WARNING',
      body: expect.stringContaining('维修单 RP-260916-001 超过 48 小时无跟进'),
    }));
  });

  it('最新跟进未超时 → 不通知', async () => {
    const { linkageNotify, tasks } = setup({ repairs: [staleRepair], latestFollowUp: new Date(Date.now() - HOUR_MS) });
    await tasks.checkTimeouts();
    expect(linkageNotify.notifyUnreadOnce).not.toHaveBeenCalled();
  });

  it('无负责人时通知所有 admin', async () => {
    const { linkageNotify, tasks } = setup({ repairs: [{ ...staleRepair, assigneeId: null }], admins: ['admin-1', 'admin-2'] });
    await tasks.checkTimeouts();
    const recipients = linkageNotify.notifyUnreadOnce.mock.calls.map((call) => call[0].recipientId).sort();
    expect(recipients).toEqual(['admin-1', 'admin-2']);
  });

  it('近 20 小时内已提醒过 → 跳过', async () => {
    const { linkageNotify, tasks } = setup({ repairs: [staleRepair], notifiedRecently: true });
    await tasks.checkTimeouts();
    expect(linkageNotify.notifyUnreadOnce).not.toHaveBeenCalled();
  });
});
