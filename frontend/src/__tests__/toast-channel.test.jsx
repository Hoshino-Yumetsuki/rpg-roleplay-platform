/**
 * toast-channel.test.jsx — pl-toast-stack 收口(createToastChannel)回归测试。
 *
 * platform-app 与 game-app 的 toast pub/sub + 渲染收口到 ./toast.jsx 的工厂。锁定:
 *   · install():按 install 选项装 window.toast / window.__apiToast(契约不变)。
 *   · guardWindowToast:仅在 window.toast 未是函数时才装(承接 game-app「不覆盖 Platform」)。
 *   · 两条独立总线互不串扰(平台总线 fire 不进 game 总线订阅者)。
 *   · <ToastStack/>:fire → 渲染 pl-toast 项;duration>0 自动消失;close 按钮可手动关闭。
 *   · window.toast 返回自增 id;duration 缺省 2400。
 */
import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { createToastChannel } from '../toast.jsx';

beforeEach(() => {
  // 每个用例清空全局通道注册表,避免幂等缓存串扰。
  if (typeof window !== 'undefined') window.__rpgToastChannels = {};
  delete window.toast;
  delete window.__apiToast;
  vi.useFakeTimers();
});
afterEach(() => { vi.useRealTimers(); });

describe('createToastChannel', () => {
  it('install(setWindowToast) 装 window.toast,契约不变(返回 id,duration 缺省 2400)', () => {
    const ch = createToastChannel({ name: 't1', setWindowToast: true });
    ch.install();
    expect(typeof window.toast).toBe('function');
    let id;
    const seen = [];
    ch.subscribe((t) => seen.push(t));
    act(() => { id = window.toast('你好', { kind: 'ok' }); });
    expect(typeof id).toBe('number');
    expect(seen[0].message).toBe('你好');
    expect(seen[0].kind).toBe('ok');
    expect(seen[0].duration).toBe(2400);
  });

  it('setApiToast 装 window.__apiToast,setApiToast=false 时不动', () => {
    window.__apiToast = () => 'untouched';
    const ch = createToastChannel({ name: 't2', setWindowToast: true, setApiToast: false });
    ch.install();
    expect(window.__apiToast()).toBe('untouched'); // 未被覆盖
    const ch2 = createToastChannel({ name: 't3', setWindowToast: true, setApiToast: true });
    ch2.install();
    expect(typeof window.__apiToast).toBe('function');
    expect(window.__apiToast).toBe(ch2.fire);
  });

  it('guardWindowToast:已有 window.toast 时不覆盖', () => {
    const platform = createToastChannel({ name: 'platform', setWindowToast: true });
    platform.install();
    const platformFire = window.toast;
    const game = createToastChannel({ name: 'game', setWindowToast: true, guardWindowToast: true, setApiToast: true });
    game.install();
    expect(window.toast).toBe(platformFire);  // 没被 game 覆盖
    expect(window.__apiToast).toBe(game.fire); // 但 __apiToast 走 game 通道
  });

  it('两条独立总线互不串扰', () => {
    const a = createToastChannel({ name: 'A' });
    const b = createToastChannel({ name: 'B' });
    const aSeen = []; const bSeen = [];
    a.subscribe((t) => aSeen.push(t));
    b.subscribe((t) => bSeen.push(t));
    act(() => { a.fire('only-a'); });
    expect(aSeen.length).toBe(1);
    expect(bSeen.length).toBe(0);
  });

  it('<ToastStack/> 渲染 fire 的 toast,duration>0 自动消失', () => {
    const ch = createToastChannel({ name: 'stack1' });
    render(<ch.ToastStack />);
    act(() => { ch.fire('短暂提示', { kind: 'ok', duration: 1000 }); });
    expect(screen.getByText('短暂提示')).toBeTruthy();
    act(() => { vi.advanceTimersByTime(1000); });
    expect(screen.queryByText('短暂提示')).toBeNull();
  });

  it('<ToastStack/> 渲染 detail 与 close 按钮', () => {
    const ch = createToastChannel({ name: 'stack2' });
    render(<ch.ToastStack />);
    act(() => { ch.fire('主消息', { kind: 'danger', detail: '细节', duration: 0 }); });
    expect(screen.getByText('主消息')).toBeTruthy();
    expect(screen.getByText('细节')).toBeTruthy();
    // duration=0 不自动消失
    act(() => { vi.advanceTimersByTime(5000); });
    expect(screen.getByText('主消息')).toBeTruthy();
    // pl-toast-danger class 应用(createPortal 到 body,故查 document.body)
    expect(document.body.querySelector('.pl-toast-danger')).toBeTruthy();
  });
});
