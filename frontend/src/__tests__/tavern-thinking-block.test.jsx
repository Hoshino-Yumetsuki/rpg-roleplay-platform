/**
 * tavern-thinking-block.test.jsx — 酒馆思考流渲染修复回归测试。
 *
 * 生产事故:思考流(reasoning)与正文(content)被 NarrativeBlock 互斥渲染 ——
 * 只要 _thinking 非空,整条消息就渲染成思考气泡,正文被压制。修复后思考流是
 * 独立的可折叠块(默认折叠),与正文上下分区共存。
 *
 * 本测试覆盖独立的 TavernThinkingBlock 组件的确定性行为:
 *   · 默认折叠(不渲染推理正文)
 *   · 流式中无 content(thinking=true)→ 显示「思考中…」+ spinner
 *   · 流式结束 / 有 content(thinking=false)→ 静态「思考过程」折叠条,无 spinner
 *   · 点击展开 → 露出推理文本
 *   · 无文本且非 thinking → 不渲染
 */
import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TavernThinkingBlock } from '../tavern-app.jsx';

describe('TavernThinkingBlock — 思考流独立可折叠块', () => {
  it('默认折叠:不渲染推理正文,但有「思考过程」标签', () => {
    render(<TavernThinkingBlock text="我在推理某事" thinking={false} />);
    expect(screen.getByText('思考过程')).toBeTruthy();
    expect(screen.queryByText('我在推理某事')).toBeNull();
  });

  it('点击展开 → 露出推理文本', () => {
    render(<TavernThinkingBlock text="我在推理某事" thinking={false} />);
    fireEvent.click(screen.getByText('思考过程'));
    expect(screen.getByText('我在推理某事')).toBeTruthy();
  });

  it('流式中无 content(thinking=true)→ 显示「思考中…」', () => {
    const { container } = render(<TavernThinkingBlock text="" thinking={true} />);
    expect(screen.getByText('思考中…')).toBeTruthy();
    // spinner 元素在场(.gc-spinner)
    expect(container.querySelector('.gc-spinner')).toBeTruthy();
  });

  it('流式结束 / 有 content(thinking=false)→ 静态条,无 spinner', () => {
    const { container } = render(<TavernThinkingBlock text="推理" thinking={false} />);
    expect(screen.getByText('思考过程')).toBeTruthy();
    expect(screen.queryByText('思考中…')).toBeNull();
    expect(container.querySelector('.gc-spinner')).toBeNull();
  });

  it('无文本且非 thinking → 不渲染', () => {
    const { container } = render(<TavernThinkingBlock text="" thinking={false} />);
    expect(container.firstChild).toBeNull();
  });

  it('thinking=true 但仍有累积文本时,展开能看到已到的推理片段', () => {
    render(<TavernThinkingBlock text="部分推理…" thinking={true} />);
    // 折叠态:标签是「思考中…」
    expect(screen.getByText('思考中…')).toBeTruthy();
    fireEvent.click(screen.getByText('思考中…'));
    expect(screen.getByText('部分推理…')).toBeTruthy();
  });
});
