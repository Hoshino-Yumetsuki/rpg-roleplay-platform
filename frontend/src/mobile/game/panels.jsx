/* panels.jsx — 移动原生世界面板(P2)。
   对齐电脑端 game-panels.jsx 的 8 个 tab(状态/规则/记忆/世界书/人物/时间线/上下文/调试),
   读同一份真实 `state`,但 UI 是移动原生(不复用电脑端 RightPanel)。
   字段防御性读取;空态明确提示。调试 tab 仅 devmode。 */
import React from 'react';
import { Icon } from '../icons.jsx';

export const MOBILE_PANEL_TABS = [
  { id: 'status', label: '状态', icon: 'status' },
  { id: 'rules', label: '规则', icon: 'dice' },
  { id: 'memory', label: '记忆', icon: 'memory' },
  { id: 'worldbook', label: '世界书', icon: 'world' },
  { id: 'cards', label: '人物', icon: 'cards' },
  { id: 'timeline', label: '时间线', icon: 'timeline' },
  { id: 'context', label: '上下文', icon: 'gauge' },
  ...((typeof localStorage !== 'undefined' && localStorage.getItem('rpg_devmode') === '1')
    ? [{ id: 'debug', label: '调试', icon: 'braces' }] : []),
];

const Empty = ({ children }) => <div className="mp-empty">{children}</div>;
const Sec = ({ title, count, children }) => (
  <div className="mp-sec">
    {title && <div className="mp-sec-head"><span>{title}</span>{count != null && <span className="mono">{count}</span>}</div>}
    {children}
  </div>
);
const KV = ({ k, v }) => (v == null || v === '') ? null : (
  <div className="mp-kv"><span className="mp-k">{k}</span><span className="mp-v">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span></div>
);

function StatusPanel({ s }) {
  const p = s.player || {}; const w = s.world || {};
  const wl = s.worldline || {}; const vars = wl.variables || wl.vars || {};
  const varEntries = Object.entries(vars);
  return (
    <>
      <Sec title="角色">
        <KV k="姓名" v={p.name || p.display_name} />
        <KV k="身份" v={p.role} />
        <KV k="位置" v={p.current_location || p.location} />
        {p.background ? <div className="mp-para">{p.background}</div> : null}
        {!p.name && !p.role ? <Empty>尚未建立角色</Empty> : null}
      </Sec>
      <Sec title="世界">
        <KV k="时刻" v={w.time} />
        <KV k="天气" v={w.weather} />
        {Array.isArray(w.known_events) && w.known_events.length ? (
          <div className="mp-list">{w.known_events.slice(0, 8).map((e, i) => <div key={i} className="mp-li">· {typeof e === 'string' ? e : (e.text || e.title || JSON.stringify(e))}</div>)}</div>
        ) : null}
      </Sec>
      {varEntries.length > 0 && (
        <Sec title="世界线变量" count={varEntries.length}>
          {varEntries.slice(0, 20).map(([k, v]) => <KV key={k} k={k} v={v} />)}
        </Sec>
      )}
    </>
  );
}

function RulesPanel({ s }) {
  const rs = s.ruleset || {}; const sc = s.scene || {}; const enc = s.encounter || {};
  const pc = s.player_character || {}; const dice = Array.isArray(s.dice_log) ? s.dice_log : [];
  const hasRules = rs.id || rs.name || sc.module_id || enc.id || dice.length;
  if (!hasRules) return <Empty>当前玩法非规则模式(无 5E 兼容模组)。</Empty>;
  return (
    <>
      {(rs.id || rs.name) && <Sec title="规则集"><KV k="ruleset" v={rs.name || rs.id} /></Sec>}
      {pc && (pc.hp != null || pc.level != null) && (
        <Sec title="角色卡(PC)">
          <KV k="等级" v={pc.level} /><KV k="HP" v={pc.hp != null ? `${pc.hp}/${pc.max_hp ?? '?'}` : null} />
          <KV k="AC" v={pc.ac} />
        </Sec>
      )}
      {sc.module_id && <Sec title="场景"><KV k="模组" v={sc.module_id} /><KV k="位置" v={sc.location} /></Sec>}
      {enc.id && <Sec title="遭遇"><KV k="encounter" v={enc.id} /><KV k="回合" v={enc.round} /></Sec>}
      {dice.length > 0 && (
        <Sec title="掷骰记录" count={dice.length}>
          {dice.slice(-12).reverse().map((d, i) => <div key={i} className="mono mp-li">{typeof d === 'string' ? d : `${d.expr || ''} → ${d.total ?? d.result ?? ''}`}</div>)}
        </Sec>
      )}
    </>
  );
}

