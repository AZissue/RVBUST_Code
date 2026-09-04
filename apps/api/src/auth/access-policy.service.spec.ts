import { describe, expect, it } from 'vitest';
import { AccessPolicyService } from './access-policy.service.js';

const prisma = {} as never;
const service = new AccessPolicyService(prisma);

describe('AccessPolicyService', () => {
  it('keeps customer ticket data inside its organization', () => {
    expect(service.ticketWhere({ id: 'u1', username: 'customer', name: '客户', email: null, role: 'customer', customerOrganizationId: 'org-1', permissions: [] })).toEqual({ organizationId: 'org-1' });
  });

  it('limits employee work items to ownership or collaboration', () => {
    expect(service.workItemWhere({ id: 'u2', username: 'employee', name: '员工', email: null, role: 'employee', customerOrganizationId: null, permissions: [] })).toEqual({ OR: [{ ownerId: 'u2' }, { collaborators: { some: { userId: 'u2' } } }] });
  });

  it('limits employee work logs to authored facts', () => {
    expect(service.worklogWhere({ id: 'u2', username: 'employee', name: '员工', email: null, role: 'employee', customerOrganizationId: null, permissions: [] })).toEqual({ authorId: 'u2' });
  });
});
