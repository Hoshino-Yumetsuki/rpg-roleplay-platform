// md-continue.js — Cursor 风「AI 续写/改写正文」引擎(CodeMirror 6)。
// 设计:LLM 只产正文文本(流式),前端确定性决定插哪(选中→改写替换 / 光标→续写插入),
// 插入内容高亮为「待定区」,Tab 接受 / Esc 放弃 —— 即 VSCode/Cursor 的 Cmd+K 应用到小说正文。
// 复用后端 POST /api/console_assistant/continue(SSE: token/done/error)。
import { StateField, StateEffect, Prec } from '@codemirror/state';
import { EditorView, Decoration, keymap, showPanel } from '@codemirror/view';

// ── 待定区状态(高亮 + 范围 + 改写时的原文,用于放弃还原)──────────────────
const setPending = StateEffect.define();   // {from,to,original,busy} | null

export const pendingField = StateField.define({
  create: () => null,
  update(val, tr) {
    let v = val;
    if (v && tr.docChanged) {
      // 流式插入会改文档,映射范围;from 用 -1(不随插入右移)、to 用 1(随插入扩张)。
      v = { ...v, from: tr.changes.mapPos(v.from, -1), to: tr.changes.mapPos(v.to, 1) };
    }
    for (const e of tr.effects) if (e.is(setPending)) v = e.value;
    return v;
  },
  provide: (f) => EditorView.decorations.from(f, (v) =>
    (v && v.to > v.from)
      ? Decoration.set([Decoration.mark({ class: 'mde-ai-pending' }).range(v.from, v.to)])
      : Decoration.none),
});

function pendingState(view) { return view.state.field(pendingField, false) || null; }

export function hasPending(view) { return !!pendingState(view); }

export function acceptPending(view) {
  if (!pendingState(view)) return false;
  view.dispatch({ effects: setPending.of(null) });
  view.focus();
  return true;
}

export function rejectPending(view) {
  const p = pendingState(view);
  if (!p) return false;
  // 删掉插入的待定文本;改写模式还原原文。
  view.dispatch({
    changes: { from: p.from, to: p.to, insert: p.original || '' },
    effects: setPending.of(null),
  });
  view.focus();
  return true;
}

// ── 顶部提示条(待定时显示 Tab 接受 / Esc 放弃)──────────────────────────
function pendingPanel(view) {
  const dom = document.createElement('div');
  dom.className = 'mde-ai-panel';
  const sync = (v) => {
    const p = v.state.field(pendingField, false);
    dom.style.display = p ? 'flex' : 'none';
    if (p) dom.textContent = p.busy ? 'AI 生成中…  Esc 取消' : 'AI 续写完成 —  Tab 接受   Esc 放弃';
  };
  sync(view);
  return { dom, update: (u) => sync(u.view) };
}

// ── 待定期间的快捷键(高优先级:Tab 接受 / Esc 放弃)────────────────────
const pendingKeymap = Prec.highest(keymap.of([
  { key: 'Tab', run: (view) => acceptPending(view) },
  { key: 'Mod-Enter', run: (view) => acceptPending(view) },
  { key: 'Escape', run: (view) => rejectPending(view) },
]));

export function aiContinueExtension() {
  return [pendingField, showPanel.of(pendingPanel), pendingKeymap];
}

// ── SSE 读取 ───────────────────────────────────────────────────────────
async function consumeSSE(res, onEvent, signal) {
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    if (signal?.aborted) { try { reader.cancel(); } catch (_) {} break; }
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const raw = buf.slice(0, i); buf = buf.slice(i + 2);
      let ev = 'message', data = '';
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) ev = line.slice(6).trim();
        else if (line.startsWith('data:')) data += line.slice(5).replace(/^ /, '');
      }
      if (data) { let j = {}; try { j = JSON.parse(data); } catch (_) {} onEvent(ev, j); }
    }
  }
}

const BEFORE_CAP = 4000, AFTER_CAP = 1500;