function MemoryPanel({ s }) {
  const m = s.memory || {};
  const facts = Array.isArray(m.facts) ? m.facts : [];
  const updates = Array.isArray(m.last_structured_updates) ? m.last_structured_updates : [];
  return (
    <>
      <Sec title="记忆模式"><KV k="mode" v={m.mode || 'normal'} />{m.current_objective ? <KV k="当前目标" v={m.current_objective} /> : null}</Sec>
      <Sec title="固定记忆 / 事实" count={facts.length}>
        {facts.length ? facts.slice(0, 30).map((f, i) => <div key={i} className="mp-li">· {typeof f === 'string' ? f : (f.text || f.content || JSON.stringify(f))}</div>) : <Empty>暂无固定记忆</Empty>}
      </Sec>
      {updates.length > 0 && (
        <Sec title="本轮结构化更新" count={updates.length}>
          {updates.map((u, i) => <div key={i} className="mono mp-li">{typeof u === 'string' ? u : (u.field ? `${u.field}: ${u.value ?? ''}` : JSON.stringify(u))}</div>)}
        </Sec>
      )}
    </>
  );
}

function WorldbookPanel({ s }) {
  const wb = s.worldbook || s.world_book || (s.content_pack && s.content_pack.worldbook) || [];
  const entries = Array.isArray(wb) ? wb : (wb.entries || []);
  if (!entries.length) return <Empty>本档暂无激活的世界书条目(检索时按需注入)。</Empty>;
  return (
    <Sec title="世界书" count={entries.length}>
      {entries.slice(0, 40).map((e, i) => (
        <div key={i} className="mp-card">
          <div className="mp-card-t">{e.key || e.title || e.name || ('条目 ' + i)}</div>
          {(e.content || e.text) ? <div className="mp-card-b">{String(e.content || e.text).slice(0, 200)}</div> : null}
        </div>
      ))}
    </Sec>
  );
}

function CardsPanel({ s }) {
  const onStage = Array.isArray(s.active_entities) ? s.active_entities : [];
  const rel = s.relationships || {};
  const relEntries = Object.entries(rel);
  return (
    <>
      <Sec title="在场" count={onStage.length}>
        {onStage.length ? onStage.map((c, i) => {
          const nm = c.name || c.id || ('实体' + i);
          return <div key={i} className="mp-row"><span className="mp-av serif">{String(nm).slice(0, 1)}</span><span className="mp-row-tx"><strong>{nm}</strong>{c.role || c.status ? <span>{c.role || c.status}</span> : null}</span></div>;
        }) : <Empty>当前无在场角色</Empty>}
      </Sec>
      <Sec title="关系" count={relEntries.length}>
        {relEntries.length ? relEntries.slice(0, 30).map(([name, r]) => (
          <div key={name} className="mp-kv"><span className="mp-k">{name}</span><span className="mp-v">{typeof r === 'object' ? (r.tone || r.status || r.value || JSON.stringify(r)) : String(r)}</span></div>
        )) : <Empty>暂无关系记录</Empty>}
      </Sec>
    </>
  );
}

function TimelinePanel({ s }) {
  const w = s.world || {};
  const tl = w.timeline || {};
  const items = Array.isArray(tl) ? tl : (Array.isArray(tl.events) ? tl.events : (Array.isArray(w.known_events) ? w.known_events : []));
  if (!items.length) return <Empty>暂无时间线事件。</Empty>;
  return (
    <Sec title="时间线" count={items.length}>
      {items.slice(0, 40).map((e, i) => (
        <div key={i} className="mp-tl"><span className="mp-tl-dot" /><div className="mp-tl-tx"><strong>{e.time || e.when || ''}</strong><span>{typeof e === 'string' ? e : (e.text || e.title || e.event || JSON.stringify(e))}</span></div></div>
      ))}
    </Sec>
  );
}

function ContextPanel({ s }) {
  const c = s.context || {};
  const segs = Array.isArray(c.segments) ? c.segments : [];
  if (!segs.length) return <Empty>本轮尚无上下文分项。底部「上下文」按钮可看本轮 token 用量。</Empty>;
  return (
    <Sec title="上下文分项" count={segs.length}>
      {segs.map((seg, i) => (
        <div key={i} className="mp-kv"><span className="mp-k">{seg.label}</span><span className="mp-v mono">{seg.tok} · {seg.pct}%</span></div>
      ))}
    </Sec>
  );
}

function DebugPanel({ s }) {
  return (
    <Sec title="原始 state(调试)">
      <pre className="mp-pre">{JSON.stringify(s, null, 2)}</pre>
    </Sec>
  );
}

const PANELS = {
  status: StatusPanel, rules: RulesPanel, memory: MemoryPanel, worldbook: WorldbookPanel,
  cards: CardsPanel, timeline: TimelinePanel, context: ContextPanel, debug: DebugPanel,
};

export function MobilePanel({ tab, state }) {
  const P = PANELS[tab] || StatusPanel;
  return <div className="mp-root">{<P s={state || {}} />}</div>;
}

export default MobilePanel;
