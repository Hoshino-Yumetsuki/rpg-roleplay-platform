/* lib/storage.js — 统一 localStorage 封装语义回归(语义统一 #39)
 *
 * 重点守住替换调用点时依赖的边界:缺失→fallback、空串原样、JSON 解析失败→fallback、
 * 写入异常被吞掉(不炸调用方)、null 与 fallback 的区分。
 *
 * 注:本环境 jsdom 的 localStorage 是不可用 stub(setItem 非函数),故装一个
 * 受控内存版到 globalThis.localStorage,精确测 storage.js 的逻辑而非 jsdom 行为。
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { lsGet, lsSet, lsGetJSON, lsSetJSON, lsRemove } from '../lib/storage.js';

function makeMemoryStorage({ throwOn } = {}) {
  const map = new Map();
  return {
    getItem(k) { if (throwOn === 'get') throw new Error('boom'); return map.has(k) ? map.get(k) : null; },
    setItem(k, v) { if (throwOn === 'set') throw new Error('quota'); map.set(k, String(v)); },
    removeItem(k) { if (throwOn === 'remove') throw new Error('boom'); map.delete(k); },
  };
}

let original;
function install(storage) {
  Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true, writable: true });
}

describe('lib/storage', () => {
  beforeEach(() => {
    original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
    install(makeMemoryStorage());
  });
  afterEach(() => {
    if (original) Object.defineProperty(globalThis, 'localStorage', original);
  });

  describe('lsGet / lsSet', () => {
    it('returns fallback (default null) when key missing', () => {
      expect(lsGet('nope')).toBe(null);
      expect(lsGet('nope', 'def')).toBe('def');
    });

    it('round-trips a raw string value', () => {
      lsSet('k', 'hello');
      expect(lsGet('k')).toBe('hello');
    });

    it('returns stored empty string as-is (not fallback)', () => {
      lsSet('k', '');
      expect(lsGet('k', 'fallback')).toBe('');
    });

    it('|| fallback idiom still works for missing keys', () => {
      // 调用点常写 lsGet(k) || 'x';缺失返回 null → 取 'x'
      expect(lsGet('missing') || 'serif').toBe('serif');
    });

    it('lsSet swallows write errors without throwing', () => {
      install(makeMemoryStorage({ throwOn: 'set' }));
      expect(() => lsSet('k', 'v')).not.toThrow();
    });

    it('lsGet returns fallback when getItem throws', () => {
      install(makeMemoryStorage({ throwOn: 'get' }));
      expect(lsGet('k', 'safe')).toBe('safe');
    });
  });

  describe('lsGetJSON / lsSetJSON', () => {
    it('round-trips an object', () => {
      lsSetJSON('o', { a: 1, b: [2, 3] });
      expect(lsGetJSON('o')).toEqual({ a: 1, b: [2, 3] });
    });

    it('returns fallback when key missing', () => {
      expect(lsGetJSON('nope', {})).toEqual({});
      expect(lsGetJSON('nope')).toBe(null);
    });

    it('returns fallback on malformed JSON instead of throwing', () => {
      lsSet('bad', '{not json');
      expect(lsGetJSON('bad', { ok: false })).toEqual({ ok: false });
    });

    it('treats stored literal null as fallback', () => {
      lsSet('n', 'null');
      expect(lsGetJSON('n', { def: true })).toEqual({ def: true });
    });

    it('lsSetJSON swallows write errors without throwing', () => {
      install(makeMemoryStorage({ throwOn: 'set' }));
      expect(() => lsSetJSON('o', { a: 1 })).not.toThrow();
    });
  });

  describe('lsRemove', () => {
    it('removes a key', () => {
      lsSet('k', 'v');
      lsRemove('k');
      expect(lsGet('k')).toBe(null);
    });

    it('swallows errors without throwing', () => {
      install(makeMemoryStorage({ throwOn: 'remove' }));
      expect(() => lsRemove('k')).not.toThrow();
    });
  });
});
