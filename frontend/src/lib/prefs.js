/* prefs — 统一 user_preferences 读取(语义统一 #24)
 *
 * 后端把模型参数等偏好存在 `settings.<key>` 命名空间下,但部分旧条目是裸 `<key>`。
 * 读取时要先看命名空间键、再看裸键、最后兜底默认值;数字字段还要 Number 兜底。
 * 此前 pages/settings.jsx(readScopedPref/readNumberPref)与 mobile/pages/MobileSettings.jsx
 * (readPref/readNumPref)各写一份等价实现 → 抽到此处单一来源。
 */

/**
 * 按命名空间回退读取偏好:`settings.<key>` 优先,其次裸 `<key>`,都没有则 fallback。
 * 用 hasOwnProperty 判定,故 false / 0 / "" 等 falsy 值能被正确读出(不被 fallback 吞)。
 * @param {Record<string, any> | null | undefined} prefs
 * @param {string} key
 * @param {any} fallback
 * @returns {any}
 */
export function readScopedPref(prefs, key, fallback) {
  if (prefs && Object.prototype.hasOwnProperty.call(prefs, `settings.${key}`)) return prefs[`settings.${key}`];
  if (prefs && Object.prototype.hasOwnProperty.call(prefs, key)) return prefs[key];
  return fallback;
}

/**
 * 数字偏好:走 readScopedPref 取值后 Number 化,非有限数则回退 fallback。
 * @param {Record<string, any> | null | undefined} prefs
 * @param {string} key
 * @param {number} fallback
 * @returns {number}
 */
export function readNumberPref(prefs, key, fallback) {
  const raw = readScopedPref(prefs, key, fallback);
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

if (typeof window !== "undefined") {
  window.readScopedPref = readScopedPref;
  window.readNumberPref = readNumberPref;
}