// ── 主入口:对一个 EditorView 跑一次续写/改写 ────────────────────────────
// opts: { scriptId, instruction, onState?(s) }  s ∈ 'busy'|'done'|'error'|'cancel'
export async function runContinue(view, opts = {}) {
  if (!view) return;
  if (pendingState(view)) rejectPending(view);   // 已有待定 → 先清掉再来

  const doc = view.state.doc;
  const sel = view.state.selection.main;
  const rewrite = !sel.empty;
  const selectionText = rewrite ? doc.sliceString(sel.from, sel.to) : '';
  const anchor = rewrite ? sel.from : sel.head;
  const before = doc.sliceString(Math.max(0, anchor - BEFORE_CAP), anchor);
  const afterStart = rewrite ? sel.to : sel.head;
  const after = doc.sliceString(afterStart, Math.min(doc.length, afterStart + AFTER_CAP));

  // 改写:先删选中,插入点 = 选中起点(原文存进待定区,放弃时还原)。
  let insertAt = anchor;
  if (rewrite) {
    view.dispatch({ changes: { from: sel.from, to: sel.to, insert: '' } });
    insertAt = sel.from;
  }
  // 建空待定区(busy)。
  view.dispatch({ effects: setPending.of({ from: insertAt, to: insertAt, original: selectionText, busy: true }) });
  view.focus();

  const ctrl = new AbortController();
  let pos = insertAt;        // 当前插入位置(待定区末尾)
  let got = false;
  opts.onState?.('busy');

  const insertToken = (text) => {
    if (!text) return;
    const p = pendingState(view);
    if (!p) { ctrl.abort(); return; }   // 用户中途取消
    view.dispatch({
      changes: { from: pos, insert: text },
      effects: setPending.of({ from: p.from, to: pos + text.length, original: p.original, busy: true }),
      scrollIntoView: true,
    });
    pos += text.length;
    got = true;
  };

  try {
    const res = await fetch('/api/console_assistant/continue', {
      method: 'POST', credentials: 'include', signal: ctrl.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        before, after, selection: selectionText,
        instruction: opts.instruction || '',
        mode: rewrite ? 'rewrite' : 'continue',
        script_id: opts.scriptId,
      }),
    });
    let errMsg = '';
    await consumeSSE(res, (ev, data) => {
      if (ev === 'token') insertToken(data.text || '');
      else if (ev === 'error') errMsg = data.message || '生成失败';
    }, ctrl.signal);

    const p = pendingState(view);
    if (!p) { opts.onState?.('cancel'); return; }
    if (errMsg && !got) {
      rejectPending(view);   // 没产出任何内容 + 报错 → 撤回待定区
      opts.onState?.('error', errMsg);
      try { window.__apiToast?.('AI 续写失败', { kind: 'danger', detail: errMsg }); } catch (_) {}
      return;
    }
    // 完成:留高亮 + 提示条,等用户 Tab 接受 / Esc 放弃。
    view.dispatch({ effects: setPending.of({ from: p.from, to: p.to, original: p.original, busy: false }) });
    opts.onState?.('done');
  } catch (e) {
    if (pendingState(view) && !got) rejectPending(view);
    opts.onState?.('error', e?.message);
    try { window.__apiToast?.('AI 续写出错', { kind: 'danger', detail: e?.message }); } catch (_) {}
  }
}

// ── Cmd+K 行内指令:复用全局 __prompt 取指令 → runContinue ────────────────
export function cmdKKeymap(getScriptId) {
  return keymap.of([{
    key: 'Mod-k',
    run: (view) => {
      (async () => {
        const sel = view.state.selection.main;
        const title = sel.empty ? 'AI 续写(光标处)' : 'AI 改写选中段';
        let instr = '';
        try {
          instr = await (window.__prompt
            ? window.__prompt({ title, label: '指令(可空;续写直接回车=顺势写)', default: '' })
            : Promise.resolve(prompt(title)));
        } catch (_) { instr = null; }
        if (instr === null) return;   // 取消
        runContinue(view, { scriptId: getScriptId?.(), instruction: instr });
      })();
      return true;
    },
  }]);
}
