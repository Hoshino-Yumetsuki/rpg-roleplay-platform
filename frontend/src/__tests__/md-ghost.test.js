/**
 * md-ghost.test.js — 内联续写(ghost text)状态机回归。
 * 真 EditorView(jsdom)挂 ghostCompleteExtension:
 *   · setGhost → hasGhost + 幽灵 DOM 渲染。
 *   · acceptGhost(Tab)→ 文本插入光标处、光标移末尾、幽灵清除。
 *   · 继续打字 / 移动光标 → 幽灵自动作废。
 *   · 触发器:打字停顿后调 fetch 并 setGhost(用假 fetch + 假定时器)。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { ghostCompleteExtension, ghostField, hasGhost, acceptGhost } from '../lib/md-ghost';

// 直接驱动 setGhost effect 用的内部 effect 不导出 → 用 acceptGhost/hasGhost + 触发器路径验证。
// 为单测 set 路径,这里用触发器:开启 enabled + 假 fetch,模拟打字。

function mkView(text, opts) {
  const parent = document.createElement('div');
  document.body.appendChild(parent);
  return new EditorView({
    state: EditorState.create({ doc: text, extensions: [ghostCompleteExtension(opts || {})] }),
    parent,
  });
}

describe('md-ghost 触发 + 采纳', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it('打字停顿 → fetch → 渲染幽灵;Tab 采纳后插入并清除', async () => {
    const fetchCompletion = vi.fn(async () => ',夜色正浓。');
    const v = mkView('第一行文字', { isEnabled: () => true, fetchCompletion, delay: 100 });
    // 把光标放末尾,模拟「打字」事务(userEvent input.type)
    const end = v.state.doc.length;
    v.dispatch({ changes: { from: end, insert: '。' }, selection: { anchor: end + 1 }, userEvent: 'input.type' });
    expect(fetchCompletion).not.toHaveBeenCalled();           // 还在防抖
    await vi.advanceTimersByTimeAsync(120);                    // 触发防抖 + await fetch
    expect(fetchCompletion).toHaveBeenCalledTimes(1);
    expect(hasGhost(v)).toBe(true);
    expect(v.dom.querySelector('.mde-ghost')?.textContent).toBe(',夜色正浓。');
    const before = v.state.doc.toString();
    // Tab 采纳
    const ok = acceptGhost(v);
    expect(ok).toBe(true);
    expect(hasGhost(v)).toBe(false);
    expect(v.state.doc.toString()).toBe(before + ',夜色正浓。');
    expect(v.state.selection.main.head).toBe(v.state.doc.length);
    v.destroy();
  });

  it('幽灵出现后继续打字 → 自动作废', async () => {
    const v = mkView('abc', { isEnabled: () => true, fetchCompletion: async () => 'XYZ', delay: 50 });
    const end = v.state.doc.length;
    v.dispatch({ changes: { from: end, insert: 'd' }, selection: { anchor: end + 1 }, userEvent: 'input.type' });
    await vi.advanceTimersByTimeAsync(60);
    expect(hasGhost(v)).toBe(true);
    // 再打一个字 → docChanged → 幽灵清
    const e2 = v.state.doc.length;
    v.dispatch({ changes: { from: e2, insert: 'e' }, selection: { anchor: e2 + 1 }, userEvent: 'input.type' });
    expect(hasGhost(v)).toBe(false);
    v.destroy();
  });

  it('移动光标 → 幽灵作废', async () => {
    const v = mkView('hello world', { isEnabled: () => true, fetchCompletion: async () => '!!', delay: 50 });
    const end = v.state.doc.length;
    v.dispatch({ changes: { from: end, insert: '.' }, selection: { anchor: end + 1 }, userEvent: 'input.type' });
    await vi.advanceTimersByTimeAsync(60);
    expect(hasGhost(v)).toBe(true);
    v.dispatch({ selection: { anchor: 0 } });                  // 光标跳到行首
    expect(hasGhost(v)).toBe(false);
    v.destroy();
  });

  it('开关关闭 → 不 fetch、不出幽灵', async () => {
    const fetchCompletion = vi.fn(async () => 'no');
    const v = mkView('xyz', { isEnabled: () => false, fetchCompletion, delay: 50 });
    const end = v.state.doc.length;
    v.dispatch({ changes: { from: end, insert: 'q' }, selection: { anchor: end + 1 }, userEvent: 'input.type' });
    await vi.advanceTimersByTimeAsync(80);
    expect(fetchCompletion).not.toHaveBeenCalled();
    expect(hasGhost(v)).toBe(false);
    v.destroy();
  });

  it('采纳后(input.complete)不再触发新 fetch', async () => {
    const fetchCompletion = vi.fn(async () => '续');
    const v = mkView('one', { isEnabled: () => true, fetchCompletion, delay: 50 });
    const end = v.state.doc.length;
    v.dispatch({ changes: { from: end, insert: 't' }, selection: { anchor: end + 1 }, userEvent: 'input.type' });
    await vi.advanceTimersByTimeAsync(60);
    expect(fetchCompletion).toHaveBeenCalledTimes(1);
    acceptGhost(v);                                           // userEvent input.complete
    await vi.advanceTimersByTimeAsync(120);
    expect(fetchCompletion).toHaveBeenCalledTimes(1);         // 没有第二次
    v.destroy();
  });
});
