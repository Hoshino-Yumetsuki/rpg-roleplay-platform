import React from 'react';
import { getCaps } from './catalog-helpers.js';

/**
 * ModelPicker — Wave 11-D (Phase 0 revision)
 *
 * props:
 *   value    : string                              当前 model real_name
 *   onChange : (real_name: string, api_id: string) => void
 *   filter?  : { capability?: string, kind?: "chat"|"embedding" }
 *
 * 拉 GET /api/models（window.api.models.list()），5 分钟内存缓存。
 * 按 api_id 分组（后端 canonical：vertex_ai / openai / anthropic 等）。
 * 顶部 capability filter chip，弃用 model 划线警告，
 * pricing + context window + source 标注。
 * 选中态 cyan border，搜索框 fuzzy。
 */

// ── 5 分钟内存缓存 ─────────────────────────────────────────────────────────────
// 缓存后端 /api/models 完整响应（含 apis 嵌套结构 + selected）
/** @type {{ resp: object | null, ts: number }} */
const _cache = { resp: null, ts: 0 };
const CACHE_TTL_MS = 5 * 60 * 1000;

/**
 * 拉 GET /api/models，返回完整响应对象。
 * 形状：{ok, models:{apis:[{id, display_name, kind, enabled, models:[...]}]}, selected:{...}}
 */
async function fetchCatalog() {
  const now = Date.now();
  if (_cache.resp && now - _cache.ts < CACHE_TTL_MS) return _cache.resp;
  try {
    // 用 window.api.models.list()（指向 GET /api/models）；无 window.api 时直连
    const res = await (window.api && window.api.models && window.api.models.list
      ? window.api.models.list()
      : fetch("/api/models", { credentials: "include" }).then((r) => r.json()));
    _cache.resp = res || {};
    _cache.ts = now;
    return _cache.resp;
  } catch (_) {
    return _cache.resp || {};
  }
}

/**
 * 从完整响应中提取扁平化的 [{apiId, apiLabel, model}] 列表，
 * model 形如 {id, real_name, display_name, enabled, capabilities}。
 */
function extractEntries(resp) {
  const apis = (resp && resp.models && Array.isArray(resp.models.apis))
    ? resp.models.apis
    : (Array.isArray(resp && resp.apis) ? resp.apis : []);
  const entries = [];
  for (const api of apis) {
    const apiId = api.id || api.api_id || '';
    const apiLabel = api.display_name || api.name || apiId;
    const models = Array.isArray(api.models) ? api.models : [];
    for (const m of models) {
      entries.push({ apiId, apiLabel, model: m });
    }
  }
  return entries;
}

// ── Provider 正规化：后端 canonical → 显示名 ────────────────────────────────
// canonical id 来自后端（小写，如 vertex_ai / openai / anthropic）
// 直接用 api.id（后端给什么用什么），这里只定义显示名映射。
const PROVIDER_LABELS = {
  vertex_ai:    "Vertex AI",
  openai:       "OpenAI",
  anthropic:    "Anthropic",
  deepseek:     "DeepSeek",
  dashscope:    "Qwen (DashScope)",
  doubao:       "豆包 (Doubao)",
  hunyuan:      "混元 (Hunyuan)",
  minimax:      "MiniMax",
  siliconflow:  "SiliconFlow",
  openrouter:   "OpenRouter",
  xiaomi_mimo:  "MiMo",
};

// 固定分组顺序（后端 canonical api id）
const PROVIDER_ORDER = [
  "anthropic",
  "openai",
  "vertex_ai",
  "deepseek",
  "dashscope",
  "doubao",
  "hunyuan",
  "minimax",
  "siliconflow",
  "openrouter",
  "xiaomi_mimo",
];

// ── Capability filter chip 定义 ───────────────────────────────────────────────
const CAP_CHIPS = [
  { key: "streaming",        label: "流式" },
  { key: "tools",            label: "工具" },
  { key: "vision",           label: "视觉" },
  { key: "extended_thinking",label: "深度思考" },
  { key: "function_calling", label: "函数调用" },
  { key: "web_search",       label: "联网搜索" },
];

// ── Source icon ───────────────────────────────────────────────────────────────
function sourceIcon(source) {
  if (source === "LiveApi")        return "🟢";
  if (source === "OpenRouterProxy")return "🔀";
  return "📋";
}
function sourceTitle(source) {
  if (source === "LiveApi")        return "Live API";
  if (source === "OpenRouterProxy")return "OpenRouter Proxy";
  return "Static Catalog";
}

