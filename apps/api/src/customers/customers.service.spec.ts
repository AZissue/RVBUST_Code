import { NotFoundException } from '@nestjs/common';
import { describe, expect, it, vi } from 'vitest';
import { CustomersService } from './customers.service.js';
import type { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import type { PrismaService } from '../prisma/prisma.service.js';

const user: AuthUser = { id: 'u1', username: 'zhang', name: '张伟', email: null, role: 'support', permissions: [] };

describe('CustomersService.addAlias', () => {
  const makeAccess = () => ({ requireCustomer: vi.fn().mockResolvedValue({ id: 'c1' }) });

  it('creates a trimmed alias for an existing organization', async () => {
    const prisma = { customerAlias: { findUnique: vi.fn().mockResolvedValue(null), create: vi.fn().mockResolvedValue({}) } };
    const access = makeAccess();
    const service = new CustomersService(prisma as unknown as PrismaService, access as unknown as AccessPolicyService);
    await expect(service.addAlias(user, { organizationId: 'c1', alias: '  盈联科技  ' })).resolves.toEqual({ ok: true });
    expect(prisma.customerAlias.create).toHaveBeenCalledWith({ data: { organizationId: 'c1', alias: '盈联科技', createdById: 'u1' } });
  });

  it('is idempotent when the same alias already exists', async () => {
    const prisma = { customerAlias: { findUnique: vi.fn().mockResolvedValue({ id: 'a1' }), create: vi.fn() } };
    const access = makeAccess();
    const service = new CustomersService(prisma as unknown as PrismaService, access as unknown as AccessPolicyService);
    await expect(service.addAlias(user, { organizationId: 'c1', alias: '盈联科技' })).resolves.toEqual({ ok: true });
    expect(prisma.customerAlias.create).not.toHaveBeenCalled();
  });

  it('treats a concurrent unique violation as success', async () => {
    const error = Object.assign(new Error('unique'), { code: 'P2002' });
    const prisma = { customerAlias: { findUnique: vi.fn().mockResolvedValue(null), create: vi.fn().mockRejectedValue(error) } };
    const access = makeAccess();
    const service = new CustomersService(prisma as unknown as PrismaService, access as unknown as AccessPolicyService);
    await expect(service.addAlias(user, { organizationId: 'c1', alias: '盈联科技' })).resolves.toEqual({ ok: true });
  });

  it('rejects when the organization does not exist', async () => {
    const prisma = { customerAlias: { findUnique: vi.fn(), create: vi.fn() } };
    const access = { requireCustomer: vi.fn().mockRejectedValue(new NotFoundException('客户不存在')) };
    const service = new CustomersService(prisma as unknown as PrismaService, access as unknown as AccessPolicyService);
    await expect(service.addAlias(user, { organizationId: 'missing', alias: '盈联科技' })).rejects.toThrow('客户不存在');
    expect(prisma.customerAlias.create).not.toHaveBeenCalled();
  });

  it('rejects a blank or overlong alias before any lookup', async () => {
    const prisma = { customerAlias: { findUnique: vi.fn(), create: vi.fn() } };
    const access = makeAccess();
    const service = new CustomersService(prisma as unknown as PrismaService, access as unknown as AccessPolicyService);
    await expect(service.addAlias(user, { organizationId: 'c1', alias: '   ' })).rejects.toThrow('别名长度需在 1-100 字之间');
    await expect(service.addAlias(user, { organizationId: 'c1', alias: '盈'.repeat(101) })).rejects.toThrow('别名长度需在 1-100 字之间');
    expect(access.requireCustomer).not.toHaveBeenCalled();
    expect(prisma.customerAlias.create).not.toHaveBeenCalled();
  });
});
