import { PrismaClient, TicketEventType, TicketPriority, TicketSource, TicketStatus, Visibility, WorkItemPriority, WorkItemStatus } from '@prisma/client';
import { hash } from 'bcryptjs';

const prisma = new PrismaClient();

const rolePermissions: Record<string, string[]> = {
  admin: ['users.manage', 'teams.manage', 'settings.manage', 'audit.read', 'customers.manage', 'tickets.manage', 'workitems.manage', 'worklogs.manage', 'notifications.manage'],
  support: ['customers.manage', 'tickets.manage', 'workitems.manage', 'worklogs.manage', 'notifications.manage'],
  employee: ['customers.read', 'tickets.participate', 'workitems.own', 'worklogs.own', 'notifications.own'],
  customer: ['tickets.customer', 'notifications.own'],
};

function requiredPassword(name: string) {
  const value = process.env[name];
  if (!value || value.length < 10 || value.startsWith('set-a-')) throw new Error(`${name} must be set to a unique password of at least 10 characters`);
  return value;
}

async function main() {
  for (const [roleName, codes] of Object.entries(rolePermissions)) {
    const role = await prisma.role.upsert({ where: { name: roleName }, update: {}, create: { name: roleName, label: { admin: '管理员', support: '技术支持', employee: '普通员工', customer: '客户' }[roleName] ?? roleName } });
    for (const code of codes) {
      const permission = await prisma.permission.upsert({ where: { code }, update: {}, create: { code, description: code } });
      await prisma.rolePermission.upsert({ where: { roleId_permissionId: { roleId: role.id, permissionId: permission.id } }, update: {}, create: { roleId: role.id, permissionId: permission.id } });
    }
  }

  const roles = Object.fromEntries((await prisma.role.findMany()).map((role) => [role.name, role]));
  const workTypeLabels = ['客户支持', '售前选型', '工件测试', '现场调试', '内部支持', '研发协同', '培训', '文档资料', 'PPT制作', '视频教程', '产品测试', '产品学习', '知识库', '软件工具', '项目工作', '会议', '其他'];
  for (const [sortOrder, label] of workTypeLabels.entries()) {
    const code = ['customer-support', 'pre-sales', 'workpiece-test', 'on-site-debug', 'internal-support', 'rnd-collaboration', 'training', 'documentation', 'ppt', 'video-tutorial', 'product-test', 'product-learning', 'knowledge-base', 'software-tools', 'project-work', 'meeting', 'other'][sortOrder];
    await prisma.workType.upsert({ where: { code }, update: { label, sortOrder, isActive: true }, create: { code, label, sortOrder } });
  }
  const workTypes = Object.fromEntries((await prisma.workType.findMany()).map((type) => [type.code, type]));
  const admin = await prisma.user.upsert({
    where: { username: 'admin' }, update: {},
    create: { username: 'admin', name: '系统管理员', email: 'admin@example.local', passwordHash: await hash(requiredPassword('SEED_ADMIN_PASSWORD'), 12), roleId: roles.admin.id },
  });
  const support = await prisma.user.upsert({
    where: { username: 'support' }, update: {},
    create: { username: 'support', name: '技术支持', email: 'support@example.local', passwordHash: await hash(requiredPassword('SEED_SUPPORT_PASSWORD'), 12), roleId: roles.support.id },
  });
  const employee = await prisma.user.upsert({
    where: { username: 'employee' }, update: {},
    create: { username: 'employee', name: '支持协作员工', email: 'employee@example.local', passwordHash: await hash(requiredPassword('SEED_EMPLOYEE_PASSWORD'), 12), roleId: roles.employee.id },
  });

  const organization = await prisma.customerOrganization.upsert({
    where: { name: '华东智能制造示例客户' },
    update: { technicalOwnerId: support.id, businessOwnerId: admin.id },
    create: { name: '华东智能制造示例客户', region: '浙江', industry: '智能制造', level: 'A', notes: 'V2 本地验收数据，禁止作为生产数据。', technicalOwnerId: support.id, businessOwnerId: admin.id },
  });
  const contact = await prisma.contact.upsert({
    where: { id: '00000000-0000-4000-8000-000000000101' },
    update: {},
    create: { id: '00000000-0000-4000-8000-000000000101', organizationId: organization.id, name: '陈工', title: '项目工程师', phone: '13800000001', email: 'chen@example.local', wechat: 'demo-chen', isPrimary: true },
  });
  const device = await prisma.device.upsert({
    where: { id: '00000000-0000-4000-8000-000000000201' },
    update: {},
    create: { id: '00000000-0000-4000-8000-000000000201', organizationId: organization.id, name: '产线 3D 相机', product: 'RVC 3D Camera', cameraModel: 'M2600', serialNumber: 'DEMO-M2600-001', sdkVersion: '2.3.0', location: '一号产线' },
  });
  const project = await prisma.project.upsert({
    where: { organizationId_name: { organizationId: organization.id, name: '机器人抓取项目' } },
    update: {},
    create: { organizationId: organization.id, name: '机器人抓取项目', application: '无序抓取与点云定位', status: '调试中' },
  });
  await prisma.user.upsert({
    where: { username: 'customer' }, update: { customerOrganizationId: organization.id },
    create: { username: 'customer', name: '客户测试账号', email: 'customer@example.local', passwordHash: await hash(requiredPassword('SEED_CUSTOMER_PASSWORD'), 12), roleId: roles.customer.id, customerOrganizationId: organization.id },
  });

  const ticket = await prisma.ticket.upsert({
    where: { number: 'TS-DEMO-0001' }, update: {},
    create: {
      number: 'TS-DEMO-0001', source: TicketSource.AFTER_SALES_INCIDENT, organizationId: organization.id,
      contactId: contact.id, deviceId: device.id, projectId: project.id, cameraModel: 'M2600', serialNumber: device.serialNumber,
      sdkVersion: device.sdkVersion, systemEnvironment: 'Windows 11 / 千兆网卡 / RVC SDK 2.3.0', category: '网络连接',
      title: 'M2600 连接超时', description: '相机可以被发现，但连接时偶发超时。', priority: TicketPriority.HIGH,
      status: TicketStatus.IN_PROGRESS, assigneeId: support.id, createdById: admin.id,
      plannedAt: new Date(Date.now() + 20 * 60 * 60 * 1000), collaborators: { create: { userId: employee.id } },
      events: { create: [
        { authorId: admin.id, type: TicketEventType.ASSIGNMENT, visibility: Visibility.INTERNAL, content: '分配给技术支持' },
        { authorId: support.id, type: TicketEventType.WORK_RECORD, visibility: Visibility.INTERNAL, content: '已复现连接超时，正在检查网卡配置。' },
      ] },
    },
  });
  const workItem = await prisma.workItem.upsert({
    where: { id: '00000000-0000-4000-8000-000000000401' },
    update: {},
    create: {
      id: '00000000-0000-4000-8000-000000000401', title: 'SDK 安装教程第二版', description: '补充驱动检查与常见安装失败处理。',
      workTypeId: workTypes['video-tutorial'].id, projectId: project.id, priority: WorkItemPriority.HIGH, status: WorkItemStatus.IN_PROGRESS,
      ownerId: support.id, startDate: new Date(), dueDate: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000), progress: 60, tags: ['SDK', '教程'],
      collaborators: { create: { userId: employee.id } },
    },
  });
  await prisma.worklog.upsert({
    where: { id: '00000000-0000-4000-8000-000000000301' }, update: {},
    create: { id: '00000000-0000-4000-8000-000000000301', authorId: support.id, workTypeId: workTypes['customer-support'].id, organizationId: organization.id, ticketId: ticket.id, projectId: project.id, occurredAt: new Date(), summary: '排查 M2600 连接超时', problem: '连接阶段偶发超时', actions: '检查 IP 与巨帧设置', result: '定位到网卡巨帧配置待调整', nextStep: '远程协助客户设置 9014 Bytes', durationMinutes: 45, rawText: '排查客户 M2600 连接超时，定位到巨帧设置。' },
  });
  await prisma.worklog.upsert({
    where: { id: '00000000-0000-4000-8000-000000000302' }, update: {},
    create: { id: '00000000-0000-4000-8000-000000000302', authorId: support.id, workTypeId: workTypes['video-tutorial'].id, workItemId: workItem.id, projectId: project.id, occurredAt: new Date(), summary: '完成 SDK 安装教程第二版脚本', actions: '重构安装步骤并补充截图清单', result: '脚本已完成，待录屏', nextStep: '录制并校对视频', durationMinutes: 90, rawText: '上午完成SDK安装教程第二版。' },
  });
  await prisma.notification.upsert({
    where: { recipientId_dedupeKey: { recipientId: support.id, dedupeKey: 'demo-ticket-assigned' } }, update: {},
    create: { recipientId: support.id, ticketId: ticket.id, type: 'ticket.assigned', severity: 'WARNING', title: '高优先级工单已分配', body: `${ticket.number} 需要在计划时间前处理`, dedupeKey: 'demo-ticket-assigned' },
  });
  await prisma.systemSetting.upsert({ where: { key: 'workspace' }, update: {}, create: { key: 'workspace', value: { name: '技术支持系统 V2', locale: 'zh-CN' }, isPublic: true } });
  console.log('Seed complete. Test data only; do not use as production data.');
}

main().finally(() => prisma.$disconnect());
