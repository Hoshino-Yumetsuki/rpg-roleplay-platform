// ConfirmDialog —— 桌面确认弹窗,建在 Modal 之上(收敛此前各页手写的 ConfirmModal:
// platform-app 本地 ConfirmModal / tavern 导出的 ConfirmModal / game-app 删除确认 /
// settings 清空确认 的"纯 title+body+取消/确认"形态)。产出 DOM 与各自原手写
// pl-modal-backdrop > pl-modal > head/body/foot【完全一致】,迁移零视觉变化。
//
// ⚠️ 不是为了"统一"而抹平差异:各调用方原本的 eyebrow 文案 / 宽度 / 是否带图标 /
//    是否 createPortal / 行高 都做成 props,默认值对齐 platform-app 形态。
//    宁可多给一个 prop 保真,也不改任何站点的视觉。
//
// 命令式 API(window.__confirm,platform-app DialogHost)是另一条路径,与本声明式组件
// 并存——不互相取代。本组件供 JSX 内联确认弹窗用。
import React from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { Icon } from '../game-icons.jsx';
import Modal from './Modal.jsx';

export default function ConfirmDialog({
  open,
  title,
  body,
  // eyebrow:不传则按 danger 取默认("高危操作"/"确认");传字符串可覆盖(如 tavern 用"危险操作"/"请确认")
  eyebrow,
  danger = false,
  // dangerEyebrow=true:danger 态把 eyebrow 文字染红(platform-app / settings 风格)
  dangerEyebrow = false,
  confirmLabel,
  cancelLabel,
  // icons:确认/取消钮是否带 trash/check 图标(platform-app=true;tavern=false)
  icons = false,
  busy = false,
  width = 440,
  // bodyLineHeight:正文行高(platform-app=1.65;tavern/game=1.7)
  bodyLineHeight = 1.65,
  // portal:是否 createPortal 到 document.body(tavern/game=true;platform/settings=false)
  portal = false,
  onClose,
  onConfirm,
}) {
  const { t } = useTranslation();
  if (!open) return null;
  const eb = eyebrow != null
    ? eyebrow
    : (danger ? '高危操作' : '确认');
  const ebStyle = dangerEyebrow
    ? { color: danger ? 'var(--danger)' : 'var(--muted-2)' }
    : undefined;
  const cLabel = confirmLabel != null ? confirmLabel : '确认';
  const xLabel = cancelLabel != null ? cancelLabel : '取消';

  const header = (
    <div>
      <div className="pl-modal-eyebrow" style={ebStyle}>{eb}</div>
      <h2 className="pl-modal-title">{title}</h2>
    </div>
  );

  const footer = (
    <>
      <span />
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="btn ghost" onClick={onClose} disabled={busy}>{xLabel}</button>
        <button className={`btn ${danger ? 'danger' : 'primary'}`} onClick={onConfirm} disabled={busy}>
          {icons && (danger ? <Icon name="trash" size={12} /> : <Icon name="check" size={12} />)}
          {icons ? ' ' : ''}{cLabel}
        </button>
      </div>
    </>
  );

  const node = (
    <Modal
      open
      header={header}
      width={width}
      closeDisabled={busy}
      onClose={onClose}
      footer={footer}
    >
      <div style={{ fontSize: 13.5, lineHeight: bodyLineHeight, color: 'var(--text-quiet)' }}>{body}</div>
    </Modal>
  );

  return portal ? createPortal(node, document.body) : node;
}
