import { ConfigService } from '@nestjs/config';
import { randomBytes } from 'node:crypto';
import { AIKeyStore } from './ai.crypto.js';
import { AITransport, isPublicAddress } from './ai.transport.js';
import { validateExtraction } from '../tickets/ai.parser.js';
import { RuleBasedParser } from '../tickets/quick-input.parser.js';

describe('AI security boundaries', () => {
  it('encrypts with unique IVs, binds ciphertext to a provider, rejects tampering and missing master key', () => {
    const store = new AIKeyStore(new ConfigService({ AI_CONFIG_ENCRYPTION_KEY: randomBytes(32).toString('hex') }));
    const secret = randomBytes(24).toString('hex');
    const a = store.encrypt(secret, 'provider-a'); const b = store.encrypt(secret, 'provider-a');
    expect(a).not.toContain(secret); expect(a).not.toBe(b); expect(store.decrypt(a, 'provider-a')).toBe(secret);
    expect(() => store.decrypt(a, 'provider-b')).toThrow();
    expect(() => store.decrypt(a.slice(0, -4) + 'xxxx', 'provider-a')).toThrow();
    expect(new AIKeyStore(new ConfigService({ AI_CONFIG_ENCRYPTION_KEY: '' })).ready()).toBe(false);
  });
  it.each(['127.0.0.1', '10.1.1.1', '172.31.0.2', '192.168.0.1', '169.254.169.254', '100.64.0.1', '::1', '::ffff:127.0.0.1', 'fe80::1', 'fc00::1', '2002:7f00:1::'])('blocks nonpublic address %s', (address) => expect(isPublicAddress(address)).toBe(false));
  it.each(['http://example.com/v1', 'https://user:pass@example.com', 'https://example.com?key=secret', 'https://localhost/v1', 'https://127.1/v1', 'https://2130706433/v1', 'https://[::1]/v1'])('rejects unsafe base URL %s', (url) => expect(() => new AITransport(new ConfigService({ AI_ALLOWED_INTERNAL_ORIGINS: '' })).validateUrl(url)).toThrow());
  it('allows exact internal origins only when server configured', () => {
    const transport = new AITransport(new ConfigService({ AI_ALLOWED_INTERNAL_ORIGINS: 'http://127.0.0.1:9876' }));
    expect(transport.validateUrl('http://127.0.0.1:9876/v1').allowed).toBe(true);
    expect(() => transport.validateUrl('http://127.0.0.1:9877/v1')).toThrow();
  });
  it('requires strict schema and literal source facts, rejects IDs and hallucinations', () => {
    const raw = '浙江智享 M2600无点云，张伟负责，紧急';
    const value = { customerText: '浙江智享', issue: 'M2600无点云', assigneeText: '张伟', deviceText: 'M2600', priority: 'urgent' };
    expect(validateExtraction(value, raw)).toEqual(value);
    for (const bad of [{ ...value, customerId: 'id' }, { ...value, customerText: '虚构客户' }, { ...value, assigneeText: '李四' }, { ...value, issue: '调整巨帧后恢复' }, { ...value, priority: 'critical' }, { ...value, issue: null }, []]) expect(() => validateExtraction(bad, raw)).toThrow();
  });
  it('rule fallback handles the user-provided assignee phrase', () => {
    const r = new RuleBasedParser().parse('浙江智享 M2600无点云，张伟负责，紧急', { customers: [{ id: 'c', name: '浙江智享机器人' }], users: [{ id: 'u', name: '张伟' }], currentUserId: 'u' });
    expect(r.matchedAssignee?.id).toBe('u'); expect(r.issue).toBe('M2600无点云'); expect(r.priority).toBe('URGENT');
  });
});
