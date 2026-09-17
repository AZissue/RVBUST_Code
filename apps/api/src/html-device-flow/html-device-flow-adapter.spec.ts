import { describe, it, expect, vi } from 'vitest';
import { HtmlDeviceFlowService } from './html-device-flow.service.js';

/** sync 全量事务所需的最小 mock 集；用例按需覆写返回值 */
function setupSync() {
  const tx = {
    htmlFlowState: {
      findUnique: vi.fn().mockResolvedValue({ id: 'main', revision: 0, data: {} }),
      create: vi.fn(),
      updateMany: vi.fn().mockResolvedValue({ count: 1 }),
    },
    user: { findFirst: vi.fn().mockResolvedValue({ id: 'user-1' }) },
    loanOrder: {
      findMany: vi.fn().mockResolvedValue([]),
      findFirst: vi.fn().mockResolvedValue(null),
      upsert: vi.fn().mockResolvedValue({}),
      update: vi.fn().mockResolvedValue({}),
      delete: vi.fn().mockResolvedValue({}),
    },
    repairOrder: {
      findMany: vi.fn().mockResolvedValue([]),
      findFirst: vi.fn().mockResolvedValue(null),
      upsert: vi.fn().mockResolvedValue({}),
      update: vi.fn().mockResolvedValue({}),
      delete: vi.fn().mockResolvedValue({}),
    },
    device: {
      findMany: vi.fn().mockResolvedValue([]),
      create: vi.fn().mockResolvedValue({ id: 'device-new' }),
      upsert: vi.fn().mockResolvedValue({}),
      update: vi.fn().mockResolvedValue({}),
      delete: vi.fn().mockResolvedValue({}),
    },
    customerOrganization: {
      findFirst: vi.fn().mockResolvedValue(null),
      create: vi.fn().mockResolvedValue({ id: 'org-new' }),
    },
    contact: {
      findFirst: vi.fn().mockResolvedValue(null),
      create: vi.fn().mockResolvedValue({ id: 'contact-new' }),
    },
    loanItem: { upsert: vi.fn().mockResolvedValue({ id: 'item-new' }) },
    followUp: {
      findMany: vi.fn().mockResolvedValue([]),
      upsert: vi.fn().mockResolvedValue({}),
      deleteMany: vi.fn().mockResolvedValue({ count: 0 }),
    },
    attachment: {
      findMany: vi.fn().mockResolvedValue([]),
      upsert: vi.fn().mockResolvedValue({}),
      deleteMany: vi.fn().mockResolvedValue({ count: 0 }),
    },
    htmlFlowFile: {
      findUnique: vi.fn().mockResolvedValue(null),
      findMany: vi.fn().mockResolvedValue([]),
      deleteMany: vi.fn().mockResolvedValue({ count: 0 }),
    },
  };
  const prisma = { $transaction: (fn: (db: typeof tx) => unknown) => fn(tx) };
  const service = new HtmlDeviceFlowService(prisma as never);
  const emptyData = (partial: Record<string, unknown> = {}) => ({
    records: [], devices: [], recycle: { records: [], devices: [] }, settings: {}, ...partial,
  });
  return { tx, service, emptyData };
}

