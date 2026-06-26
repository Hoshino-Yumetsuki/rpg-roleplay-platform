/* chrome.jsx — 移动端共享外壳件:页头 / 信息提示 popover / 栈层。
   纯表现层,从设计稿(平台外壳)抬取并转 ESM。 */
import React from 'react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Icon } from './icons.jsx';

/* 复用页头:返回箭头 + 标题/副标题 + 右侧操作 */
export function PageHeader({ title, sub, onBack, actions, center }) {
  const { t } = useTranslation();
  return (
    <div className="pl-head">
      {onBack && (
        <button className="pl-back" onClick={onBack} aria-label={t('common.back')}>
          <Icon name="chevron_left" size={20} />
        </button>
      )}
      <div className={'pl-head-title' + (center ? ' center' : '')}>
        <strong>{title}</strong>
        {sub && <span className="sub">{sub}</span>}
      </div>
      {actions && <div className="pl-head-actions">{actions}</div>}
    </div>
  );
}

/* ⓘ 信息提示:把长描述折进按需弹出的 popover */
export function InfoHint({ text }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <span className="ih-wrap">
      <button
        type="button"
        className="ih-btn"
        aria-label={t('common.info_hint')}
        aria-expanded={open}
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen((o) => !o); }}
      >
        <Icon name="info" size={13} />
      </button>
      {open && (
        <>
          <span className="ih-scrim" onClick={(e) => { e.stopPropagation(); setOpen(false); }} />
          <span className="ih-pop" role="tooltip">{text}</span>
        </>
      )}
    </span>
  );
}

export function LabelWithHint({ label, hint }) {
  return <span className="label-with-hint">{label}{hint ? <InfoHint text={hint} /> : null}</span>;
}

/* 栈层:纯 CSS 动画,front/behind/pushed 由 MobileRoot 控制 */
export function Layer({ top, pushed, children }) {
  const cls = 'pl-layer ' + (top ? 'front' : 'behind') + (pushed ? ' pushed' : '');
  return <div className={cls}>{children}</div>;
}
