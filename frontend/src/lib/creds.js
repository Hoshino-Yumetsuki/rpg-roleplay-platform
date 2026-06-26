/* creds — 统一「需要配置凭据」错误检测
 *
 * 后端在多处会返回 credentials_required / needs_credentials 信号,但 shape 不统一:
 *   - 响应对象:  { code: 'credentials_required' } | { error_key: 'credentials_required' }
 *                | { needs_credentials: true }
 *   - Error 对象: e.code / e.payload.{code,error_key,needs_credentials}
 *   - SSE 错误字符串: 'credentials_required' / 'needs_credentials' 混在 message 里
 *
 * 之前每个调用点各写一段内联条件,检测条件各有出入(MediaStudio 只检 needs_credentials/code,
 * scripts.jsx 多检 error_key,tavern.jsx 用 regex),新增信号容易漏。统一到此处。
 *
 * 以 ESM 导出 + window 挂载两种方式分发。
 */

/**
 * 判断一个值是否表示「需要配置凭据」。
 * 接受:响应对象 / Error 对象(含 .payload) / 字符串。
 * @param {any} v
 * @returns {boolean}
 */
export function isCredentialsError(v) {
  if (!v) return false;
  if (typeof v === "string") {
    return /credentials_required|needs_credentials/i.test(v);
  }
  if (typeof v === "object") {
    const payload = v.payload || {};
    if (
      v.code === "credentials_required"
      || v.error_key === "credentials_required"
      || v.needs_credentials === true
      || payload.code === "credentials_required"
      || payload.error_key === "credentials_required"
      || payload.needs_credentials === true
    ) {
      return true;
    }
    // 错误信息字符串里夹带信号(SSE / 抛错文案)
    const msg = v.message || v.detail || v.error
      || payload.detail || payload.error || "";
    if (msg && /credentials_required|needs_credentials/i.test(String(msg))) {
      return true;
    }
  }
  return false;
}

if (typeof window !== "undefined") {
  window.isCredentialsError = isCredentialsError;
}
