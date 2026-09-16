import { describe, it, expect, vi } from 'vitest';
import { WorklogsService } from './worklogs.service.js';

const user = { id: 'user-1', name: 'Alice', role: 'admin' } as never;

function setup({ worklog = {}, workItem = {}, ticketEvent = {} }: {
  worklog?: Record<string, unknown>;
  workItem?: Record<string, unknown>;
  ticketEvent?: Record<string, unknown>;
} = {}) {
  const current = { id: 'wl-1', authorId: 'user-1', ticketId: null, workTypeId: 'wt', durationMinutes: 30, summary: '现场排查', ...worklog };
  const db = {
    worklog: {
      findFirst: vi.fn().mockResolvedValue(current),
      create: vi.fn().mockImplementation(({ data }) => Promise.resolve({ ...current, ...data, id: 'wl-new' })),
      update: vi.fn().mockImplementation(({ data }) => Promise.resolve({ ...current, ...data })),
      delete: vi.fn().mockResolvedValue({}),
    },
    ticketEvent: {
      create: vi.fn().mockResolvedValue({ id: 'ev-1' }),
      findMany: vi.fn().mockResolvedValue([]),
      update: vi.fn().mockResolvedValue({}),
      updateMany: vi.fn().mockResolvedValue({ count: 1 }),
      ...ticketEvent,
    },
    workItem: {
      findUnique: vi.fn().mockResolvedValue({ organizationId: null, projectId: null, convertedTicketId: null }),
      findUniqueOrThrow: vi.fn().mockResolvedValue({ status: 'TODO', progress: 0 }),
      update: vi.fn().mockResolvedValue({}),
      ...workItem,
    },
    workType: { findFirst: vi.fn().mockResolvedValue({ id: 'wt' }) },
    ticket: { findUnique: vi.fn().mockResolvedValue({ organizationId: null, projectId: null }) },
    project: { findUnique: vi.fn().mockResolvedValue({ organizationId: null }) },
  };
  const prisma = { ...db, $transaction: (fn: (tx: typeof db) => unknown) => fn(db) };
  const access = { requireInternal: vi.fn(), worklogWhere: vi.fn().mockReturnValue({}) };
  const service = new WorklogsService(prisma as never, access as never);
  return { db, service };
}

const baseDto = { occurredAt: '2026-09-11T10:00:00.000Z', workTypeId: 'wt', summary: '现场排查' };

