import React from 'react';
import { createPortal } from 'react-dom';

/* ImageLightbox — 统一的图片全屏预览 + 裁剪。
   · createPortal 到 document.body：彻底逃离任何祖先(如 .msplit__media 的 sticky)
     造成的层叠上下文,根治"文字浮在预览图之上"的 z-index bug。
   · view 模式：contain 大图 + 工具条(裁剪 / 关闭)。
   · crop 模式：canvas 裁剪框(整框拖动 + 8 个 handle 缩放,box-shadow 暗化框外),
     「应用」→ 把裁剪区域画进 canvas → toBlob → onCrop(blob)。

   props:
     open       : 是否显示
     src        : 图片 URL
     alt        : 替代文本
     onClose()  : 关闭
     onCrop(blob) : 可选；提供则显示「裁剪」按钮,应用后回调裁剪结果 Blob(image/png)
     cropHint   : 裁剪态底部提示文案
*/
export default function ImageLightbox({ open, src, alt = '', onClose, onCrop, cropHint }) {
  const { useState, useEffect, useRef, useCallback } = React;
  const [mode, setMode] = useState('view');     // 'view' | 'crop'
  const [busy, setBusy] = useState(false);
  const [box, setBox] = useState(null);          // 裁剪框(相对图片显示区的 px){x,y,w,h}
  const imgRef = useRef(null);
  const dragRef = useRef(null);                  // {type:'move'|handle, sx,sy, start:{...}, dims}

  // 打开时重置；Esc 关闭(crop 态先退回 view)
  useEffect(() => {
    if (!open) { setMode('view'); setBox(null); setBusy(false); return; }
    const h = (e) => {
      if (e.key !== 'Escape') return;
      if (mode === 'crop') { setMode('view'); setBox(null); }
      else onClose && onClose();
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [open, mode, onClose]);

  // 锁滚动(预览/裁剪期间)
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  const imgDims = useCallback(() => {
    const el = imgRef.current;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { left: r.left, top: r.top, w: r.width, h: r.height,
             natW: el.naturalWidth || r.width, natH: el.naturalHeight || r.height };
  }, []);

  // 进入裁剪：初始化为居中 78% 框
  const enterCrop = useCallback(() => {
    const d = imgDims();
    if (!d) return;
    const w = d.w * 0.78, h = d.h * 0.78;
    setBox({ x: (d.w - w) / 2, y: (d.h - h) / 2, w, h });
    setMode('crop');
  }, [imgDims]);

  // 拖动 / 缩放
  const onPointerDown = (type) => (e) => {
    e.preventDefault(); e.stopPropagation();
    const d = imgDims();
    if (!d || !box) return;
    dragRef.current = { type, sx: e.clientX, sy: e.clientY, start: { ...box }, dims: d };
    const move = (ev) => {
      const g = dragRef.current; if (!g) return;
      const dx = ev.clientX - g.sx, dy = ev.clientY - g.sy;
      const { w: IW, h: IH } = g.dims;
      let { x, y, w, h } = g.start;
      const MIN = 24;
      if (g.type === 'move') {
        x = Math.min(Math.max(0, x + dx), IW - w);
        y = Math.min(Math.max(0, y + dy), IH - h);
      } else {
        // handle: 含 n/s/e/w 任意组合
        const t = g.type;
        if (t.includes('e')) w = Math.min(Math.max(MIN, w + dx), IW - x);
        if (t.includes('s')) h = Math.min(Math.max(MIN, h + dy), IH - y);
        if (t.includes('w')) { const nx = Math.min(Math.max(0, x + dx), x + w - MIN); w += (x - nx); x = nx; }
        if (t.includes('n')) { const ny = Math.min(Math.max(0, y + dy), y + h - MIN); h += (y - ny); y = ny; }
      }
      setBox({ x, y, w, h });
    };
    const up = () => {
      dragRef.current = null;
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const applyCrop = useCallback(async () => {
    const d = imgDims();
    if (!d || !box || !onCrop) return;
    setBusy(true);
    try {
      const scaleX = d.natW / d.w, scaleY = d.natH / d.h;
      const sx = Math.round(box.x * scaleX), sy = Math.round(box.y * scaleY);
      const sw = Math.max(1, Math.round(box.w * scaleX)), sh = Math.max(1, Math.round(box.h * scaleY));
      const canvas = document.createElement('canvas');
      canvas.width = sw; canvas.height = sh;
      const ctx = canvas.getContext('2d');
      // 用一个 crossOrigin 的新 Image 确保能进 canvas(站内同源,安全)
      const img = imgRef.current;
      ctx.drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh);
      const blob = await new Promise((res) => canvas.toBlob(res, 'image/png', 0.95));
      if (blob) await onCrop(blob);
      setMode('view'); setBox(null);
    } catch (err) {
      try { window.__apiToast && window.__apiToast('裁剪失败', { kind: 'danger' }); } catch (_) {}
    } finally { setBusy(false); }
  }, [box, onCrop, imgDims]);

  if (!open) return null;

  const HANDLES = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];
  const node = (
    <div className="ilb" role="dialog" aria-modal="true" onClick={() => mode === 'view' && onClose && onClose()}>
      <div className="ilb__stage" onClick={(e) => e.stopPropagation()}>
        <div className="ilb__imgwrap">
          <img ref={imgRef} src={src} alt={alt} className="ilb__img" draggable="false" />
          {mode === 'crop' && box && (
            <div className="ilb-crop" style={{ left: box.x, top: box.y, width: box.w, height: box.h }}
              onPointerDown={onPointerDown('move')}>
              {HANDLES.map((hd) => (
                <span key={hd} className={`ilb-crop__h ilb-crop__h--${hd}`} data-h={hd}
                  onPointerDown={onPointerDown(hd)} />
              ))}
            </div>
          )}
        </div>

        <div className="ilb__bar">
          {mode === 'view' ? (
            <>
              {onCrop && <button className="ilb__btn" onClick={enterCrop}>✂ 裁剪</button>}
              <button className="ilb__btn ilb__btn--ghost" onClick={() => onClose && onClose()}>关闭</button>
            </>
          ) : (
            <>
              <span className="ilb__hint">{cropHint || '拖动调整裁剪区域，应用后保存'}</span>
              <button className="ilb__btn ilb__btn--ghost" disabled={busy} onClick={() => { setMode('view'); setBox(null); }}>取消</button>
              <button className="ilb__btn" disabled={busy} onClick={applyCrop}>{busy ? '处理中…' : '应用裁剪'}</button>
            </>
          )}
        </div>
      </div>
      <button className="ilb__close" aria-label="关闭" onClick={() => onClose && onClose()}>×</button>
    </div>
  );
  return createPortal(node, document.body);
}
