/* components/DesktopDialogHost.jsx — 命令式确认/输入弹窗 Host(给非 platform-app 的入口用)
 *
 * platform-app.jsx 在桌面主壳里安装了 window.__confirm / window.__prompt(Cloudscape 弹窗)。
 * 但独立入口(entries/game-console.jsx 的游戏台)不经 platform-app → 这两个全局不存在 →
 * 该入口里的 onNew 新建确认、game-panels 的记忆/时间线 prompt/confirm 全部回退到浏览器
 * 原生 confirm()/prompt()(阻塞式、系统样式、与 app 割裂)。
 *
 * 本 Host 用站内共享的 ConfirmDialog + Modal 提供与 platform-app 完全相同的命令式契约:
 *   await window.__confirm({ title, message, danger, confirmText }) → bool
 *   await window.__prompt ({ title, label, default, confirmText })  → string|null
 * 挂载在游戏台 App 根部即可;卸载时还原全局。一个页面只会加载一个入口,故与 platform-app 不冲突。
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import ConfirmDialog from './ConfirmDialog.jsx';
import Modal from './Modal.jsx';

export default function DesktopDialogHost() {
  const { t } = useTranslation();
  const [dlg, setDlg] = useState(null);
  const [value, setValue] = useState('');
  const inputRef = useRef(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const prevConfirm = window.__confirm;
    const prevPrompt = window.__prompt;
    const c = (o = {}) => new Promise((resolve) => setDlg({
      type: 'confirm', resolve,
      title: o.title || t('common.confirm'),
      message: o.message || o.body || '',
      danger: !!o.danger,
      confirmText: o.confirmText || o.confirmLabel || t('common.confirm'),
      cancelText: o.cancelText || o.cancelLabel || t('common.cancel'),
    }));
    const p = (o = {}) => {
      setValue(o.default || '');
      return new Promise((resolve) => setDlg({
        type: 'prompt', resolve,
        title: o.title || t('common.confirm'),
        label: o.label || '',
        confirmText: o.confirmText || o.confirmLabel || t('common.confirm'),
        cancelText: o.cancelText || o.cancelLabel || t('common.cancel'),
      }));
    };
    c.__hosted = true; p.__hosted = true;
    window.__confirm = c;
    window.__prompt = p;
    return () => {
      if (window.__confirm === c) window.__confirm = prevConfirm;
      if (window.__prompt === p) window.__prompt = prevPrompt;
    };
  }, [t]);

  useEffect(() => {
    if (dlg && dlg.type === 'prompt') {
      const id = setTimeout(() => { try { inputRef.current?.focus(); inputRef.current?.select?.(); } catch (_) {} }, 60);
      return () => clearTimeout(id);
    }
  }, [dlg]);

  const close = useCallback((val) => {
    setDlg((d) => { if (d) { try { d.resolve(val); } catch (_) {} } return null; });
  }, []);

  if (!dlg) return null;

  if (dlg.type === 'confirm') {
    return (
      <ConfirmDialog
        open
        portal
        title={dlg.title}
        body={dlg.message}
        danger={dlg.danger}
        confirmLabel={dlg.confirmText}
        cancelLabel={dlg.cancelText}
        onClose={() => close(false)}
        onConfirm={() => close(true)}
      />
    );
  }

  // prompt
  return (
    <Modal
      open
      title={dlg.title}
      width={440}
      onClose={() => close(null)}
      footer={(
        <div className="pl-modal-actions" style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn ghost" onClick={() => close(null)}>{dlg.cancelText}</button>
          <button className="btn" onClick={() => close(value || '')}>{dlg.confirmText}</button>
        </div>
      )}
    >
      <div className="pl-modal-form" style={{ padding: '4px 0' }}>
        {dlg.label && <label className="pl-field-label" style={{ display: 'block', marginBottom: 6 }}>{dlg.label}</label>}
        <input
          ref={inputRef}
          className="pl-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') close(value || ''); else if (e.key === 'Escape') close(null); }}
          style={{ width: '100%', boxSizing: 'border-box' }}
        />
      </div>
    </Modal>
  );
}