describe('worklogs linkage', () => {
  it('建 worklog（带 ticketId）时同事务回写 WORK_RECORD 事件', async () => {
    const { db, service } = setup();
    await service.create(user, { ...baseDto, ticketId: 't-1' });
    expect(db.worklog.create).toHaveBeenCalledTimes(1);
    expect(db.ticketEvent.create).toHaveBeenCalledTimes(1);
    const event = db.ticketEvent.create.mock.calls[0][0].data;
    expect(event).toMatchObject({ ticketId: 't-1', authorId: 'user-1', type: 'WORK_RECORD', visibility: 'INTERNAL' });
    expect(event.content).toContain('现场排查');
    expect(event.metadata.worklogId).toBe('wl-new');
    expect(event.metadata.durationMinutes).toBe(30);
  });

  it('建 worklog（带 workItemId，事项 TODO）时推进事项状态与进度', async () => {
    const { db, service } = setup();
    await service.create(user, { ...baseDto, workItemId: 'wi-1' });
    expect(db.workItem.update).toHaveBeenCalledTimes(1);
    expect(db.workItem.update.mock.calls[0][0]).toEqual({ where: { id: 'wi-1' }, data: { status: 'IN_PROGRESS', progress: 10 } });
  });

  it('建 worklog（带 workItemId，事项 COMPLETED）时不改动事项', async () => {
    const { db, service } = setup({ workItem: { findUniqueOrThrow: vi.fn().mockResolvedValue({ status: 'COMPLETED', progress: 100 }) } });
    await service.create(user, { ...baseDto, workItemId: 'wi-1' });
    expect(db.workItem.update).not.toHaveBeenCalled();
  });

  it('建 worklog（不带任何关联）时无联动副作用', async () => {
    const { db, service } = setup();
    await service.create(user, baseDto);
    expect(db.ticketEvent.create).not.toHaveBeenCalled();
    expect(db.workItem.update).not.toHaveBeenCalled();
  });

  it('校验失败（ticketId 不存在）时整体回滚，无事件残留', async () => {
    const { db, service } = setup({ ticketEvent: {} });
    db.ticket.findUnique.mockResolvedValue(null);
    await expect(service.create(user, { ...baseDto, ticketId: 'missing' })).rejects.toThrow('工单不存在');
    expect(db.worklog.create).not.toHaveBeenCalled();
    expect(db.ticketEvent.create).not.toHaveBeenCalled();
  });

  it('update 修改摘要时同步联动事件 content', async () => {
    const { db, service } = setup({ worklog: { ticketId: 't-1' }, ticketEvent: { findMany: vi.fn().mockResolvedValue([{ id: 'ev-1', ticketId: 't-1', metadata: { worklogId: 'wl-1' } }]) } });
    await service.update(user, 'wl-1', { summary: '更换镜头后复测' });
    expect(db.ticketEvent.updateMany).toHaveBeenCalledTimes(1);
    const call = db.ticketEvent.updateMany.mock.calls[0][0];
    expect(call.where).toMatchObject({ type: 'WORK_RECORD', ticketId: 't-1' });
    expect(call.where.metadata).toEqual({ path: ['worklogId'], equals: 'wl-1' });
    expect(call.data.content).toContain('更换镜头后复测');
    expect(db.ticketEvent.create).not.toHaveBeenCalled();
  });

  it('update 变更 ticketId 时旧事件软删、新工单补建事件', async () => {
    const { db, service } = setup({
      worklog: { ticketId: 't-old' },
      ticketEvent: { findMany: vi.fn().mockResolvedValue([{ id: 'ev-old', ticketId: 't-old', metadata: { worklogId: 'wl-1', durationMinutes: 30 } }]) },
    });
    await service.update(user, 'wl-1', { ticketId: 't-new' });
    // 旧事件软删：合并原 metadata，不整体覆盖
    expect(db.ticketEvent.update).toHaveBeenCalledTimes(1);
    const softDelete = db.ticketEvent.update.mock.calls[0][0];
    expect(softDelete.where).toEqual({ id: 'ev-old' });
    expect(softDelete.data.metadata).toMatchObject({ worklogId: 'wl-1', durationMinutes: 30, timelineDeleted: true, timelineDeletedBy: 'user-1' });
    expect(typeof softDelete.data.metadata.timelineDeletedAt).toBe('string');
    expect(db.ticketEvent.updateMany).not.toHaveBeenCalled();
    // 新工单补建事件
    expect(db.ticketEvent.create).toHaveBeenCalledTimes(1);
    expect(db.ticketEvent.create.mock.calls[0][0].data.ticketId).toBe('t-new');
  });

  it('update 给裸记录补挂 ticketId 时补建联动事件', async () => {
    const { db, service } = setup({ worklog: { ticketId: null } });
    await service.update(user, 'wl-1', { ticketId: 't-1' });
    expect(db.ticketEvent.create).toHaveBeenCalledTimes(1);
    expect(db.ticketEvent.create.mock.calls[0][0].data.ticketId).toBe('t-1');
  });

  it('remove worklog 时软删联动事件并删除记录（单事务）', async () => {
    const { db, service } = setup({
      ticketEvent: { findMany: vi.fn().mockResolvedValue([{ id: 'ev-1', ticketId: 't-1', metadata: { worklogId: 'wl-1' } }]) },
    });
    const result = await service.remove(user, 'wl-1');
    expect(result).toEqual({ success: true });
    expect(db.ticketEvent.update).toHaveBeenCalledTimes(1);
    expect(db.ticketEvent.update.mock.calls[0][0].data.metadata).toMatchObject({ worklogId: 'wl-1', timelineDeleted: true, timelineDeletedBy: 'user-1' });
    expect(db.worklog.delete).toHaveBeenCalledWith({ where: { id: 'wl-1' } });
  });
});