describe('html-device-flow adapter snapshot（关系库组装）', () => {
  function setupSnapshot() {
    const loanAtts = [
      { id: 'att-l1', loanItemId: 'item-1', repairOrderId: null, photoCategory: 'VIEWS', photoSlot: 1, photoKey: 'file-l1', originalName: 'p.jpg' },
    ];
    const repairAtts = [
      { id: 'att-r1', loanItemId: null, repairOrderId: 'rep-1', photoCategory: 'VIEWS', photoSlot: 2, photoKey: 'file-r1', originalName: 'view.jpg' },
      { id: 'att-r2', loanItemId: null, repairOrderId: 'rep-1', photoCategory: 'AGREEMENT', photoSlot: 1, photoKey: 'file-r2', originalName: 'agreement.pdf' },
    ];
    const loanFUs = [
      { id: 'fu-1', loanOrderId: 'loan-1', repairOrderId: null, flowId: 'FU-custom', content: '已电话确认', occurredAt: new Date('2026-09-06T10:00:00'), source: 'WEB', author: { name: '刘海焕' } },
    ];
    const prisma = {
      htmlFlowState: { findUnique: vi.fn().mockResolvedValue({ id: 'main', revision: 7, data: { settings: { sales: '李辉' } } }) },
      loanOrder: {
        findMany: vi.fn().mockResolvedValue([
          {
            id: 'loan-1', loanNo: 'LN-260917-001', flowId: 'R-custom', status: 'ONGOING', purpose: '产线验证',
            loanedAt: new Date('2026-09-01'), dueAt: new Date('2026-09-20'),
            outboundCarrier: '顺丰', outboundTracking: 'SF001', returnCarrier: '圆通', returnTracking: 'YT001',
            note: '加急', createdAt: new Date('2026-09-02T09:00:00'), updatedAt: new Date('2026-09-03T10:00:00'), deletedAt: null,
            organization: { name: '华东自动化' }, contact: { name: '张工', phone: '13800000001' },
            items: [
              { id: 'item-1', accessories: '15m标配', device: { serialNumber: 'SN001', cameraModel: 'M2600', product: null } },
              { id: 'item-2', accessories: '支架', device: { serialNumber: 'SN001-B', cameraModel: 'M2600', product: null } },
            ],
          },
        ]),
      },
      repairOrder: {
        findMany: vi.fn().mockResolvedValue([
          {
            id: 'rep-1', repairNo: 'RP-260917-001', flowId: null, status: 'CLOSED', serialNumber: 'SN002',
            symptom: '无法拍摄', receivedAt: new Date('2026-09-05'),
            inboundCarrier: '德邦', inboundTracking: 'DB001', outboundCarrier: '顺丰', trackingNo: 'SF999',
            partsReturned: '相机×1', note: null, closedAt: new Date('2026-09-08'),
            createdAt: new Date('2026-09-04T08:00:00'), updatedAt: new Date('2026-09-08T18:00:00'), deletedAt: new Date('2026-09-10T00:00:00'),
            organization: { name: '群青科技' }, contact: { name: '王工', phone: '13900000002' },
            device: { serialNumber: 'SN002', cameraModel: 'M2600 V2', product: null },
          },
        ]),
      },
      device: {
        findMany: vi.fn().mockResolvedValue([
          {
            id: 'dev-1', flowId: null, serialNumber: 'SN001', cameraModel: 'M2600', product: null,
            ownerType: 'COMPANY', status: 'LOANED', assetNo: 'AS001', notes: '公司样机',
            createdAt: new Date('2026-08-01T10:00:00'), deletedAt: null, organization: { name: '华东自动化' },
          },
        ]),
      },
      attachment: { findMany: vi.fn().mockImplementation(({ where }: { where: Record<string, unknown> }) => Promise.resolve(where.loanItemId ? loanAtts : repairAtts)) },
      followUp: { findMany: vi.fn().mockImplementation(({ where }: { where: Record<string, unknown> }) => Promise.resolve(where.loanOrderId ? loanFUs : [])) },
    };
    const service = new HtmlDeviceFlowService(prisma as never);
    return { prisma, service };
  }

  it('借测/维修/设备字段与状态映射正确，跟进与附件注入，软删行进 recycle', async () => {
    const { prisma, service } = setupSnapshot();
    const result = await service.snapshot();
    expect(result.revision).toBe(7);
    expect(result.data.settings).toEqual({ sales: '李辉' });

    // 活跃区：1 条借测
    expect(result.data.records).toHaveLength(1);
    const loan = result.data.records[0];
    expect(loan).toMatchObject({
      id: 'R-custom', orderNo: 'LN-260917-001', type: 'loan', status: '借测中',
      sn: 'SN001', model: 'M2600', customer: '华东自动化', contact: '张工', phone: '13800000001',
      loanStart: '2026-09-01', loanDue: '2026-09-20', loanPurpose: '产线验证',
      outboundCarrier: '顺丰', outboundTracking: 'SF001', inboundCarrier: '圆通', inboundTracking: 'YT001',
      accessories: '15m标配、支架', notes: '加急',
      photos: { '0': '/api/html-device-flow/files/file-l1' }, agreement: null,
      createdAt: '2026-09-02 09:00:00',
    });
    expect(loan.followUps).toEqual([{ id: 'FU-custom', person: '刘海焕', date: '2026-09-06 10:00:00', text: '已电话确认', source: 'WEB' }]);

    // 回收区：软删维修单，无 flowId 时 id 为 R-<uuid> 形态，附件含协议
    expect(result.data.recycle.records).toHaveLength(1);
    const repair = result.data.recycle.records[0];
    expect(repair.id).toBe('R-rep-1');
    expect(typeof repair.deletedAt).toBe('string');
    expect(repair).toMatchObject({
      orderNo: 'RP-260917-001', type: 'repair', status: '已完成', sn: 'SN002', model: 'M2600 V2',
      customer: '群青科技', reportDate: '2026-09-05', reason: '无法拍摄',
      inboundCarrier: '德邦', outboundTracking: 'SF999', accessories: '相机×1',
      photos: { '1': '/api/html-device-flow/files/file-r1' },
      agreement: { name: 'agreement.pdf', data: '/api/html-device-flow/files/file-r2' },
    });

    // 设备台账
    expect(result.data.devices).toHaveLength(1);
    expect(result.data.devices[0]).toMatchObject({
      id: 'D-dev-1', sn: 'SN001', model: 'M2600', ownership: '公司资产', status: '借测中',
      customer: '华东自动化', assetNo: 'AS001', note: '公司样机',
    });
    expect(result.data.recycle.devices).toHaveLength(0);
    // 不再读写 html_flow_followups
    expect((prisma as Record<string, unknown>).htmlFlowFollowup).toBeUndefined();
  });
});

