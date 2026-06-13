/**
 * tavern-tool-inline-order.test.jsx — 酒馆工具调用按时间内联 回归测试。
 *
 * 生产 bug:工具调用永远渲染在正文最顶部,不按实际先后顺序(非 Claude 风)。
 * 根因:渲染固定「工具块在前、正文在后」。修复:每个工具带 anchor(=触发时的正文长度),
 * 渲染时按 anchor 把工具卡片内联到正文对应位置。
 *
 * 本测试锁住 renderNarrativeWithInlineTools 的确定性顺序:
 *   · 工具出现在它 anchor 对应的文本位置(前文 → 工具 → 后文)
 *   · anchor=0 的工具排在所有正文之前
 *   · 同一 anchor 的多个工具合并成一组
 *   · anchor 超界被 clamp 到文末
 */
import React from 'react';
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { renderNarrativeWithInlineTools } from '../game-app.jsx';

const FakeMd = ({ text }) => <span data-seg="text">{text}</span>;
const renderTool = (ops) => <span data-seg="tool">{ops.map((o) => o.tool).join(',')}</span>;

function seq(text, ops) {
  const nodes = renderNarrativeWithInlineTools(text, ops, renderTool, false, FakeMd);
  const { container } = render(<div>{nodes}</div>);
  return [...container.querySelectorAll('[data-seg]')].map((el) => ({
    kind: el.getAttribute('data-seg'),
    text: el.textContent,
  }));
}

describe('renderNarrativeWithInlineTools — 工具按 anchor 内联', () => {
  it('工具内联在前文与后文之间(前文→工具→后文)', () => {
    expect(seq('AAAABBBB', [{ tool: 'roll_dice', anchor: 4 }])).toEqual([
      { kind: 'text', text: 'AAAA' },
      { kind: 'tool', text: 'roll_dice' },
      { kind: 'text', text: 'BBBB' },
    ]);
  });

  it('anchor=0 的工具排在所有正文之前(不再"置顶"是因为它本就在最前)', () => {
    expect(seq('hello', [{ tool: 'set_flag', anchor: 0 }])).toEqual([
      { kind: 'tool', text: 'set_flag' },
      { kind: 'text', text: 'hello' },
    ]);
  });

  it('多工具按各自 anchor 分别内联,顺序正确', () => {
    expect(seq('AABBCC', [
      { tool: 't2', anchor: 4 },
      { tool: 't1', anchor: 2 },
    ])).toEqual([
      { kind: 'text', text: 'AA' },
      { kind: 'tool', text: 't1' },
      { kind: 'text', text: 'BB' },
      { kind: 'tool', text: 't2' },
      { kind: 'text', text: 'CC' },
    ]);
  });

  it('同一 anchor 的多个工具合并成一组', () => {
    expect(seq('AAAA', [
      { tool: 'a', anchor: 2 },
      { tool: 'b', anchor: 2 },
    ])).toEqual([
      { kind: 'text', text: 'AA' },
      { kind: 'tool', text: 'a,b' },
      { kind: 'text', text: 'AA' },
    ]);
  });

  it('anchor 超界 clamp 到文末;非常规旧 op(无 anchor)落到文末', () => {
    expect(seq('AAAA', [{ tool: 'big', anchor: 999 }])).toEqual([
      { kind: 'text', text: 'AAAA' },
      { kind: 'tool', text: 'big' },
    ]);
    expect(seq('AAAA', [{ tool: 'legacy' }])).toEqual([
      { kind: 'text', text: 'AAAA' },
      { kind: 'tool', text: 'legacy' },
    ]);
  });
});
