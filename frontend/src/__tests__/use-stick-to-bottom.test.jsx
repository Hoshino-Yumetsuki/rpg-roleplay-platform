/**
 * use-stick-to-bottom.test.jsx — 粘底守卫 hook 回归测试。
 *
 * 四处聊天流(桌面游戏/桌面酒馆/手机游戏/手机酒馆)各自手抄的滚动守卫已收口到
 * useStickToBottom。本测试锁定逐字保留的确定性行为:
 *   · onScroll:距底 < 80px → 在底部(不显示「回到最新」);离开底部 → showJump=true。
 *   · 跟随策略:首屏 / 末条玩家 → 强制到底;用户已上滚或实时距底>360 → 不跟随。
 *   · jumpToBottom:smooth 跳底并隐藏按钮。
 *   · withButton=false:不维护 showJump(手机游戏)。
 */
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useStickToBottom } from '../hooks/useStickToBottom.js';

// 造一个可控的滚动容器:可设 scrollHeight/clientHeight/scrollTop,记录 scrollTo 调用。
function makeEl({ scrollHeight = 1000, clientHeight = 400, scrollTop = 600 } = {}) {
  const listeners = {};
  return {
    scrollHeight, clientHeight, scrollTop,
    scrollToCalls: [],
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener: (ev, fn) => { listeners[ev] = (listeners[ev] || []).filter((f) => f !== fn); },
    scrollTo: function (arg) { this.scrollToCalls.push(arg); if (arg && typeof arg.top === 'number') this.scrollTop = arg.top; },
    __fire: (ev) => (listeners[ev] || []).forEach((fn) => fn()),
  };
}

beforeEach(() => {
  global.requestAnimationFrame = (cb) => { cb(); return 1; };
  global.cancelAnimationFrame = () => {};
});

describe('useStickToBottom', () => {
  it('onScroll:在底部(距底<80)→ showJump=false;离开底部 → showJump=true', () => {
    const el = makeEl({ scrollHeight: 1000, clientHeight: 400, scrollTop: 600 }); // 距底 = 1000-600-400 = 0
    const ref = { current: el };
    const { result } = renderHook(() =>
      useStickToBottom(ref, { deps: [0], lastIsUser: false, hasContent: false, withButton: true })
    );
    act(() => { el.scrollTop = 600; el.__fire('scroll'); }); // 距底 0 < 80 → 在底部
    expect(result.current.showJump).toBe(false);
    act(() => { el.scrollTop = 100; el.__fire('scroll'); }); // 距底 = 1000-100-400 = 500 → 离开底部
    expect(result.current.showJump).toBe(true);
  });

  it('首屏(hasContent)→ 强制 scrollTop = scrollHeight(instant)', () => {
    const el = makeEl({ scrollHeight: 2000, clientHeight: 400, scrollTop: 0 });
    const ref = { current: el };
    renderHook(() => useStickToBottom(ref, { deps: [1], lastIsUser: false, hasContent: true, mode: 'instant' }));
    expect(el.scrollTop).toBe(2000);
  });

  it('末条玩家 → 强制到底,即使之前不在底部', () => {
    const el = makeEl({ scrollHeight: 3000, clientHeight: 400, scrollTop: 0 });
    const ref = { current: el };
    // 先离开底部
    renderHook(() => useStickToBottom(ref, { deps: [1], lastIsUser: true, hasContent: false, mode: 'instant' }));
    expect(el.scrollTop).toBe(3000);
  });

  it('双守卫:用户已上滚(距底>360 且非首屏/非末条玩家)→ 不跟随', () => {
    const el = makeEl({ scrollHeight: 5000, clientHeight: 400, scrollTop: 100 }); // 距底 = 4500 > 360
    const ref = { current: el };
    const { rerender } = renderHook(
      ({ d }) => useStickToBottom(ref, { deps: [d], lastIsUser: false, hasContent: true, mode: 'instant' }),
      { initialProps: { d: 1 } }
    );
    // 首屏已消费(scrollTop 被设为 5000),复位模拟用户上滚
    el.scrollTop = 100;
    el.__fire('scroll');           // atBottom=false
    rerender({ d: 2 });            // 新内容到达,但用户在上文 → 不跟随
    expect(el.scrollTop).toBe(100);
  });

  it('jumpToBottom:smooth 跳底 + 隐藏按钮', () => {
    const el = makeEl({ scrollHeight: 1200, clientHeight: 400, scrollTop: 0 });
    const ref = { current: el };
    const { result } = renderHook(() =>
      useStickToBottom(ref, { deps: [0], lastIsUser: false, hasContent: false, withButton: true })
    );
    act(() => { el.scrollTop = 0; el.__fire('scroll'); });
    expect(result.current.showJump).toBe(true);
    act(() => { result.current.jumpToBottom(); });
    expect(el.scrollToCalls.some((c) => c.behavior === 'smooth' && c.top === 1200)).toBe(true);
    expect(result.current.showJump).toBe(false);
  });

  it('withButton=false(手机游戏):onScroll 不维护 showJump', () => {
    const el = makeEl({ scrollHeight: 1000, clientHeight: 400, scrollTop: 0 });
    const ref = { current: el };
    const { result } = renderHook(() =>
      useStickToBottom(ref, { deps: [0], lastIsUser: false, hasContent: false, withButton: false })
    );
    act(() => { el.scrollTop = 0; el.__fire('scroll'); }); // 离开底部
    expect(result.current.showJump).toBe(false); // 仍 false
  });

  it('mode=smooth:跟随用 scrollTo smooth(手机游戏)', () => {
    const el = makeEl({ scrollHeight: 2400, clientHeight: 400, scrollTop: 0 });
    const ref = { current: el };
    renderHook(() => useStickToBottom(ref, { deps: [1], lastIsUser: true, hasContent: false, mode: 'smooth', withButton: false }));
    expect(el.scrollToCalls.some((c) => c.behavior === 'smooth' && c.top === 2400)).toBe(true);
  });

  it('scrollOnMount:挂载即 auto 滚底(手机游戏)', () => {
    const el = makeEl({ scrollHeight: 1800, clientHeight: 400, scrollTop: 0 });
    const ref = { current: el };
    renderHook(() => useStickToBottom(ref, { deps: [0], lastIsUser: false, hasContent: false, mode: 'smooth', withButton: false, scrollOnMount: true }));
    expect(el.scrollToCalls.some((c) => c.behavior === 'auto' && c.top === 1800)).toBe(true);
  });
});