// ── Context window 大标签 ─────────────────────────────────────────────────────
function ctxLabel(tokens) {
  if (!tokens) return null;
  if (tokens >= 900000)  return "1M";
  if (tokens >= 150000)  return "200K";
  if (tokens >= 100000)  return "128K";
  if (tokens >= 50000)   return "64K";
  if (tokens >= 30000)   return "32K";
  return (tokens / 1000).toFixed(0) + "K";
}

// ── Pricing ───────────────────────────────────────────────────────────────────
function fmtPrice(v) {
  if (v === null || v === undefined) return "—";
  return "$" + (Number(v)).toFixed(2);
}

// ── fuzzy match ───────────────────────────────────────────────────────────────
function fuzzyMatch(text, query) {
  if (!query) return true;
  const t = text.toLowerCase();
  const q = query.toLowerCase();
  let ti = 0;
  for (let qi = 0; qi < q.length; qi++) {
    ti = t.indexOf(q[qi], ti);
    if (ti === -1) return false;
    ti++;
  }
  return true;
}

// ── 注入样式(只注一次) ────────────────────────────────────────────────────────
const MP_STYLE_ID = "mp-styles-v1";
if (typeof document !== "undefined" && !document.getElementById(MP_STYLE_ID)) {
  const css = `
/* ModelPicker — Wave 11-D */
.mp-wrap{
  display:flex;flex-direction:column;gap:0;
  background:var(--panel,#211f1d);
  border:1px solid var(--line,#36322d);
  border-radius:var(--r-3,8px);
  overflow:hidden;
  font-family:var(--font-sans,system-ui);
  font-size:13px;
  color:var(--text,#ebe7df);
}
/* 搜索框 */
.mp-search-bar{
  display:flex;align-items:center;gap:6px;
  padding:8px 10px;
  border-bottom:1px solid var(--line-soft,#2a2724);
  background:var(--bg-deep,#131211);
}
.mp-search-bar svg{flex-shrink:0;color:var(--muted-2,#6b655e)}
.mp-search-bar input{
  flex:1;min-width:0;border:0;background:transparent;
  color:var(--text,#ebe7df);font-size:12.5px;outline:none;padding:0;
  font-family:inherit;
}
.mp-search-bar input::placeholder{color:var(--muted-2,#6b655e)}
/* capability filter 行 */
.mp-cap-row{
  display:flex;align-items:center;gap:4px;flex-wrap:wrap;
  padding:6px 10px 4px;
  border-bottom:1px solid var(--line-soft,#2a2724);
  background:var(--bg-deep,#131211);
}
.mp-chip{
  display:inline-flex;align-items:center;
  padding:2px 9px;
  font-size:11px;
  border:1px solid var(--line,#36322d);
  border-radius:999px;
  background:var(--panel-2,#282623);
  color:var(--muted,#968f85);
  cursor:pointer;
  user-select:none;
  transition:border-color .12s,background .12s,color .12s;
  white-space:nowrap;
}
.mp-chip:hover{color:var(--text,#ebe7df);border-color:var(--line-strong,#4a4540)}
.mp-chip.mp-chip-on{
  color:var(--info,#7aa6c2);
  border-color:rgba(122,166,194,.45);
  background:var(--info-soft,rgba(122,166,194,.12));
}
/* 列表滚动区 */
.mp-list{
  flex:1;overflow-y:auto;max-height:420px;
  padding:4px 0;
}
.mp-list::-webkit-scrollbar{width:5px}
.mp-list::-webkit-scrollbar-thumb{background:var(--line,#36322d);border-radius:3px}
/* Provider 分组头 */
.mp-group-head{
  font-size:10.5px;
  text-transform:uppercase;
  letter-spacing:.12em;
  color:var(--muted-2,#6b655e);
  padding:8px 12px 4px;
  display:flex;align-items:center;gap:6px;
}
/* 单个 model 行 */
.mp-model-row{
  display:grid;
  grid-template-columns:minmax(0,1fr) auto auto;
  gap:8px;
  align-items:start;
  padding:7px 12px;
  cursor:pointer;
  border:1px solid transparent;
  border-radius:0;
  transition:background .1s,border-color .1s;
  position:relative;
}
.mp-model-row:hover{background:var(--panel-2,#282623)}
.mp-model-row.mp-selected{
  background:var(--info-soft,rgba(122,166,194,.12));
  border-color:rgba(122,166,194,.45);
  border-radius:var(--r-2,6px);
}
/* 弃用 model */
.mp-model-row.mp-deprecated .mp-model-name{
  text-decoration:line-through;
  color:var(--muted,#968f85);
}
/* model 名称区 */
.mp-model-cell{display:flex;flex-direction:column;gap:2px;min-width:0}
.mp-model-name{
  font-family:var(--font-serif,serif);
  font-size:13.5px;
  letter-spacing:.02em;
  color:var(--text,#ebe7df);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.mp-model-id{
  font-family:var(--font-mono,monospace);
  font-size:10.5px;
  color:var(--muted,#968f85);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.mp-deprecated-tag{
  display:inline-flex;align-items:center;gap:3px;
  font-size:10px;
  color:var(--danger,#c8675d);
  background:var(--danger-soft,rgba(200,103,93,.12));
  border:1px solid rgba(200,103,93,.28);
  border-radius:4px;
  padding:1px 5px;
  margin-top:2px;
  align-self:flex-start;
  font-family:var(--font-mono,monospace);
}
/* 价格列 */
.mp-price-cell{
  text-align:right;
  display:flex;flex-direction:column;gap:1px;
  font-size:10.5px;
  color:var(--muted,#968f85);
  font-family:var(--font-mono,monospace);
  white-space:nowrap;
  flex-shrink:0;
}
.mp-price-cell span{display:block}
/* 右下角: ctx + source */
.mp-meta-cell{
  display:flex;flex-direction:column;align-items:flex-end;gap:3px;
  flex-shrink:0;
}
.mp-ctx-badge{
  font-size:10px;
  color:var(--muted-2,#6b655e);
  background:var(--panel-3,#2f2c28);
  border:1px solid var(--line-soft,#2a2724);
  border-radius:3px;
  padding:1px 5px;
  font-family:var(--font-mono,monospace);
  white-space:nowrap;
}
.mp-source-icon{font-size:11px;cursor:default;line-height:1}
/* 空状态 */
.mp-empty{
  padding:28px 14px;
  text-align:center;
  color:var(--muted,#968f85);
  font-size:12.5px;
}
/* 加载 */
.mp-loading{
  padding:20px 14px;
  text-align:center;
  color:var(--muted-2,#6b655e);
  font-size:12px;
}
`;
  const el = document.createElement("style");
  el.id = MP_STYLE_ID;
  el.textContent = css;
  document.head.appendChild(el);
}

