import { describe, expect, it } from 'vitest';
import { AccessPolicyService } from './access-policy.service.js';

const prisma = {} as never;
const service = new AccessPolicyService(prisma);

describe('AccessPolicyService', () => {
  it('keeps customer ticket data inside its organization', () => {
    expect(service.ticketWhere({ id: 'u1', username: 'customer', name: '客户', email: null, role: 'customer', customerOrganizationId: 'org-1', permissions: [] })).toEqual({ organizationId: 'org-1', deletedAt: null });
  });

  it('lets all internal roles see every ticket', () => {
    const employee = { id: 'u2', username: 'employee', name: '员工', email: null, role: 'employee', customerOrganizationId: null, permissions: [] };
    expect(service.ticketWhere(employee)).toEqual({});
    expect(service.ticketWhere({ ...employee, id: 'u3', role: 'support' })).toEqual({});
    expect(service.ticketWhere({ ...employee, id: 'u4', role: 'admin' })).toEqual({});
  });

  it('limits ticket editing to creator, assignee and admin', () => {
    const employee = { id: 'u2', username: 'employee', name: '员工', email: null, role: 'employee', customerOrganizationId: null, permissions: [] };
    const admin = { ...employee, id: 'u4', role: 'admin' };
    const ticket = { createdById: 'u2', assigneeId: 'u3' };
    expect(service.canEditTicket(employee, ticket)).toBe(true);
    expect(service.canEditTicket({ ...employee, id: 'u3' }, ticket)).toBe(true);
    expect(service.canEditTicket(admin, ticket)).toBe(true);
    expect(service.canEditTicket({ ...employee, id: 'u5' }, ticket)).toBe(false);
    expect(service.canEditTicket({ ...employee, id: 'u3' }, { createdById: 'u2', assigneeId: null })).toBe(false);
  });

  it('limits employee work items to ownership or collaboration', () => {
    expect(service.workItemWhere({ id: 'u2', username: 'employee', name: '员工', email: null, role: 'employee', customerOrganizationId: null, permissions: [] })).toEqual({ OR: [{ ownerId: 'u2' }, { collaborators: { some: { userId: 'u2' } } }] });
  });

  it('limits employee work logs to authored facts', () => {
    expect(service.worklogWhere({ id: 'u2', username: 'employee', name: '员工', email: null, role: 'employee', customerOrganizationId: null, permissions: [] })).toEqual({ authorId: 'u2' });
  });
});
