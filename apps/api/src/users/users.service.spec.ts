import { describe, expect, it, vi } from 'vitest';
import { UsersService } from './users.service.js';
import type { PrismaService } from '../prisma/prisma.service.js';

describe('UsersService account safeguards', () => {
  it('rejects changing the current administrator role before any writes', async () => {
    const prisma = {
      user: { findUnique: vi.fn().mockResolvedValue({ id: 'admin', roleId: 'role-admin', role: { name: 'admin' } }) },
      role: { findUnique: vi.fn().mockResolvedValue({ id: 'role-employee' }) },
      $transaction: vi.fn(),
    };
    const service = new UsersService(prisma as unknown as PrismaService);
    await expect(service.update('admin', { role: 'employee' }, 'admin')).rejects.toThrow('不能修改当前登录账号的角色');
    expect(prisma.$transaction).not.toHaveBeenCalled();
  });

  it('rejects stale approval without invalidating sessions or returning success', async () => {
    const tx = {
      user: { updateMany: vi.fn().mockResolvedValue({ count: 0 }), findUniqueOrThrow: vi.fn() },
      authSession: { deleteMany: vi.fn() },
    };
    const prisma = {
      user: { findUnique: vi.fn().mockResolvedValue({ status: 'PENDING' }) },
      $transaction: (run: (client: typeof tx) => unknown) => run(tx),
    };
    const service = new UsersService(prisma as unknown as PrismaService);
    await expect(service.approve('user')).rejects.toThrow('用户状态已变化');
    expect(tx.user.updateMany).toHaveBeenCalledWith({ where: { id: 'user', status: 'PENDING' }, data: { status: 'ACTIVE' } });
    expect(tx.authSession.deleteMany).not.toHaveBeenCalled();
  });
});