describe('html-device-flow adapter sync（翻译回关系表）', () => {
  it('新建：新客户自动建组织，loan/repair 走 create 分支，状态与单号反映射', async () => {
    const { tx, service, emptyData } = setupSync();
    tx.device.create.mockImplementation(({ data }: { data: { serialNumber: string } }) => Promise.resolve({ id: data.serialNumber === 'SN100' ? 'dev-1' : 'dev-2' }));
    const payload = {
      revision: 0,
      data: emptyData({
        records: [
          {
            id: 'R-new1', orderNo: 'JC20260917001', type: 'loan', sn: 'SN100', model: 'M2600',
            customer: '新客户', contact: '张三', phone: '13800000001',
            loanStart: '2026-09-01', loanDue: '2026-09-30', loanPurpose: '验证',
            outboundCarrier: '顺丰', outboundTracking: 'SF001', inboundCarrier: '', inboundTracking: '',
            status: '借测中', accessories: '裸机', notes: '备注', photos: {}, agreement: null, followUps: [],
          },
          {
            id: 'R-new2', orderNo: 'WX20260917001', type: 'repair', sn: 'SN200', model: 'M2600 V2',
            customer: '新客户', contact: '李四', phone: '13800000002',
            reportDate: '2026-09-10', reason: '拍摄异常',
            inboundCarrier: '德邦', inboundTracking: 'DB001', outboundCarrier: '顺丰', outboundTracking: 'SF002',
            status: '维修中', accessories: '相机', notes: '', photos: {}, agreement: null, followUps: [],
          },
        ],
        settings: { sales: '李辉' },
      }),
    };
    await expect(service.sync(payload)).resolves.toEqual({ revision: 1 });

    // 客户按名创建一次并缓存复用
    expect(tx.customerOrganization.create).toHaveBeenCalledTimes(1);
    expect(tx.customerOrganization.create).toHaveBeenCalledWith(expect.objectContaining({ data: { name: '新客户' } }));

    // 借测单 create 分支
    const loanCall = tx.loanOrder.upsert.mock.calls[0][0];
    expect(loanCall.where).toEqual({ id: expect.any(String) });
    expect(loanCall.create).toMatchObject({
      loanNo: 'JC20260917001', organizationId: 'org-new', contactId: 'contact-new',
      status: 'ONGOING', purpose: '验证', createdById: 'user-1', flowId: 'R-new1', deletedAt: null,
      loanedAt: new Date('2026-09-01'), dueAt: new Date('2026-09-30'),
      outboundCarrier: '顺丰', returnCarrier: null,
    });
    expect(loanCall.update.loanNo).toBeUndefined();
    expect(loanCall.update.createdById).toBeUndefined();

    // 维修单 create 分支：状态反映射与字段映射
    const repairCall = tx.repairOrder.upsert.mock.calls[0][0];
    expect(repairCall.create).toMatchObject({
      repairNo: 'WX20260917001', organizationId: 'org-new', status: 'REPAIRING',
      serialNumber: 'SN200', symptom: '拍摄异常', receivedAt: new Date('2026-09-10'),
      inboundCarrier: '德邦', trackingNo: 'SF002', partsReturned: '相机',
      deviceId: 'dev-2', createdById: 'user-1', flowId: 'R-new2',
    });

    // 设备按 SN 解析创建：借测=公司样机、维修=客户设备
    expect(tx.device.create.mock.calls.map((c: { data: { serialNumber: string; ownerType: string } }[]) => [c[0].data.serialNumber, c[0].data.ownerType]))
      .toEqual([['SN100', 'COMPANY'], ['SN200', 'CUSTOMER']]);
    expect(tx.loanItem.upsert).toHaveBeenCalledWith(expect.objectContaining({
      create: expect.objectContaining({ loanOrderId: loanCall.create.id ?? loanCall.where.id, deviceId: 'dev-1', accessories: '裸机' }),
    }));

    // state 行只存 settings
    expect(tx.htmlFlowState.updateMany).toHaveBeenCalledWith(expect.objectContaining({
      where: { id: 'main', revision: 0 },
      data: expect.objectContaining({ data: { settings: { sales: '李辉' } } }),
    }));
  });

  it('更新：flowId 命中走 update 分支并恢复 deletedAt，不动 loanNo/createdById', async () => {
    const { tx, service, emptyData } = setupSync();
    tx.htmlFlowState.findUnique.mockResolvedValue({ id: 'main', revision: 3, data: {} });
    tx.loanOrder.findMany.mockResolvedValue([{ id: 'loan-9', flowId: 'R-flow-1', loanNo: 'LN-260917-001' }]);
    tx.customerOrganization.findFirst.mockResolvedValue({ id: 'org-9' });
    tx.device.create.mockResolvedValue({ id: 'dev-9' });
    const payload = {
      revision: 3,
      data: emptyData({
        records: [
          {
            id: 'R-flow-1', orderNo: 'JC-SHOULD-NOT-APPLY', type: 'loan', sn: 'SN9', model: 'M2600',
            customer: '老客户', contact: '', phone: '',
            loanStart: '', loanDue: '', loanPurpose: '复测',
            outboundCarrier: '', outboundTracking: '', inboundCarrier: '圆通', inboundTracking: 'YT9',
            status: '已归还', accessories: '线缆', notes: '', photos: {}, agreement: null, followUps: [],
          },
        ],
      }),
    };
    await expect(service.sync(payload)).resolves.toEqual({ revision: 4 });
    expect(tx.customerOrganization.create).not.toHaveBeenCalled();
    expect(tx.loanOrder.upsert).toHaveBeenCalledTimes(1);
    const call = tx.loanOrder.upsert.mock.calls[0][0];
    expect(call.where).toEqual({ id: 'loan-9' });
    expect(call.update).toMatchObject({ status: 'RETURNED', flowId: 'R-flow-1', deletedAt: null, purpose: '复测', returnCarrier: '圆通' });
    expect(call.update.loanNo).toBeUndefined();
    expect(call.update.createdById).toBeUndefined();
    expect(tx.loanItem.upsert).toHaveBeenCalledWith(expect.objectContaining({
      where: { loanOrderId_deviceId: { loanOrderId: 'loan-9', deviceId: 'dev-9' } },
    }));
  });

  it('回收软删 flowId 行；payload 缺失的 flowId 行物理删除；非 flowId 行不删除', async () => {
    const { tx, service, emptyData } = setupSync();
    tx.loanOrder.findMany.mockResolvedValue([
      { id: 'l1', flowId: 'R-a', loanNo: 'A' },
      { id: 'l2', flowId: 'R-b', loanNo: 'B' },
      { id: 'l3', flowId: null, loanNo: 'C' },
    ]);
    tx.device.findMany.mockResolvedValue([
      { id: 'd1', flowId: 'D-a', serialNumber: 'S1' },
      { id: 'd2', flowId: 'D-b', serialNumber: 'S2' },
      { id: 'd3', flowId: null, serialNumber: 'S3' },
    ]);
    const payload = {
      revision: 0,
      data: emptyData({ recycle: { records: [{ id: 'R-a', type: 'loan' }], devices: [{ id: 'D-a' }] } }),
    };
    await expect(service.sync(payload)).resolves.toEqual({ revision: 1 });

    expect(tx.loanOrder.update).toHaveBeenCalledWith({ where: { id: 'l1' }, data: { deletedAt: expect.any(Date) } });
    expect(tx.device.update).toHaveBeenCalledWith({ where: { id: 'd1' }, data: { deletedAt: expect.any(Date) } });
    expect(tx.loanOrder.delete).toHaveBeenCalledTimes(1);
    expect(tx.loanOrder.delete).toHaveBeenCalledWith({ where: { id: 'l2' } });
    expect(tx.device.delete).toHaveBeenCalledTimes(1);
    expect(tx.device.delete).toHaveBeenCalledWith({ where: { id: 'd2' } });
    expect(tx.loanOrder.delete).not.toHaveBeenCalledWith({ where: { id: 'l3' } });
    expect(tx.device.delete).not.toHaveBeenCalledWith({ where: { id: 'd3' } });
  });

  it('revision 冲突：行版本不匹配或 updateMany 命中 0 均抛 409', async () => {
    const { tx, service, emptyData } = setupSync();
    tx.htmlFlowState.findUnique.mockResolvedValue({ id: 'main', revision: 5, data: {} });
    await expect(service.sync({ revision: 0, data: emptyData() })).rejects.toThrow('数据已被其他人更新，请刷新后重试');
    expect(tx.htmlFlowState.updateMany).not.toHaveBeenCalled();

    tx.htmlFlowState.findUnique.mockResolvedValue({ id: 'main', revision: 0, data: {} });
    tx.htmlFlowState.updateMany.mockResolvedValue({ count: 0 });
    await expect(service.sync({ revision: 0, data: emptyData() })).rejects.toThrow('数据已被其他人更新，请刷新后重试');
    expect(tx.user.findFirst).not.toHaveBeenCalled();
  });
});
