import { describe, expect, it } from 'vitest';
import { deviceHealth } from './device-health.js';

describe('deviceHealth', () => {
  it('无任何记录为正常', () => {
    expect(deviceHealth(0, 0)).toBe('OK');
  });

  it('维修 1 次为关注', () => {
    expect(deviceHealth(0, 1)).toBe('ATTENTION');
  });

  it('借测 6 次为关注', () => {
    expect(deviceHealth(6, 0)).toBe('ATTENTION');
  });

  it('维修 2 次为建议检查', () => {
    expect(deviceHealth(0, 2)).toBe('CHECK');
  });

  it('借测 10 次为建议检查', () => {
    expect(deviceHealth(10, 0)).toBe('CHECK');
  });

  it('借测 5 次维修 0 次仍为正常', () => {
    expect(deviceHealth(5, 0)).toBe('OK');
  });
});
