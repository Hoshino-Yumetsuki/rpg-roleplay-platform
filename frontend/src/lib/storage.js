/* storage — 统一 localStorage 读写封装(语义统一 #39)
 *
 * 此前各处散落 `try { localStorage.getItem/setItem(...) } catch (_) {}`,
 * 每处各写一遍 try/catch + 默认值 + JSON 编解码,容易漏 catch 致隐私模式/
 * 配额满时抛错炸页面。统一到此处四个原语:
 *   - lsGet(key, fallback)     裸字符串读,缺失/异常 → fallback
 *   - lsSet(key, value)        裸写(调用方自行 String() 编码),异常吞掉
 *   - lsGetJSON(key, fallback) JSON.parse 读,缺失/解析失败 → fallback
 *   - lsSetJSON(key, value)    JSON.stringify 写,异常吞掉
 *   - lsRemove(key)            删除,异常吞掉
 *
 * 语义铁律(替换调用点时逐一对齐):
 *   - 默认值由调用方传入,保持各点原有兜底不变。
 *   - 布尔/枚举编码(如 '1'/'0'、'on'/'off')仍在调用点判断;本层只管字符串读写。
 *   - lsGet 返回 null(缺失)时与原 `getItem() || fallback` 行为一致 —— 故 fallback
 *     默认 null,调用点若用 `lsGet(k) || 'x'` 可继续工作。
 *
 * 以 ESM 导出 + window 挂载两种方式分发。
 */

/**
 * 读取裸字符串。键不存在或读取异常时返回 fallback。
 * 注意:空串 "" 是有效存储值,会被原样返回(不回退 fallback)。
 * @param {string} key
 * @param {any} [fallback=null]
 * @returns {any}
 */
export function lsGet(key, fallback = null) {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : v;
  } catch (_) {
    return fallback;
  }
}

/**
 * 写入裸字符串。调用方负责把非字符串值 String() 编码。异常(隐私模式/配额满)吞掉。
 * @param {string} key
 * @param {string} value
 * @returns {void}
 */
export function lsSet(key, value) {
  try { localStorage.setItem(key, value); } catch (_) {}
}

/**
 * 读取并 JSON.parse。键不存在或解析失败时返回 fallback。
 * @param {string} key
 * @param {any} [fallback=null]
 * @returns {any}
 */
export function lsGetJSON(key, fallback = null) {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    const parsed = JSON.parse(raw);
    return parsed === null ? fallback : parsed;
  } catch (_) {
    return fallback;
  }
}

/**
 * JSON.stringify 后写入。异常吞掉。
 * @param {string} key
 * @param {any} value
 * @returns {void}
 */
export function lsSetJSON(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {}
}

/**
 * 删除键。异常吞掉。
 * @param {string} key
 * @returns {void}
 */
export function lsRemove(key) {
  try { localStorage.removeItem(key); } catch (_) {}
}

if (typeof window !== "undefined") {
  window.lsGet = lsGet;
  window.lsSet = lsSet;
  window.lsGetJSON = lsGetJSON;
  window.lsSetJSON = lsSetJSON;
  window.lsRemove = lsRemove;
}
