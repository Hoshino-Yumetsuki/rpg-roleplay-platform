/* mobile/Field.jsx — 移动端通用表单行(语义统一 #36)
 *
 * 把分散在各移动页的「label + desc + 控件」竖排字段、以及「label + desc + 开关」
 * 切换行收口成两个组件:
 *   <Field>      竖排字段:label + 可选 desc + 任意 children 作为控件(.pl-field class)
 *   <ToggleRow>  开关行:label + 可选 desc + 右侧 .pl-toggle 开关(.pl-setrow class)
 *
 * 视觉/行为以 mobile.css 既有 class 为准(.pl-field/.pl-field>label/.pl-field .desc 与
 * .pl-setrow/.pl-setrow-tx/.pl-toggle),零新 CSS、零视觉改动。
 *
 * 收口铁律(语义统一,行为零变化):
 *   - 只收 DOM/CSS 与本组件**逐字节一致**的 class-based 站点
 *     (= MobileSettings.MField 竖排字段、MobileCards.SetRow 开关行)。
 *   - **信息行 ≠ 开关行**:label+desc+右侧控件的「信息行」(MobileSettings.SetRow /
 *     MobileMe.SetRow)与本文件的竖排 Field、开关 ToggleRow 都不同,不强并。
 *   - 纯 inline-style 写的变体(MobileCaps.MField 用 11px/line-height1.5 的内联 span、
 *     MobileMe.SetRow 的 inline + danger 变体、MobileNewGame.FieldLabel 纯标签块、
 *     MobileCards.Field 内置 input 控件)若强迁会改 px/行高/结构 = 可见变化,
 *     按铁律保留原样,不在此收口。
 */
import React from 'react';

/* ── 竖排字段 ────────────────────────────────────────────────────────
 * label    字段名(.pl-field > label)
 * desc     可选说明(.pl-field .desc 小字)
 * children 控件(input / select / slider 等)
 */
export function Field({ label, desc, children }) {
  return (
    <div className="pl-field">
      <label>{label}</label>
      {desc && <span className="desc">{desc}</span>}
      {children}
    </div>
  );
}

/* ── 开关行 ──────────────────────────────────────────────────────────
 * label    行名(.pl-setrow-tx strong)
 * desc     可选说明(.pl-setrow-tx span 小字)
 * checked  开关状态
 * onChange (next:boolean) => void —— 点击切换时回传取反后的值
 */
export function ToggleRow({ label, desc, checked, onChange }) {
  return (
    <div className="pl-setrow">
      <div className="pl-setrow-tx">
        <strong>{label}</strong>
        {desc && <span>{desc}</span>}
      </div>
      <button
        className={'pl-toggle' + (checked ? ' on' : '')}
        onClick={() => onChange(!checked)}
        aria-label={label}
      />
    </div>
  );
}

export default Field;
