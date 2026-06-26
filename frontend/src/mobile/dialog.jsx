/* mobile/dialog.jsx — 移动端命令式确认/输入弹窗(底抽屉,取代裸 window.confirm/prompt)
 *
 * 背景:移动各页此前大量调浏览器原生 window.confirm/window.prompt —— 阻塞式、系统样式、
 * 与 app 视觉割裂、无法下滑关闭。本 Host 提供与【桌面 platform-app DialogHost 完全相同】的
 * 命令式契约,但渲染为 mobile/Sheet 的底抽屉(grip 拉手 + 向下拖拽关闭 + 安全区):
 *
 *   await window.__confirm({ title, message, danger, confirmText, cancelText }) → bool
 *   await window.__prompt ({ title, label, default, confirmText })             → string|null
 *
 * 这样移动页改造只需把 `window.confirm(x)` → `await window.__confirm({ message: x })`、
 * `window.prompt(t,d)` → `await window.__prompt({ title: t, default: d })`,与桌面同调用约定,
 * 零分叉。MobileRoot 挂载本 Host;卸载时还原全局,绝不影响桌面宿主的同名全局。
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Sheet, ConfirmSheet } from './Sheet.jsx';

export function MobileDialogHost() {
  const { t } = useTranslation();
  const [dlg, setDlg] = useState(null);
  const [value, setValue] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const prevConfirm = window.__confirm;
    const prevPrompt = window.__prompt;
    window.__confirm = (o = {}) => new Promise((resolve) => setDlg({
      type: 'confirm', resolve,
      title: o.title || t('common.confirm'),
      message: o.message || o.body || '',
      danger: !!o.danger,
      confirmText: o.confirmText || o.confirmLabel || t('common.confirm'),
      cancelText: o.cancelText || o.cancelLabel || t('common.cancel'),
    }));
    window.__prompt = (o = {}) => {
      setValue(o.default || '');
      return new Promise((resolve) => setDlg({
        type: 'prompt', resolve,
        title: o.title || t('platform.shell.prompt_title'),
        label: o.label || '',
        confirmText: o.confirmText || t('common.confirm'),
        cancelText: o.cancelText || t('common.cancel'),
      }));
    };
    return () => {
      if (window.__confirm && window.__confirm.__mobile) window.__confirm = prevConfirm;
      if (window.__prompt && window.__prompt.__mobile) window.__prompt = prevPrompt;
    };
  }, [t]);

  // mark our installs so cleanup only reverts ours
  useEffect(() => {
    if (window.__confirm) window.__confirm.__mobile = true;
    if (window.__prompt) window.__prompt.__mobile = true;
  });

  // prompt 打开后自动聚焦输入框
  useEffect(() => {
    if (dlg && dlg.type === 'prompt') {
      const id = setTimeout(() => { try { inputRef.current?.focus(); } catch (_) {} }, 80);
      return () => clearTimeout(id);
    }
  }, [dlg]);

  const close = useCallback((val) => {
    setDlg((d) => { if (d) { try { d.resolve(val); } catch (_) {} } return null; });
  }, []);

  if (!dlg) return null;

  if (dlg.type === 'confirm') {
    return (
      <ConfirmSheet
        open
        title={dlg.title}
        body={dlg.message}
        danger={dlg.danger}
        confirmLabel={dlg.confirmText}
        cancelLabel={dlg.cancelText}
        onConfirm={() => close(true)}
        onCancel={() => close(false)}
      />
    );
  }

  // prompt
  return (
    <Sheet open title={dlg.title} onClose={() => close(null)}>
      {dlg.label && <div className="confirm-note" style={{ marginBottom: 8 }}>{dlg.label}</div>}
      <input
        ref={inputRef}
        className="pl-input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') close(value || ''); }}
        style={{ width: '100%', boxSizing: 'border-box' }}
      />
      <div className="sheet-actions" style={{ marginTop: 12 }}>
        <button className="sheet-btn" onClick={() => close(null)}>{dlg.cancelText}</button>
        <button className="sheet-btn primary" onClick={() => close(value || '')}>{dlg.confirmText}</button>
      </div>
    </Sheet>
  );
}

export default MobileDialogHost;