// ── Main component ────────────────────────────────────────────────────────────
/**
 * @param {{
 *   value: string,
 *   onChange: (real_name: string, api_id: string) => void,
 *   filter?: { capability?: string, kind?: "chat"|"embedding" }
 * }} props
 *
 * value / onChange 均使用 real_name（后端 model_entries.real_name），
 * 即 m.real_name || m.id（两者在后端等价）。
 */
function ModelPicker({ value, onChange, filter }) {
  const { useState, useEffect, useMemo } = React;

  // entries: [{apiId, apiLabel, model}]
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [capFilter, setCapFilter] = useState(
    (filter && filter.capability) ? filter.capability : null
  );

  // 首次加载 catalog
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchCatalog().then((resp) => {
      if (!alive) return;
      setEntries(extractEntries(resp));
      setLoading(false);
    });
    return () => { alive = false; };
  }, []);

  // 应用 filter prop 的 capability + kind
  const baseFiltered = useMemo(() => {
    let list = entries;
    if (filter && filter.kind === "embedding") {
      list = list.filter(({ model: m }) => getCaps(m).includes("embedding"));
    } else if (filter && filter.kind === "chat") {
      list = list.filter(({ model: m }) => !getCaps(m).includes("embedding"));
    }
    return list;
  }, [entries, filter]);

  // 应用 capability chip + 搜索
  const displayed = useMemo(() => {
    let list = baseFiltered;
    if (capFilter) {
      list = list.filter(({ model: m }) => getCaps(m).includes(capFilter));
    }
    if (search.trim()) {
      const q = search.trim();
      list = list.filter(({ model: m }) =>
        fuzzyMatch(m.real_name || m.id || "", q) ||
        fuzzyMatch(m.id || "", q) ||
        fuzzyMatch(m.display_name || "", q)
      );
    }
    return list;
  }, [baseFiltered, capFilter, search]);

  // 按 api_id 分组（后端 canonical id，小写）
  const grouped = useMemo(() => {
    const map = {};
    const labelMap = {};
    for (const { apiId, apiLabel, model } of displayed) {
      const key = apiId || "unknown";
      if (!map[key]) { map[key] = []; labelMap[key] = apiLabel; }
      map[key].push(model);
    }
    // 按固定顺序排列，再追加未知 provider
    const result = [];
    for (const p of PROVIDER_ORDER) {
      if (map[p] && map[p].length > 0) result.push({ apiId: p, label: labelMap[p], models: map[p] });
    }
    for (const p of Object.keys(map)) {
      if (!PROVIDER_ORDER.includes(p) && map[p].length > 0) result.push({ apiId: p, label: labelMap[p], models: map[p] });
    }
    return result;
  }, [displayed]);

  const toggleCap = (key) => {
    setCapFilter((prev) => (prev === key ? null : key));
  };

  return (
    <div className="mp-wrap">
      {/* 搜索框 */}
      <div className="mp-search-bar">
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
          <circle cx="6.5" cy="6.5" r="5" stroke="currentColor" strokeWidth="1.5"/>
          <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
        <input
          type="text"
          placeholder="搜索模型 id 或名称…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button
            style={{ background: "transparent", border: 0, color: "var(--muted-2)", cursor: "pointer", padding: "2px 4px", lineHeight: 1 }}
            onClick={() => setSearch("")}
            title="清除"
          >✕</button>
        )}
      </div>

      {/* Capability filter chips */}
      <div className="mp-cap-row">
        {CAP_CHIPS.map((c) => (
          <span
            key={c.key}
            className={"mp-chip" + (capFilter === c.key ? " mp-chip-on" : "")}
            onClick={() => toggleCap(c.key)}
            title={capFilter === c.key ? "取消筛选" : `只看支持「${c.label}」的模型`}
          >
            {c.label}
          </span>
        ))}
        {capFilter && (
          <span
            className="mp-chip"
            style={{ borderStyle: "dashed", color: "var(--danger,#c8675d)" }}
            onClick={() => setCapFilter(null)}
            title="清除 capability 筛选"
          >✕ 清除</span>
        )}
      </div>

      {/* 模型列表 */}
      <div className="mp-list">
        {loading && <div className="mp-loading">加载模型目录…</div>}
        {!loading && grouped.length === 0 && (
          <div className="mp-empty">没有符合条件的模型</div>
        )}
        {!loading && grouped.map(({ apiId, label, models: grpModels }) => (
          <div key={apiId}>
            <div className="mp-group-head">
              {PROVIDER_LABELS[apiId] || label || apiId}
              <span style={{ color: "var(--muted-3,#4d4842)", fontWeight: "normal", textTransform: "none", letterSpacing: 0 }}>
                {grpModels.length}
              </span>
            </div>
            {grpModels.map((m) => {
              // real_name is the stable identifier used in preferences & onChange
              const realName = m.real_name || m.id || "";
              const isSelected = realName === value || m.id === value;
              const isDeprecated = !!m.deprecated_at;
              return (
                <div
                  key={realName || m.id}
                  className={
                    "mp-model-row" +
                    (isSelected ? " mp-selected" : "") +
                    (isDeprecated ? " mp-deprecated" : "")
                  }
                  onClick={() => onChange && onChange(realName, apiId)}
                  title={isDeprecated && m.retiring_at
                    ? `已弃用。停服时间: ${m.retiring_at}`
                    : isDeprecated ? "已弃用"
                    : realName}
                >
                  {/* 名称 + real_name + deprecated 警告 */}
                  <div className="mp-model-cell">
                    <span className="mp-model-name">{m.display_name || realName}</span>
                    <span className="mp-model-id">{realName}</span>
                    {isDeprecated && (
                      <span className="mp-deprecated-tag">
                        弃用于 {m.deprecated_at}
                        {m.retiring_at && ` · 停服 ${m.retiring_at}`}
                      </span>
                    )}
                  </div>

                  {/* pricing */}
                  <div className="mp-price-cell">
                    <span title="input / 1M tokens">{fmtPrice(m.input_cost_per_million)}</span>
                    <span title="output / 1M tokens" style={{ color: "var(--muted-2,#6b655e)" }}>{fmtPrice(m.output_cost_per_million)}</span>
                  </div>

                  {/* ctx badge + source icon */}
                  <div className="mp-meta-cell">
                    {m.context_window && (
                      <span className="mp-ctx-badge" title={`Context: ${m.context_window.toLocaleString()} tokens`}>
                        {ctxLabel(m.context_window)}
                      </span>
                    )}
                    <span className="mp-source-icon" title={sourceTitle(m.source)}>
                      {sourceIcon(m.source)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

window.ModelPicker = ModelPicker;
export default ModelPicker;
