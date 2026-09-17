import { describe, expect, it, vi } from 'vitest';
import { DashboardService } from './dashboard.service.js';

const HOUR_MS = 60 * 60 * 1000;

function setup() {
  const prisma = {
    loanOrder: { findMany: vi.fn().mockResolvedValue([]), count: vi.fn().mockResolvedValue(0) },
    repairOrder: { findMany: vi.fn().mockResolvedValue([]), count: vi.fn().mockResolvedValue(0) },
  };
  const access = { requireInternal: vi.fn() };
  const linkageConfig = {
    getAll: vi.fn().mockResolvedValue({ infoCompleteTimeoutHours: 24, repairFollowupTimeoutHours: 48, notifyOnOverdue: true, defaultCreate: { loan: false, repair: false } }),
  };
  const service = new DashboardService(prisma as never, access as never, linkageConfig as never);
  return { prisma, access, linkageConfig, service };
}

const employee = { id: 'user-1', name: '员工甲', role: 'employee' } as never;
const admin = { id: 'admin-1', name: '管理员', role: 'admin' } as never;

describe('DashboardService.linkageTodos', () => {
  it('scopes loan todos to ticket assignee or loan creator and computes pendingHours', async () => {
    const { prisma, service } = setup();
    const createdAt = new Date(Date.now() - 26 * HOUR_MS);
    prisma.loanOrder.findMany.mockResolvedValue([
      { id: 'loan-1', loanNo: 'LN-1', ticketId: 'ticket-1', createdAt, dueAt: null, ticket: { id: 'ticket-1', number: 'TK-1', title: '借测申请' } },
    ]);
    const result = await service.linkageTodos(employee);
    // 归属规则写入 where：工单负责人 = 当前用户 或 创建人 = 当前用户
    expect(prisma.loanOrder.findMany).toHaveBeenCalledWith(expect.objectContaining({
      where: expect.objectContaining({
        status: 'QUEUED', infoComplete: false, deletedAt: null,
        OR: [{ ticket: { is: { assigneeId: 'user-1' } } }, { createdById: 'user-1' }],
      }),
    }));
    expect(result.infoIncomplete.total).toBe(0);
    expect(result.infoIncomplete.items).toEqual([
      { loanId: 'loan-1', loanNo: 'LN-1', ticketId: 'ticket-1', ticketNumber: 'TK-1', title: '借测申请', pendingHours: 26 },
    ]);
    // toScore 与 loansOverdue 用同一归属规则
    const scoreWhere = prisma.loanOrder.findMany.mock.calls[1][0].where;
    expect(scoreWhere).toEqual(expect.objectContaining({ infoComplete: true, score: null, OR: [{ ticket: { is: { assigneeId: 'user-1' } } }, { createdById: 'user-1' }] }));
    const overdueWhere = prisma.loanOrder.findMany.mock.calls[2][0].where;
    expect(overdueWhere).toEqual(expect.objectContaining({ status: 'OVERDUE', OR: [{ ticket: { is: { assigneeId: 'user-1' } } }, { createdById: 'user-1' }] }));
  });

  it('uses counts for totals and keeps at most 5 newest items per group', async () => {
    const { prisma, service } = setup();
    prisma.loanOrder.count.mockResolvedValue(7);
    prisma.loanOrder.findMany.mockResolvedValue([]);
    const result = await service.linkageTodos(employee);
    expect(result.infoIncomplete.total).toBe(7);
    expect(result.toScore.total).toBe(7);
    expect(result.loansOverdue.total).toBe(7);
    for (const call of prisma.loanOrder.findMany.mock.calls) {
      expect(call[0]).toEqual(expect.objectContaining({ take: 5, orderBy: { createdAt: 'desc' } }));
    }
  });

  it('lets admins see unassigned stalled repairs while regular members only see their own', async () => {
    const { prisma, service } = setup();
    await service.linkageTodos(employee);
    const employeeWhere = prisma.repairOrder.findMany.mock.calls[0][0].where;
    expect(employeeWhere.OR).toEqual([{ assigneeId: 'user-1' }]);
    prisma.repairOrder.findMany.mockClear();
    await service.linkageTodos(admin);
    const adminWhere = prisma.repairOrder.findMany.mock.calls[0][0].where;
    expect(adminWhere.OR).toEqual([{ assigneeId: 'admin-1' }, { assigneeId: null }]);
  });

  it('filters stalled repairs by the configured timeout and computes stalledHours from latest activity', async () => {
    const { prisma, linkageConfig, service } = setup();
    linkageConfig.getAll.mockResolvedValue({ infoCompleteTimeoutHours: 24, repairFollowupTimeoutHours: 12, notifyOnOverdue: true, defaultCreate: { loan: false, repair: false } });
    const createdAt = new Date(Date.now() - 60 * HOUR_MS);
    const latestEventAt = new Date(Date.now() - 20 * HOUR_MS);
    prisma.repairOrder.findMany.mockResolvedValue([
      {
        id: 'repair-1', repairNo: 'RP-1', ticketId: 'ticket-2', createdAt,
        events: [{ createdAt: latestEventAt }], followUps: [],
        ticket: { id: 'ticket-2', number: 'TK-2', title: '硬件故障' },
      },
    ]);
    prisma.repairOrder.count.mockResolvedValue(1);
    const result = await service.linkageTodos(admin);
    const where = prisma.repairOrder.findMany.mock.calls[0][0].where;
    const deadline = new Date(Date.now() - 12 * HOUR_MS);
    expect(where.status).toEqual({ in: ['RECEIVED', 'DIAGNOSING', 'REPAIRING', 'SHIPPED'] });
    expect(where.createdAt.lt.getTime()).toBeCloseTo(deadline.getTime(), -5);
    expect(where.events).toEqual({ none: { createdAt: { gte: expect.any(Date) } } });
    expect(result.repairsStalled.total).toBe(1);
    expect(result.repairsStalled.items).toEqual([
      { repairId: 'repair-1', repairNo: 'RP-1', ticketId: 'ticket-2', ticketNumber: 'TK-2', title: '硬件故障', stalledHours: 20 },
    ]);
  });

  it('computes overdueDays from dueAt (fallback to createdAt) and empty title without ticket', async () => {
    const { prisma, service } = setup();
    prisma.loanOrder.findMany.mockImplementation(({ where }: { where: { status: string } }) =>
      where.status === 'OVERDUE'
        // 距离整天边界预留 12 小时余量：mock 的 dueAt 在服务读取 now 之后才计算，毫秒差会让
        // floor((now-dueAt)/DAY) 落在 2；偏离边界后结果恒为 3，消除对执行耗时的敏感
        ? [{ id: 'loan-2', loanNo: 'LN-2', ticketId: null, createdAt: new Date(Date.now() - 10 * 24 * HOUR_MS), dueAt: new Date(Date.now() - 3 * 24 * HOUR_MS - 12 * HOUR_MS), ticket: null }]
        : [],
    );
    prisma.loanOrder.count.mockImplementation(({ where }: { where: { status: string } }) => (where.status === 'OVERDUE' ? 1 : 0));
    const result = await service.linkageTodos(employee);
    expect(result.loansOverdue.items).toEqual([
      { loanId: 'loan-2', loanNo: 'LN-2', ticketId: null, ticketNumber: '', title: '', overdueDays: 3 },
    ]);
  });
});
