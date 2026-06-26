/* MobilePlaceholder — 尚未移植的 Tab 根页占位(P4-P7 逐步替换)。
   保持设计语言,给出"迁移中"说明,不留死路。 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import { Icon } from './icons.jsx';

export function Placeholder({ title, desc, icon = 'layers', phase }) {
  const { t } = useTranslation();
  return (
    <>
      <div className="pl-head">
        <div className="pl-head-title center"><strong>{title}</strong></div>
      </div>
      <div className="pl-body tabbed">
        <div className="pl-pad">
          <div className="pl-empty" style={{ padding: '64px 20px', textAlign: 'center' }}>
            <div style={{ width: 56, height: 56, borderRadius: 16, margin: '0 auto 16px', display: 'grid', placeItems: 'center', background: 'var(--panel-2)', color: 'var(--muted)' }}>
              <Icon name={icon} size={26} />
            </div>
            <div style={{ fontSize: 15, color: 'var(--text-quiet)', marginBottom: 6 }}>{t('m_placeholder.migrating')}</div>
            <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6, maxWidth: 280, margin: '0 auto' }}>{desc}</div>
            {phase && <div style={{ marginTop: 14, fontSize: 11, color: 'var(--muted-3)', fontFamily: 'var(--font-mono)' }}>{phase}</div>}
          </div>
        </div>
      </div>
    </>
  );
}
