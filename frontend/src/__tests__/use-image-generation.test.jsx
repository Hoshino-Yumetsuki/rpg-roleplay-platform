/**
 * use-image-generation.test.jsx — 生图内核 hook 回归测试。
 *
 * GenerateImageModal 与 MediaStudio 的 generate + 每 2s 轮询 + creds 分类内核收口到
 * useImageGeneration。锁定逐字保留的两宿主语义:
 *   · generate → 轮询到 done → onDone(url)。
 *   · 轮询到 failed → 凭据错误分类(isCredentialsError)/普通错误。
 *   · GenerateImageModal:无 image_id → noImageIdMsg;轮询 catch 停并报错。
 *   · MediaStudio:inspect 拦 quota/creds;轮询 catch 重试(2500);done 需 r.url。
 */
import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useImageGeneration } from '../hooks/useImageGeneration.js';

function setApi({ generate, get }) {
  window.api = { images: { generate, get } };
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); delete window.api; });

describe('useImageGeneration', () => {
  it('generate → 轮询 pending → done → onDone(url)', async () => {
    let getCalls = 0;
    setApi({
      generate: vi.fn(async () => ({ image_id: 'img1' })),
      get: vi.fn(async () => {
        getCalls += 1;
        return getCalls < 2 ? { status: 'pending' } : { status: 'done', url: 'http://x/y.png' };
      }),
    });
    const onDone = vi.fn();
    const { result } = renderHook(() => useImageGeneration({ onDone }));
    await act(async () => { await result.current.generate({ prompt: 'p' }, {}); });
    // 第一次 get = pending → 排 2s
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(onDone).toHaveBeenCalledWith('http://x/y.png');
    expect(result.current.generating).toBe(false);
  });

  it('轮询 failed 普通错误 → error 设置,非 creds', async () => {
    setApi({
      generate: vi.fn(async () => ({ image_id: 'imgF' })),
      get: vi.fn(async () => ({ status: 'failed', error: '上游 500' })),
    });
    const { result } = renderHook(() => useImageGeneration({}));
    await act(async () => { await result.current.generate({ prompt: 'p' }, { failFallback: '生成失败' }); });
    expect(result.current.error).toBe('上游 500');
    expect(result.current.credsMissing).toBe(false);
  });

  it('轮询 failed 凭据错误 → credsMissing=true + credsErrorText', async () => {
    setApi({
      generate: vi.fn(async () => ({ image_id: 'imgC' })),
      get: vi.fn(async () => ({ status: 'failed', error: 'credentials_required' })),
    });
    const { result } = renderHook(() => useImageGeneration({}));
    await act(async () => {
      await result.current.generate({ prompt: 'p' }, { credsErrorText: '请先配置 Key' });
    });
    expect(result.current.credsMissing).toBe(true);
    expect(result.current.error).toBe('请先配置 Key');
  });

  it('GenerateImageModal 语义:无 image_id → noImageIdMsg', async () => {
    setApi({
      generate: vi.fn(async () => ({})),  // 无 image_id
      get: vi.fn(),
    });
    const { result } = renderHook(() => useImageGeneration({}));
    await act(async () => {
      await result.current.generate({ prompt: 'p' }, { noImageIdMsg: '服务端未返回任务 ID' });
    });
    expect(result.current.error).toBe('服务端未返回任务 ID');
  });

  it('MediaStudio 语义:inspect 拦 quota → onFail', async () => {
    setApi({
      generate: vi.fn(async () => ({ code: 'quota_exceeded' })),
      get: vi.fn(),
    });
    const onFail = vi.fn();
    const { result } = renderHook(() => useImageGeneration({ onFail }));
    await act(async () => {
      await result.current.generate({ prompt: 'p' }, {
        inspect: (r, { fail }) => {
          if (r && r.code === 'quota_exceeded') { fail('今日生图次数已达上限'); return true; }
          return false;
        },
      });
    });
    expect(onFail).toHaveBeenCalled();
    expect(onFail.mock.calls[0][0]).toBe('今日生图次数已达上限');
  });

  it('MediaStudio 语义:done 需 r.url(requireUrl)+ doneFromStatus(r.ok)', async () => {
    let n = 0;
    setApi({
      generate: vi.fn(async () => ({ image_id: 'imgU' })),
      get: vi.fn(async () => { n += 1; return n < 2 ? { ok: true } /*无 url → 继续轮询*/ : { ok: true, url: 'u://ok' }; }),
    });
    const onDone = vi.fn();
    const { result } = renderHook(() => useImageGeneration({ onDone }));
    await act(async () => {
      await result.current.generate({ prompt: 'p' }, {
        doneFromStatus: (r) => r && (r.status || (r.ok && 'done')),
        requireUrl: true,
      });
    });
    // 第一次 get: ok 但无 url → status='done' 但 requireUrl 不满足 → 继续轮询
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(onDone).toHaveBeenCalledWith('u://ok');
  });

  it('stop():卸载/关闭后不再继续轮询', async () => {
    const get = vi.fn(async () => ({ status: 'pending' }));
    setApi({ generate: vi.fn(async () => ({ image_id: 'imgS' })), get });
    const { result } = renderHook(() => useImageGeneration({}));
    await act(async () => { await result.current.generate({ prompt: 'p' }, {}); });
    const callsAfterGen = get.mock.calls.length; // 1
    act(() => { result.current.stop(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(get.mock.calls.length).toBe(callsAfterGen); // 没有新增轮询
  });
});
