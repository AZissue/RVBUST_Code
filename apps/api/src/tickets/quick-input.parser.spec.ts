import { describe, expect, it } from 'vitest';
import { matchCustomers, matchPeople, parseQuickTicketInput, ticketSimilarity } from './quick-input.parser.js';
const context = { customers: [{ id: 'c1', name: '浙江智享机器人' }, { id: 'c2', name: '工布公司' }], users: [{ id: 'u1', name: '张伟' }, { id: 'u2', name: '李四' }], currentUserId: 'u1' };
describe('local quick ticket parser', () => {
  it.each([
    ['浙江智享机器人 M2600拍摄3D无点云 张伟 紧急', 'c1', 'u1', 'URGENT', 'M2600拍摄3D无点云'],
    ['浙江智享 M2600连接不上 张伟 高优先级', 'c1', 'u1', 'HIGH', 'M2600连接不上'],
    ['工布 G52000 2D正常3D无点云 李四 普通', 'c2', 'u2', 'MEDIUM', 'G52000 2D正常3D无点云'],
    ['浙江智享机器人 M2600拍摄超时', 'c1', 'u1', 'MEDIUM', 'M2600拍摄超时'],
    ['M2600无点云 张伟 紧急', undefined, 'u1', 'URGENT', 'M2600无点云'],
  ])('parses %s', (raw, customer, assignee, priority, issue) => {
    const result = parseQuickTicketInput(raw, context);
    expect(result.matchedCustomer?.id).toBe(customer);
    expect(result.matchedAssignee?.id).toBe(assignee);
    expect(result.priority).toBe(priority);
    expect(result.issue).toBe(issue);
  });
  it.each(['浙江智享', '智享机器人', '浙江智享客户', '智享客户'])('matches customer alias %s', (name) => expect(matchCustomers(name, context.customers)[0]?.id).toBe('c1'));
  it('does not select ambiguous customers or surnames', () => {
    const result = parseQuickTicketInput('浙江智享 M2600无点云 张工 紧急', { ...context, customers: [...context.customers, { id: 'c3', name: '浙江智享科技' }], users: [...context.users, { id: 'u3', name: '张三' }] });
    expect(result.matchedCustomer).toBeNull(); expect(result.customerCandidates).toHaveLength(2);
    expect(result.matchedAssignee).toBeNull(); expect(result.assigneeCandidates).toHaveLength(2);
  });
  it('keeps an unknown explicit assignee unresolved', () => {
    const result = parseQuickTicketInput('浙江智享 M2600无点云，负责人不存在，紧急', context);
    expect(result.matchedAssignee).toBeNull(); expect(result.assigneeDefaulted).toBe(false);
    expect(result.issue).toBe('M2600无点云');
  });
  it('recognizes nicknames and preserves factual downtime', () => {
    expect(matchPeople('小张', context.users)[0].id).toBe('u1');
    const result = parseQuickTicketInput('浙江智享 M2600产线停机 张工', context);
    expect(result.priority).toBe('URGENT'); expect(result.issue).toContain('产线停机');
  });
  it('detects equivalent connection problems', () => {
    expect(ticketSimilarity('M2600连接不上', 'M2600连接超时', 'M2600', 'M2600', true)).toBe(100);
    expect(ticketSimilarity('M2600连接不上', '培训资料整理', 'M2600', '', true)).toBeLessThan(40);
  });
});
