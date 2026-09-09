import { describe, expect, it } from 'vitest';
import { extractDateExpression, matchCustomers, matchPeople, parseQuickTicketInput, ticketSimilarity } from './quick-input.parser.js';
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
  it.each([
    ['本周一 浙江智享 M2600无点云', '2026-09-07'],
    ['周一 浙江智享 M2600无点云', '2026-09-07'],
    ['星期三 测试问题', '2026-09-09'],
    ['上周三 测试问题', '2026-09-02'],
    ['下周二 测试问题', '2026-09-15'],
    ['周日 值班问题', '2026-09-13'],
    ['0907 浙江智享 M2600无点云', '2026-09-07'],
    ['9月7号 浙江智享 M2600无点云', '2026-09-07'],
    ['2026-09-07 浙江智享 M2600无点云', '2026-09-07'],
    ['2026/9/7 浙江智享 M2600无点云', '2026-09-07'],
    ['昨天 浙江智享 M2600无点云', '2026-09-08'],
    ['大前天 测试问题', '2026-09-06'],
    ['明天 预约上门', '2026-09-10'],
  ])('extracts date expression from %s', (raw, key) => {
    expect(extractDateExpression(raw, new Date(2026, 8, 9, 15, 30)).occurredAt).toBe(key);
  });
  it.each([
    ['RVC-260907-001 需要跟进', '工单号不当作日期'],
    ['M2600 SDK 2.8 无点云', '版本号不当作日期'],
    ['浙江智享 M2600无点云 张伟 紧急', '无日期'],
    ['客户说1330开始停机', '非日期数字段不当作日期'],
  ])('ignores non-date text: %s', (raw) => {
    expect(extractDateExpression(raw, new Date(2026, 8, 9)).occurredAt).toBeNull();
  });
  it('strips the date phrase and keeps remaining text', () => {
    const result = extractDateExpression('本周一，浙江智享 M2600无点云，紧急', new Date(2026, 8, 9));
    expect(result.occurredAt).toBe('2026-09-07');
    expect(result.text).toContain('浙江智享');
    expect(result.text).not.toContain('本周一');
  });
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
