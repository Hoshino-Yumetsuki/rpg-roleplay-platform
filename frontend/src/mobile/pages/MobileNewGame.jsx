/* MobileNewGame — 移动端新游戏向导(5 步)
   铁律:
   ① 只用 mobile.css 已有 class 或 .m-ng-* 前缀新 class + inline style。
   ② 逻辑数据复用 window.api.* / window.__createAndEnterSave。
   ③ 出身×身份联动约束严格对齐 saves.jsx ALLOWED_SOURCES 逻辑。
   ④ export function MobileNewGame({ nav, scriptId, onDone }) + export default。
   props:
     nav       — MobileRoot nav 对象(nav.pop / nav.toast 等)
     scriptId  — 传入时锁定剧本跳过步骤 1 的剧本选择
     onDone    — 可选:创建成功回调
*/

import React from 'react';
import { useState, useEffect, useCallback, useRef } from 'react';
import { Icon } from '../icons.jsx';

/* ================================================================
   常量 & 工具
   ================================================================ */

// 出身×身份来源约束(与 saves.jsx IdentityStep 保持完全一致)
const ALLOWED_SOURCES = {
  soul:   ['none', 'npc', 'ai', 'manual'],  // 灵魂穿越:占据原住民肉身 → 全开
  body:   ['none'],                          // 整体穿越:彻底外来者无本地身份 → 仅「不挂」
  dual:   ['npc', 'ai', 'manual'],           // 双魂同体:须有本地本体 → 不能不挂
  native: ['none', 'ai', 'manual'],          // 本世界人:你就是该角色 → 不能再选另一个原著人物
};

const ORIGIN_OPTIONS = [
  {
    value: 'soul', icon: '◈', label: '灵魂穿越',
    essence: '意识独立 · 占据异世界躯体',
    mapping: '你的灵魂穿越到某个原住民的肉身中',
    hint: '可以选择挂靠任何一个本地身份',
    accentColor: '#8db4e8', accentBg: 'rgba(85,130,200,.14)', accentBorder: 'rgba(85,130,200,.38)',
  },
  {
    value: 'body', icon: '◉', label: '整体穿越',
    essence: '肉体完整 · 以异乡者姿态闯入',
    mapping: '你整个人连同外貌一起穿越到这个世界',
    hint: '你是彻底的外来者,无法挂靠本地身份',
    accentColor: '#e8a87c', accentBg: 'rgba(220,140,80,.14)', accentBorder: 'rgba(220,140,80,.38)',
  },
  {
    value: 'dual', icon: '◑', label: '双魂同体',
    essence: '两魂共生 · 共享同一具肉体',
    mapping: '你与某个原住民灵魂同时存在于同一躯体',
    hint: '必须选一个共体的本地身份',
    accentColor: '#b8a0e8', accentBg: 'rgba(160,130,210,.14)', accentBorder: 'rgba(160,130,210,.38)',
  },
  {
    value: 'native', icon: '◎', label: '本世界人',
    essence: '原住民 · 从未离开这个世界',
    mapping: '你就是这个世界的原住民角色',
    hint: '不能再选另一个原著角色作为「失忆身份」',
    accentColor: '#b8b0a5', accentBg: 'rgba(150,143,133,.14)', accentBorder: 'rgba(150,143,133,.32)',
  },
];

const SOURCE_LABELS = {
  none:   '不挂身份',
  npc:    '从原著角色',
  ai:     'AI 生成',
  manual: '手动填写',
};

const STEPS = [
  { n: 0, title: '剧本与出生点' },
  { n: 1, title: '角色卡' },
  { n: 2, title: '出身与身份' },
  { n: 3, title: '引导与防剧透' },
  { n: 4, title: '确认创建' },
];

const TOTAL_STEPS = STEPS.length;

const NEWGAME_ACTIVE_IMPORT_STATUSES = new Set(['queued', 'pending', 'running', 'processing', 'importing', 'started']);
const NEWGAME_IMPORT_TERMINAL_STATUSES = new Set(['done', 'done_with_errors', 'partial', 'failed', 'cancelled']);
const NEWGAME_BLOCKING_READINESS_KEYS = new Set(['chunks', 'anchors']);

function scriptBlockReason(script) {
  if (!script) return '';
  const status = String(
    script.import_status || script.job_status ||
    script.active_job?.status || script.readiness?.active_job?.status || ''
  ).trim().toLowerCase();
  if (status && NEWGAME_ACTIVE_IMPORT_STATUSES.has(status) && !NEWGAME_IMPORT_TERMINAL_STATUSES.has(status)) {
    return '剧本正在导入,请稍后';
  }
  const missing = Array.isArray(script.readiness?.missing) ? script.readiness.missing : [];
  const blocking = missing.filter(k => NEWGAME_BLOCKING_READINESS_KEYS.has(k));
  if (blocking.length > 0) return `剧本缺少: ${blocking.join('、')}`;
  if (Number(script.chapter_count || 0) <= 0) return '剧本章节尚未就绪';
  return '';
}

/* ================================================================
   Step 进度条
   ================================================================ */
function StepDots({ step, total }) {
  return (
    <div style={{ display: 'flex', gap: 5, alignItems: 'center', flex: 1 }}>
      {Array.from({ length: total }, (_, i) => (
        <div key={i} style={{
          height: 3, flex: 1, borderRadius: 99,
          background: i < step ? 'var(--accent)' : i === step ? 'rgba(201,100,66,.5)' : 'var(--line)',
          transition: 'background .2s',
        }} />
      ))}
      <span style={{ fontSize: 10, color: 'var(--muted-2)', whiteSpace: 'nowrap', marginLeft: 4, fontFamily: 'var(--font-mono)' }}>
        {step + 1}/{total}
      </span>
    </div>
  );
}

/* ================================================================
   错误条
   ================================================================ */
function ErrBar({ msg }) {
  if (!msg) return null;
  return (
    <div style={{
      color: 'var(--danger)', padding: '9px 12px',
      border: '1px solid rgba(200,103,93,.3)', borderRadius: 10,
      fontSize: 12.5, background: 'var(--danger-soft)', lineHeight: 1.5,
    }}>
      {msg}
    </div>
  );
}

/* ================================================================
   加载占位
   ================================================================ */
function Loading({ text }) {
  return (
    <div className="pl-empty" style={{ padding: '28px 20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, fontSize: 13, color: 'var(--muted)' }}>
        <Icon name="spinner" size={14} className="spin" /> {text || '加载中…'}
      </div>
    </div>
  );
}

/* ================================================================
   FieldLabel
   ================================================================ */
function FieldLabel({ children, hint }) {
  return (
    <div style={{ marginBottom: 7 }}>
      <div style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--text-quiet)' }}>{children}</div>
      {hint && <div style={{ fontSize: 11.5, color: 'var(--muted-2)', marginTop: 2, lineHeight: 1.5 }}>{hint}</div>}
    </div>
  );
}

/* ================================================================
   STEP 0 — 剧本与出生点
   ================================================================ */
function StepScriptBirth({ scripts, lockedScriptId, scriptId, setScriptId, birthpoint, setBirthpoint }) {
  const [phases, setPhases] = useState([]);
  const [bpLoading, setBpLoading] = useState(false);
  const [bpErr, setBpErr] = useState('');
  const [openPhase, setOpenPhase] = useState(null);

  const fetchBp = useCallback(() => {
    if (!scriptId) { setPhases([]); return; }
    setBpLoading(true); setBpErr('');
    (async () => {
      try {
        const r = await window.api.scripts.birthpoints(parseInt(scriptId, 10));
        const data = r || {};
        if (Array.isArray(data.phases) && data.phases.length > 0) {
          setPhases(data.phases);
          setOpenPhase(prev => prev || (data.phases[0]?.phase_label ?? null));
        } else {
          setPhases([]);
        }
      } catch (_) {
        setBpErr('出生点加载失败,可继续跳过');
        setPhases([]);
      } finally {
        setBpLoading(false);
      }
    })();
  }, [scriptId]);

  useEffect(() => { fetchBp(); }, [fetchBp]);

  // 剧本切换时清空出生点
  const prevScriptRef = useRef(scriptId);
  useEffect(() => {
    if (prevScriptRef.current !== scriptId) {
      setBirthpoint(null);
      prevScriptRef.current = scriptId;
    }
  }, [scriptId, setBirthpoint]);

  const selScript = scripts.find(s => String(s.id) === String(scriptId)) || null;
  const blockReason = scriptBlockReason(selScript);

  return (
    <div style={{ display: 'grid', gap: 20 }}>
      {/* 剧本选择 */}
      {!lockedScriptId && (
        <div>
          <FieldLabel hint="选择你想进入的剧本世界">剧本</FieldLabel>
          {scripts.length === 0 ? (
            <div style={{ fontSize: 12.5, color: 'var(--muted)', padding: '10px 0' }}>
              暂无可用剧本,请先在剧本页面导入
            </div>
          ) : (
            <div style={{ display: 'grid', gap: 7 }}>
              {scripts.map(sc => {
                const reason = scriptBlockReason(sc);
                const sel = String(sc.id) === String(scriptId);
                return (
                  <button
                    key={sc.id}
                    disabled={!!reason}
                    onClick={() => { setScriptId(String(sc.id)); setBirthpoint(null); }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 12, width: '100%',
                      padding: '12px 13px', border: sel ? '1px solid var(--accent-edge)' : '1px solid var(--line-soft)',
                      borderRadius: 12, background: sel ? 'var(--accent-soft)' : 'var(--panel)',
                      textAlign: 'left', transition: 'border-color .12s, background .12s',
                      opacity: reason ? 0.5 : 1, cursor: reason ? 'not-allowed' : 'pointer',
                    }}
                  >
                    <span style={{ width: 8, height: 8, borderRadius: 99, flexShrink: 0, background: sel ? 'var(--accent)' : 'var(--muted-3)' }} />
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ display: 'block', fontFamily: 'var(--font-serif)', fontSize: 14, color: sel ? 'var(--accent)' : 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sc.title}</span>
                      {reason && <span style={{ display: 'block', fontSize: 11, color: 'var(--warn)', marginTop: 2 }}>{reason}</span>}
                      {!reason && sc.chapter_count != null && <span style={{ display: 'block', fontSize: 10.5, color: 'var(--muted-2)', fontFamily: 'var(--font-mono)', marginTop: 2 }}>{sc.chapter_count} 章</span>}
                    </span>
                    {sel && <Icon name="check" size={14} style={{ color: 'var(--accent)', flexShrink: 0 }} />}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {lockedScriptId && selScript && (
        <div style={{ padding: '10px 13px', border: '1px solid var(--accent-edge)', borderRadius: 12, background: 'var(--accent-soft)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="book_open" size={16} style={{ color: 'var(--accent)', flexShrink: 0 }} />
          <span style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--accent)' }}>{selScript.title}</span>
        </div>
      )}

      {blockReason && (
        <div style={{ padding: '9px 12px', border: '1px solid rgba(212,179,102,.3)', borderRadius: 10, background: 'var(--warn-soft)', fontSize: 12.5, color: 'var(--warn)' }}>
          {blockReason}
        </div>
      )}

      {/* 出生点 */}
      {scriptId && !blockReason && (
        <div>
          <FieldLabel hint="选择从哪个剧情节点开始游戏(可选,默认从开头)">出生点</FieldLabel>
          <ErrBar msg={bpErr} />
          {bpLoading && <Loading text="加载出生点…" />}
          {!bpLoading && phases.length === 0 && !bpErr && (
            <div style={{ fontSize: 12, color: 'var(--muted)', padding: '8px 0' }}>
              该剧本暂无预设出生点,将从开头开始
              <button onClick={fetchBp} style={{ marginLeft: 8, fontSize: 12, color: 'var(--accent)' }}>重试</button>
            </div>
          )}
          {!bpLoading && phases.length > 0 && (
            <div style={{ display: 'grid', gap: 6 }}>
              {phases.map(phase => {
                const isOpen = openPhase === phase.phase_label;
                return (
                  <div key={phase.phase_label} style={{ border: '1px solid var(--line-soft)', borderRadius: 10, overflow: 'hidden' }}>
                    <button
                      onClick={() => setOpenPhase(isOpen ? null : phase.phase_label)}
                      style={{
                        width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center',
                        justifyContent: 'space-between', gap: 10, padding: '10px 13px',
                        background: isOpen ? 'var(--panel-2)' : 'transparent',
                        borderBottom: isOpen ? '1px solid var(--line-soft)' : 'none',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Icon name={isOpen ? 'chevron_down' : 'chevron_right'} size={11} style={{ color: 'var(--muted)', flexShrink: 0 }} />
                        <span style={{ fontFamily: 'var(--font-serif)', fontSize: 13.5 }}>{phase.phase_label}</span>
                      </div>
                      <span style={{ fontSize: 10.5, color: 'var(--muted-2)', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>
                        第 {phase.chapter_min}–{phase.chapter_max} 章
                      </span>
                    </button>
                    {isOpen && (
                      <div style={{ display: 'grid', gap: 4, padding: '8px 10px' }}>
                        {(phase.anchors || []).map(anchor => {
                          const isSel = birthpoint && birthpoint.anchor_id === anchor.anchor_id;
                          return (
                            <label key={anchor.anchor_id} style={{
                              display: 'grid', gridTemplateColumns: '16px 1fr auto', gap: 10,
                              padding: '10px 11px', borderRadius: 9, cursor: 'pointer',
                              border: isSel ? '1px solid var(--accent-edge)' : '1px solid var(--line-soft)',
                              background: isSel ? 'var(--accent-soft)' : 'var(--panel)',
                              alignItems: 'start', transition: 'border-color .12s, background .12s',
                            }}>
                              <input type="radio" checked={!!isSel} onChange={() => setBirthpoint({
                                phase_label: phase.phase_label,
                                anchor_id: anchor.anchor_id,
                                chapter_min: anchor.chapter_min,
                                chapter_max: anchor.chapter_max,
                                story_time_label: anchor.story_time_label,
                              })} style={{ marginTop: 2, accentColor: 'var(--accent)' }} />
                              <div>
                                <div style={{ fontFamily: 'var(--font-serif)', fontSize: 13, color: isSel ? 'var(--accent)' : 'var(--text)' }}>{anchor.story_time_label}</div>
                                {anchor.sample_summary && <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 2, lineHeight: 1.5 }}>{anchor.sample_summary}</div>}
                              </div>
                              <span style={{ fontSize: 10.5, color: 'var(--muted-2)', whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)' }}>
                                {anchor.chapter_max !== anchor.chapter_min ? `${anchor.chapter_min}–${anchor.chapter_max}` : `第 ${anchor.chapter_min} 章`}
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ================================================================
   STEP 1 — 角色卡
   ================================================================ */
function StepRole({ personas, userCards, roleMode, setRoleMode, pickedCard, setPickedCard, newCardName, setNewCardName, newCardRole, setNewCardRole, newCardBg, setNewCardBg }) {
  const allOpts = [
    ...personas.map(p => ({ key: `persona:${p.id || p.slug}`, kind: 'persona', name: p.name || '(未命名)', subtitle: p.role || '人格', id: p.id, slug: p.slug, pinned: !!p.is_default })),
    ...userCards.map(c => ({ key: `user:${c.id || c.slug}`, kind: 'user_card', name: c.name || '(未命名)', subtitle: c.identity || c.role || '角色卡', id: c.id, slug: c.slug, pinned: false })),
  ];

  return (
    <div style={{ display: 'grid', gap: 20 }}>
      {/* 模式切换 */}
      <div>
        <FieldLabel>角色来源</FieldLabel>
        <div className="pl-seg2" style={{ marginBottom: 16 }}>
          <button className={roleMode === 'existing' ? 'active' : ''} disabled={allOpts.length === 0} onClick={() => setRoleMode('existing')}>
            选择现有卡
          </button>
          <button className={roleMode === 'new' ? 'active' : ''} onClick={() => setRoleMode('new')}>
            新建角色
          </button>
        </div>
      </div>

      {/* 现有卡列表 */}
      {roleMode === 'existing' && (
        allOpts.length === 0 ? (
          <div style={{ fontSize: 12.5, color: 'var(--muted)', padding: '10px 0', lineHeight: 1.6 }}>
            暂无角色卡,请先在「角色卡」页面创建,或切换到「新建角色」
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 7 }}>
            {allOpts.map(opt => {
              const sel = pickedCard === opt.key;
              return (
                <button
                  key={opt.key}
                  onClick={() => setPickedCard(opt.key)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12, padding: '12px 13px',
                    border: sel ? '1px solid var(--accent-edge)' : '1px solid var(--line-soft)',
                    borderRadius: 12, background: sel ? 'var(--accent-soft)' : 'var(--panel)',
                    textAlign: 'left', transition: 'border-color .12s, background .12s', width: '100%',
                  }}
                >
                  <div style={{
                    width: 38, height: 38, borderRadius: 11, flexShrink: 0,
                    display: 'grid', placeItems: 'center',
                    background: sel ? 'var(--accent)' : 'var(--panel-3)',
                    border: '1px solid var(--line)',
                    fontFamily: 'var(--font-serif)', fontSize: 17,
                    color: sel ? '#fff8f3' : 'var(--text)',
                  }}>
                    {opt.name.slice(0, 1)}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                      <span style={{ fontSize: 14, fontWeight: 500, color: sel ? 'var(--accent)' : 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{opt.name}</span>
                      {opt.pinned && <span className="pill accent" style={{ fontSize: 10 }}>默认</span>}
                    </div>
                    <div style={{ fontSize: 11.5, color: 'var(--muted-2)', marginTop: 2 }}>
                      {opt.subtitle} · {opt.kind === 'persona' ? '人格' : '角色卡'}
                    </div>
                  </div>
                  {sel && <Icon name="check" size={15} style={{ color: 'var(--accent)', flexShrink: 0 }} />}
                </button>
              );
            })}
          </div>
        )
      )}

      {/* 新建角色 */}
      {roleMode === 'new' && (
        <div style={{ display: 'grid', gap: 14 }}>
          <div className="pl-field">
            <label>角色名称 <span style={{ color: 'var(--danger)' }}>*</span></label>
            <input
              className="pl-input"
              placeholder="在这个世界中的称谓"
              value={newCardName}
              onChange={e => setNewCardName(e.target.value)}
              autoComplete="off"
            />
          </div>
          <div className="pl-field">
            <label>身份定位</label>
            <input
              className="pl-input"
              placeholder="例:穿越者、宫廷谋士、流浪剑客"
              value={newCardRole}
              onChange={e => setNewCardRole(e.target.value)}
              autoComplete="off"
            />
          </div>
          <div className="pl-field">
            <label>背景经历</label>
            <textarea
              className="pl-input"
              placeholder="角色的来历、性格、目标…(可选)"
              value={newCardBg}
              onChange={e => setNewCardBg(e.target.value)}
              rows={3}
            />
          </div>
        </div>
      )}
    </div>
  );
}

/* ================================================================
   STEP 2 — 出身与身份
   ================================================================ */
function StepIdentity({ scriptId, birthpoint, pickedCard, allRoleOptions, playerOrigin, setPlayerOrigin, identity, setIdentity, identityKnown, setIdentityKnown }) {
  // 允许的身份来源
  const allowedSources = ALLOWED_SOURCES[playerOrigin] || ['none', 'npc', 'ai', 'manual'];

  // 当前选中的来源
  const srcOf = id => !id ? 'none' : (id._from === 'npc_card' ? 'npc' : id._from === 'ai' ? 'ai' : 'manual');
  const [idSrc, setIdSrc] = useState(() => srcOf(identity));

  // NPC 卡列表(当 idSrc === 'npc' 时加载)
  const [npcCards, setNpcCards] = useState([]);
  const [npcLoading, setNpcLoading] = useState(false);
  // AI 推荐
  const [recs, setRecs] = useState([]);
  const [recsLoading, setRecsLoading] = useState(false);
  const [recsErr, setRecsErr] = useState('');
  // 手动填写
  const [manualName, setManualName] = useState('');
  const [manualRole, setManualRole] = useState('');
  const [manualBg, setManualBg] = useState('');

  // 出身变化时校验来源兼容性
  useEffect(() => {
    const allowed = ALLOWED_SOURCES[playerOrigin] || ['none', 'npc', 'ai', 'manual'];
    if (!allowed.includes(idSrc)) {
      setIdSrc(allowed[0]);
      setIdentity(null);
    } else if (identity && identity.player_origin !== playerOrigin) {
      setIdentity({ ...identity, player_origin: playerOrigin });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playerOrigin]);

  // identity 从外部更新时同步 tab
  useEffect(() => {
    if (identity) setIdSrc(srcOf(identity));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity ? `${identity._from || ''}:${identity.npc_card_id || ''}:${identity.name || ''}` : null]);

  const allowedNow = ALLOWED_SOURCES[playerOrigin] || ['none', 'npc', 'ai', 'manual'];

  // 加载 NPC 卡
  useEffect(() => {
    if (idSrc !== 'npc' || !scriptId) { setNpcCards([]); return; }
    let alive = true;
    setNpcLoading(true);
    (async () => {
      try {
        const r = await window.api.cards.scriptList(parseInt(scriptId, 10));
        const list = (r && (r.items || r.cards)) || (Array.isArray(r) ? r : []);
        if (alive) setNpcCards(Array.isArray(list) ? list : []);
      } catch (_) { if (alive) setNpcCards([]); }
      if (alive) setNpcLoading(false);
    })();
    return () => { alive = false; };
  }, [idSrc, scriptId]);

  const pickRec = rec => setIdentity({ name: rec.name || '', role: rec.role || '', background: rec.background || '', source: 'ai', _from: 'ai', player_origin: playerOrigin });
  const pickNpc = card => {
    const nm = card.name || card.title || '';
    const role = card.identity || card.role || card.archetype || '';
    const bg = card.background || card.persona || card.summary || card.description || card.bio || '';
    setIdentity({ name: nm, role, background: bg, source: 'npc_card', _from: 'npc_card', npc_card_id: card.id || card.slug || null, player_origin: playerOrigin });
    setIdentityKnown(false);
  };
  const applyManual = () => {
    const role = manualRole.trim(); const bg = manualBg.trim();
    if (!role && !bg) return;
    setIdentity({ name: manualName.trim(), role, background: bg, source: 'custom', _from: 'custom', player_origin: playerOrigin });
  };
  const clearIdentity = () => {
    setIdentity(null);
    setIdSrc('none');
  };
  const chooseSource = sid => {
    setIdSrc(sid);
    if (sid === 'none') clearIdentity();
  };

  const fetchAiRecs = useCallback(async () => {
    if (!scriptId) return;
    setRecsLoading(true); setRecsErr(''); setRecs([]);
    const pickedRole = allRoleOptions ? allRoleOptions.find(o => o.key === pickedCard) : null;
    try {
      const r = await fetch(`${window.__API_BASE || ''}/api/scripts/${parseInt(scriptId, 10)}/recommend-identity`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          birthpoint_phase: birthpoint?.phase_label || '',
          birthpoint_label: birthpoint?.story_time_label || '',
          character_card_id: pickedRole ? (pickedRole.id || null) : null,
          character_card_kind: pickedRole ? pickedRole.kind : null,
          player_origin: playerOrigin,
          n: 4,
        }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok || data.ok === false) {
        setRecsErr((data && data.error) || `请求失败 (${r.status})`);
      } else if (data && Array.isArray(data.recommendations) && data.recommendations.length > 0) {
        setRecs(data.recommendations);
      } else {
        setRecsErr('暂无推荐,请重试或手动填写');
      }
    } catch (e) { setRecsErr(String(e?.message || e)); }
    setRecsLoading(false);
  }, [scriptId, birthpoint, pickedCard, allRoleOptions, playerOrigin]);

  return (
    <div style={{ display: 'grid', gap: 22 }}>

      {/* ── 出身来源 ── */}
      <div>
        <FieldLabel hint="你以何种方式进入这个世界">第一步:出身来源</FieldLabel>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          {ORIGIN_OPTIONS.map(orig => {
            const sel = playerOrigin === orig.value;
            return (
              <button
                key={orig.value}
                onClick={() => setPlayerOrigin(orig.value)}
                style={{
                  textAlign: 'left', padding: '11px 12px', borderRadius: 10, cursor: 'pointer',
                  border: sel ? `1px solid ${orig.accentBorder}` : '1px solid var(--line-soft)',
                  background: sel ? orig.accentBg : 'var(--panel)',
                  display: 'grid', gap: 5, transition: 'border-color .12s, background .12s',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <span style={{ fontSize: 17, lineHeight: 1, flexShrink: 0, color: sel ? orig.accentColor : 'var(--muted-2)', fontFamily: 'var(--font-serif)' }}>{orig.icon}</span>
                  <span style={{ fontFamily: 'var(--font-serif)', fontSize: 13.5, fontWeight: 700, color: sel ? orig.accentColor : 'var(--text)', lineHeight: 1.2 }}>{orig.label}</span>
                </div>
                <span style={{ fontSize: 11, fontWeight: 600, color: sel ? orig.accentColor : 'var(--muted)', lineHeight: 1.3 }}>{orig.essence}</span>
                <span style={{ fontSize: 10.5, color: 'var(--muted-2)', lineHeight: 1.5 }}>{orig.mapping}</span>
                {sel && <span style={{ fontSize: 10.5, color: 'var(--muted)', lineHeight: 1.5, borderTop: `1px solid ${orig.accentBorder}`, paddingTop: 5, marginTop: 2 }}>{orig.hint}</span>}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── 身份来源 ── */}
      <div>
        <FieldLabel hint="你在这个世界中的初始身份卡(可选)">第二步:身份来源</FieldLabel>

        {/* 来源选择器 */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          {[['none', '不挂身份'], ['npc', '从原著角色'], ['ai', 'AI 生成'], ['manual', '手动填写']].filter(([sid]) => allowedNow.includes(sid)).map(([sid, lbl]) => {
            const sel = idSrc === sid;
            return (
              <button
                key={sid}
                onClick={() => chooseSource(sid)}
                style={{
                  padding: '7px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                  border: sel ? '1px solid var(--accent-edge)' : '1px solid var(--line-soft)',
                  background: sel ? 'var(--accent-soft)' : 'var(--panel)',
                  color: sel ? 'var(--accent)' : 'var(--text)', transition: 'all .12s',
                }}
              >
                {lbl}
              </button>
            );
          })}
        </div>

        {/* 已选预览 */}
        {identity && (
          <div style={{
            display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10,
            padding: '11px 13px', border: '1px solid var(--accent-edge)', borderRadius: 11,
            background: 'var(--accent-soft)', marginBottom: 12,
          }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', alignItems: 'center', marginBottom: 3 }}>
                <span className="pill accent" style={{ fontSize: 10 }}>
                  {identity._from === 'ai' ? 'AI' : identity._from === 'npc_card' ? 'NPC' : '手动'}
                </span>
                {identity.name && <strong style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--text)' }}>{identity.name}</strong>}
                {identity.role && <span style={{ fontSize: 12.5, color: 'var(--text-quiet)' }}>{identity.role}</span>}
              </div>
              {identity.background && <div style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.6 }}>{identity.background}</div>}
            </div>
            <button onClick={() => chooseSource('none')} style={{ flexShrink: 0, fontSize: 12, color: 'var(--muted-2)', padding: '2px 6px' }}>清除</button>
          </div>
        )}

        {/* 从原著角色 */}
        {idSrc === 'npc' && (
          npcLoading ? <Loading text="加载角色卡…" /> :
          npcCards.length === 0 ? (
            <div style={{ fontSize: 12.5, color: 'var(--muted)', padding: '8px 0' }}>该剧本暂无原著角色卡</div>
          ) : (
            <div style={{ display: 'grid', gap: 6 }}>
              {npcCards.map((card, i) => {
                const cid = card.id || card.slug || i;
                const isSel = identity && identity._from === 'npc_card' && String(identity.npc_card_id) === String(card.id || card.slug);
                const nm = card.name || card.title || '';
                const role = card.identity || card.role || card.archetype || '';
                const bg = card.background || card.persona || card.summary || card.description || card.bio || '';
                return (
                  <button key={cid} onClick={() => pickNpc(card)} style={{
                    textAlign: 'left', padding: '11px 13px', borderRadius: 11,
                    border: isSel ? '1px solid var(--accent-edge)' : '1px solid var(--line-soft)',
                    background: isSel ? 'var(--accent-soft)' : 'var(--panel)',
                    display: 'grid', gap: 4, transition: 'border-color .12s, background .12s',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      {nm && <strong style={{ fontFamily: 'var(--font-serif)', fontSize: 14 }}>{nm}</strong>}
                      {role && <span className="pill" style={{ fontSize: 10.5 }}>{role}</span>}
                      {isSel && <span className="pill accent" style={{ fontSize: 10, marginLeft: 'auto' }}>✓ 已选</span>}
                    </div>
                    {bg && <span style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.55, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{bg}</span>}
                  </button>
                );
              })}
            </div>
          )
        )}

        {/* AI 生成 */}
        {idSrc === 'ai' && (
          <div style={{ display: 'grid', gap: 10 }}>
            <button className="pl-btn-ghost" onClick={fetchAiRecs} disabled={recsLoading} style={{ height: 40, fontSize: 13 }}>
              {recsLoading ? <><Icon name="spinner" size={13} className="spin" /> 生成中…</> : recs.length > 0 ? '重新生成' : 'AI 生成身份推荐'}
            </button>
            <ErrBar msg={recsErr} />
            {recs.length > 0 && (
              <div style={{ display: 'grid', gap: 6 }}>
                {recs.map((rec, i) => {
                  const isSel = identity && identity._from === 'ai' && identity.name === rec.name && identity.role === rec.role;
                  return (
                    <button key={i} onClick={() => pickRec(rec)} style={{
                      textAlign: 'left', padding: '11px 13px', borderRadius: 11,
                      border: isSel ? '1px solid var(--accent-edge)' : '1px solid var(--line-soft)',
                      background: isSel ? 'var(--accent-soft)' : 'var(--panel)',
                      display: 'grid', gap: 4, transition: 'border-color .12s, background .12s',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        {rec.name && <strong style={{ fontFamily: 'var(--font-serif)', fontSize: 14 }}>{rec.name}</strong>}
                        {rec.role && <span className="pill" style={{ fontSize: 10.5 }}>{rec.role}</span>}
                        {isSel && <span className="pill accent" style={{ fontSize: 10, marginLeft: 'auto' }}>✓ 已选</span>}
                      </div>
                      {rec.background && <span style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.55 }}>{rec.background}</span>}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* 手动填写 */}
        {idSrc === 'manual' && (
          <div style={{ display: 'grid', gap: 12 }}>
            <div className="pl-field" style={{ marginBottom: 0 }}>
              <label>别名</label>
              <input className="pl-input" placeholder="在这个世界中的名字(可选)" value={manualName} onChange={e => setManualName(e.target.value)} />
            </div>
            <div className="pl-field" style={{ marginBottom: 0 }}>
              <label>定位 <span style={{ color: 'var(--danger)' }}>*</span></label>
              <input className="pl-input" placeholder="例:皇帝的心腹、叛军头领" value={manualRole} onChange={e => setManualRole(e.target.value)} />
            </div>
            <div className="pl-field" style={{ marginBottom: 0 }}>
              <label>背景</label>
              <textarea className="pl-input" rows={3} placeholder="身份的来历与处境(可选)" value={manualBg} onChange={e => setManualBg(e.target.value)} />
            </div>
            <button className="pl-btn-primary" onClick={applyManual} disabled={!manualRole.trim() && !manualBg.trim()} style={{ height: 42, fontSize: 13 }}>
              <Icon name="check" size={14} /> 确认身份
            </button>
          </div>
        )}
      </div>

      {/* ── 是否知道这个身份 ── */}
      {identity && playerOrigin !== 'body' && (
        <div>
          <FieldLabel hint="开局时,你的角色是否知道自己拥有这个身份">第三步:是否知道身份</FieldLabel>
          <div style={{ display: 'flex', gap: 8 }}>
            {[
              { val: true, label: '知道', desc: '角色清楚自己的本地身份' },
              { val: false, label: '不知道', desc: '失忆开局,之后可能揭开' },
            ].map(({ val, label, desc }) => {
              const sel = identityKnown === val;
              return (
                <button key={String(val)} onClick={() => setIdentityKnown(val)} style={{
                  flex: '1 1 0', textAlign: 'left', padding: '10px 12px', cursor: 'pointer',
                  border: sel ? '1px solid var(--accent-edge)' : '1px solid var(--line-soft)',
                  borderRadius: 10, background: sel ? 'var(--accent-soft)' : 'var(--panel)',
                  display: 'grid', gap: 3, transition: 'border-color .12s, background .12s',
                }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: sel ? 'var(--accent)' : 'var(--text)' }}>{label}</span>
                  <span style={{ fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.5 }}>{desc}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/* ================================================================
   STEP 3 — 引导与防剧透 + 故事意图
   ================================================================ */
function StepMeta({ foreknowledge, setForeknowledge, npcAwareness, setNpcAwareness, steering, setSteering, spoiler, setSpoiler, storyIntent, setStoryIntent }) {
  const segOpts = (opts, cur, set) => (
    <div className="pl-seg2">
      {opts.map(([v, lbl]) => (
        <button key={v} className={cur === v ? 'active' : ''} onClick={() => set(v)}>{lbl}</button>
      ))}
    </div>
  );

  return (
    <div style={{ display: 'grid', gap: 22 }}>
      {/* 元知识 */}
      <div>
        <FieldLabel hint="你作为玩家,对原著剧情的了解程度">元知识/先知</FieldLabel>
        {segOpts([
          ['none', '无先知'],
          ['partial', '部分'],
          ['omniscient', '全知'],
        ], foreknowledge, setForeknowledge)}
      </div>

      {/* NPC 起疑 */}
      <div>
        <FieldLabel hint="世界中的 NPC 对你的异常行为有多敏感">NPC 起疑阈值</FieldLabel>
        {segOpts([
          ['oblivious', '迟钝'],
          ['suspicious', '多疑'],
        ], npcAwareness, setNpcAwareness)}
      </div>

      {/* 引导强度 */}
      <div>
        <FieldLabel hint="GM 引导故事走向的力度">故事引导</FieldLabel>
        {segOpts([
          ['rail', '强引导'],
          ['guided', '适度'],
          ['free', '自由'],
        ], steering, setSteering)}
      </div>

      {/* 防剧透 */}
      <div>
        <FieldLabel hint="GM 保护原著剧情不被过早揭露">防剧透等级</FieldLabel>
        {segOpts([
          ['strict', '严格'],
          ['loose', '宽松'],
        ], spoiler, setSpoiler)}
      </div>

      {/* 故事意图 */}
      <div>
        <FieldLabel hint="告诉 GM 你的游戏方向与偏好(可选)">故事意图</FieldLabel>
        <textarea
          className="pl-input"
          rows={4}
          value={storyIntent}
          onChange={e => setStoryIntent(e.target.value)}
          placeholder={"示例:\n· 拒绝战斗,须找非战斗解法\n· 穿越者身份是绝对秘密\n· 优先甜文路线"}
        />
      </div>
    </div>
  );
}

/* ================================================================
   STEP 4 — 确认
   ================================================================ */
function StepConfirm({ title, setTitle, scripts, scriptId, birthpoint, roleMode, pickedCard, newCardName, allRoleOptions, playerOrigin, identity, foreknowledge, npcAwareness, steering, spoiler, submitErr, submitting }) {
  const selScript = scripts.find(s => String(s.id) === String(scriptId)) || null;
  const pickedOpt = allRoleOptions.find(o => o.key === pickedCard);
  const roleName = roleMode === 'new' ? (newCardName.trim() || '(新建角色)') : (pickedOpt?.name || '—');
  const origLabel = ORIGIN_OPTIONS.find(o => o.value === playerOrigin)?.label || playerOrigin;

  const rows = [
    { k: '存档名称', v: title.trim() || '—', highlight: !title.trim() },
    { k: '剧本', v: selScript?.title || '—', highlight: !selScript },
    { k: '出生点', v: birthpoint?.story_time_label || '从开头' },
    { k: '角色', v: roleName, highlight: !roleName || roleName === '—' },
    { k: '出身', v: origLabel },
    { k: '身份', v: identity ? `${identity.name || ''} ${identity.role || ''}`.trim() || '(已设置)' : '未挂靠' },
    { k: '元知识', v: { none: '无先知', partial: '部分', omniscient: '全知' }[foreknowledge] || foreknowledge },
    { k: '引导', v: { rail: '强引导', guided: '适度', free: '自由' }[steering] || steering },
    { k: '防剧透', v: { strict: '严格', loose: '宽松' }[spoiler] || spoiler },
  ];

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="pl-field">
        <label>存档名称 <span style={{ color: 'var(--danger)' }}>*</span></label>
        <input
          className="pl-input"
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="给这段旅程起个名字"
          autoFocus
        />
      </div>

      <div style={{ border: '1px solid var(--line-soft)', borderRadius: 12, overflow: 'hidden' }}>
        {rows.map((row, i) => (
          <div key={row.k} style={{
            display: 'grid', gridTemplateColumns: '80px 1fr', gap: 12, alignItems: 'baseline',
            padding: '10px 13px', borderTop: i > 0 ? '1px solid var(--line-soft)' : 'none',
          }}>
            <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '.1em', color: 'var(--muted-2)' }}>{row.k}</span>
            <span style={{ fontSize: 13.5, color: row.highlight ? 'var(--danger)' : 'var(--text)', fontFamily: 'var(--font-serif)' }}>{row.v}</span>
          </div>
        ))}
      </div>

      <ErrBar msg={submitErr} />

      {submitting && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: 'var(--muted)', justifyContent: 'center', padding: '6px 0' }}>
          <Icon name="spinner" size={13} className="spin" /> 正在创建存档…
        </div>
      )}
    </div>
  );
}

/* ================================================================
   主组件
   ================================================================ */
export function MobileNewGame({ nav, scriptId: propScriptId, onDone }) {
  const lockedScriptId = propScriptId ? String(propScriptId) : null;

  // ── 数据加载 ──
  const [scripts, setScripts] = useState([]);
  const [personas, setPersonas] = useState([]);
  const [userCards, setUserCards] = useState([]);
  const [dataLoading, setDataLoading] = useState(true);
  const [dataErr, setDataErr] = useState('');

  // ── Step 0 state ──
  const [scriptId, setScriptId] = useState(lockedScriptId || '');
  const [birthpoint, setBirthpoint] = useState(null);

  // ── Step 1 state ──
  const [roleMode, setRoleMode] = useState('existing');
  const [pickedCard, setPickedCard] = useState('');
  const [newCardName, setNewCardName] = useState('');
  const [newCardRole, setNewCardRole] = useState('');
  const [newCardBg, setNewCardBg] = useState('');

  // ── Step 2 state ──
  const [playerOrigin, setPlayerOrigin] = useState('soul');
  const [identity, setIdentity] = useState(null);
  const [identityKnown, setIdentityKnown] = useState(true);

  // ── Step 3 state ──
  const [foreknowledge, setForeknowledge] = useState('none');
  const [npcAwareness, setNpcAwareness] = useState('oblivious');
  const [steering, setSteering] = useState('guided');
  const [spoiler, setSpoiler] = useState('loose');
  const [storyIntent, setStoryIntent] = useState('');

  // ── Step 4 state ──
  const [title, setTitle] = useState('');

  // ── 向导控制 ──
  const [step, setStep] = useState(0);
  const [submitErr, setSubmitErr] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // ── 草稿恢复 ──
  const DRAFT_KEY = 'mobile_newgame.draft.v1';
  const draftReadyRef = useRef(false);

  // ── 加载数据 ──
  useEffect(() => {
    draftReadyRef.current = false;
    setDataLoading(true); setDataErr('');
    (async () => {
      let scList = []; let psList = []; let ucList = [];
      try { const r = await window.api.scripts.list(); scList = Array.isArray(r) ? r : (r?.items || r?.scripts || []); } catch (_) {}
      try { const p = await window.api.account.personas.list(); psList = (p && (p.items || p.personas)) || []; } catch (_) {}
      try { const c = await window.api.cards.myList(); ucList = (c && (c.items || c.cards)) || []; } catch (_) {}
      setScripts(scList);
      setPersonas(psList);
      setUserCards(ucList);

      // 默认剧本
      if (!lockedScriptId) {
        let pickId = '';
        try { pickId = localStorage.getItem('newgame.lastScriptId') || ''; } catch (_) {}
        if (!pickId || !scList.some(x => String(x.id) === pickId && !scriptBlockReason(x))) {
          const first = scList.find(x => !scriptBlockReason(x));
          pickId = first ? String(first.id) : (scList.length ? String(scList[0].id) : '');
        }
        setScriptId(pickId);
        // 默认存档名
        const sc = scList.find(x => String(x.id) === pickId);
        const scTitle = (sc && (sc.title || '').replace(/^《|》$/g, '')) || '';
        setTitle(scTitle ? `${scTitle} · 新档` : '');
      } else {
        const sc = scList.find(x => String(x.id) === lockedScriptId);
        const scTitle = (sc && (sc.title || '').replace(/^《|》$/g, '')) || '';
        setTitle(scTitle ? `${scTitle} · 新档` : '');
      }

      // 默认角色
      if (psList.length) { setRoleMode('existing'); setPickedCard(`persona:${psList[0].id || psList[0].slug}`); }
      else if (ucList.length) { setRoleMode('existing'); setPickedCard(`user:${ucList[0].id || ucList[0].slug}`); }
      else { setRoleMode('new'); setPickedCard(''); }

      // 草稿恢复
      try {
        const draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null');
        if (draft && typeof draft === 'object') {
          const sameScript = !lockedScriptId || String(draft.scriptId) === lockedScriptId;
          if (sameScript) {
            if (typeof draft.title === 'string') setTitle(draft.title);
            if (draft.scriptId && scList.some(x => String(x.id) === String(draft.scriptId))) setScriptId(String(draft.scriptId));
            if (draft.roleMode) setRoleMode(draft.roleMode);
            if (typeof draft.pickedCard === 'string') setPickedCard(draft.pickedCard);
            if (typeof draft.newCardName === 'string') setNewCardName(draft.newCardName);
            if (typeof draft.newCardRole === 'string') setNewCardRole(draft.newCardRole);
            if (typeof draft.newCardBg === 'string') setNewCardBg(draft.newCardBg);
            if ('birthpoint' in draft) setBirthpoint(draft.birthpoint);
            if (draft.playerOrigin) setPlayerOrigin(draft.playerOrigin);
            if ('identity' in draft) setIdentity(draft.identity);
            if ('identityKnown' in draft) setIdentityKnown(draft.identityKnown);
            if (draft.foreknowledge) setForeknowledge(draft.foreknowledge);
            if (draft.npcAwareness) setNpcAwareness(draft.npcAwareness);
            if (draft.steering) setSteering(draft.steering);
            if (draft.spoiler) setSpoiler(draft.spoiler);
            if (typeof draft.storyIntent === 'string') setStoryIntent(draft.storyIntent);
            if (typeof draft.step === 'number' && draft.step < TOTAL_STEPS) setStep(draft.step);
          }
        }
      } catch (_) {}

      setDataLoading(false);
      draftReadyRef.current = true;
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 草稿回写
  useEffect(() => {
    if (!draftReadyRef.current) return;
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({
        scriptId, title, roleMode, pickedCard, newCardName, newCardRole, newCardBg,
        birthpoint, playerOrigin, identity, identityKnown,
        foreknowledge, npcAwareness, steering, spoiler, storyIntent, step,
      }));
    } catch (_) {}
  }, [scriptId, title, roleMode, pickedCard, newCardName, newCardRole, newCardBg,
      birthpoint, playerOrigin, identity, identityKnown,
      foreknowledge, npcAwareness, steering, spoiler, storyIntent, step]);

  // ── 各步骤校验 ──
  const allRoleOptions = [
    ...personas.map(p => ({ key: `persona:${p.id || p.slug}`, kind: 'persona', id: p.id || null, slug: p.slug || '', name: p.name || '(未命名)', subtitle: p.role || '人格', pinned: !!p.is_default })),
    ...userCards.map(c => ({ key: `user:${c.id || c.slug}`, kind: 'user_card', id: c.id || null, slug: c.slug || '', name: c.name || '(未命名)', subtitle: c.identity || c.role || '角色卡', pinned: false })),
  ];

  const selScript = scripts.find(s => String(s.id) === String(scriptId)) || null;
  const step0Valid = !!scriptId && !scriptBlockReason(selScript);
  const step1Valid = (roleMode === 'existing' && !!pickedCard) || (roleMode === 'new' && !!newCardName.trim());
  const step2Valid = true; // 身份是可选项
  const step3Valid = true; // meta 都有默认值
  const step4Valid = !!title.trim() && step0Valid && step1Valid;

  const canNext = [step0Valid, step1Valid, step2Valid, step3Valid][step] ?? true;

  // ── 提交 ──
  const handleCreate = async () => {
    setSubmitErr(''); setSubmitting(true);
    try {
      // 有效性最终检查
      const sc = scripts.find(s => String(s.id) === String(scriptId));
      const blockRsn = scriptBlockReason(sc);
      if (blockRsn) throw new Error(blockRsn);

      // 有活跃 job 时再 check 一次
      const activeJob = scriptId ? await window.api.scripts.activeJob(parseInt(scriptId, 10)).catch(() => null) : null;
      if (activeJob) {
        const ajStatus = String(activeJob?.status || activeJob?.active_job?.status || '').toLowerCase();
        if (ajStatus && NEWGAME_ACTIVE_IMPORT_STATUSES.has(ajStatus) && !NEWGAME_IMPORT_TERMINAL_STATUSES.has(ajStatus)) {
          throw new Error('剧本正在导入,请稍后重试');
        }
      }

      // 新建角色卡
      let charId = null; let charKind = null;
      let finalRoleMode = roleMode;
      if (roleMode === 'existing') {
        const opt = allRoleOptions.find(o => o.key === pickedCard);
        charId = opt ? (opt.id || opt.slug || null) : null;
        charKind = opt ? opt.kind : null;
      } else {
        const r = await window.api.cards.myUpsert({
          name: newCardName.trim(),
          identity: newCardRole.trim() || undefined,
          background: newCardBg.trim() || undefined,
          kind: 'user',
        });
        const created = r && r.card;
        if (!created || !(created.id || created.slug)) throw new Error('角色卡创建失败');
        charId = created.id || created.slug;
        charKind = 'user_card';
        finalRoleMode = 'existing';
      }

      const payload = {
        title: title.trim(),
        script_id: parseInt(scriptId, 10),
        character_id: charId,
        character_kind: charKind,
        new_card: null,
        role_mode: finalRoleMode,
        birthpoint: birthpoint || null,
        identity: identity ? {
          name: identity.name || '',
          role: identity.role || '',
          background: identity.background || '',
          source: identity.source || 'custom',
        } : null,
        story_intent: storyIntent.trim() || null,
        player_origin: playerOrigin || 'soul',
        ...(identity && playerOrigin !== 'body' ? { identity_known: identityKnown } : {}),
        // 设置字段(mapping to backend settings schema):
        foreknowledge_mode: foreknowledge,
        npc_awareness: npcAwareness,
        steering_strength: steering,
        spoiler_guard: spoiler,
      };

      await window.__createAndEnterSave(payload);

      // 成功后清草稿(如果 __createAndEnterSave 跳页了就不会执行到这里)
      try { localStorage.removeItem(DRAFT_KEY); } catch (_) {}
      onDone?.();
      nav.pop();
    } catch (e) {
      const msg = e?.message || (e?.payload && (e.payload.error || e.payload.detail)) || '创建失败';
      setSubmitErr(msg);
    }
    setSubmitting(false);
  };

  // ── 渲染 ──
  return (
    <>
      {/* 顶栏 */}
      <div className="pl-head">
        <button className="pl-back" onClick={() => step > 0 ? setStep(s => s - 1) : nav.pop()} aria-label="返回">
          <Icon name="chevron_left" size={17} />
        </button>
        <div className="pl-head-title">
          <strong>{STEPS[step].title}</strong>
          <StepDots step={step} total={TOTAL_STEPS} />
        </div>
      </div>

      {/* 内容区 */}
      <div className="pl-body" style={{ paddingBottom: 100 }}>
        <div className="pl-pad">
          {dataLoading ? (
            <Loading text="加载向导数据…" />
          ) : dataErr ? (
            <ErrBar msg={dataErr} />
          ) : (
            <>
              {step === 0 && (
                <StepScriptBirth
                  scripts={scripts}
                  lockedScriptId={lockedScriptId}
                  scriptId={scriptId}
                  setScriptId={v => { setScriptId(v); try { localStorage.setItem('newgame.lastScriptId', v); } catch (_) {} }}
                  birthpoint={birthpoint}
                  setBirthpoint={setBirthpoint}
                />
              )}
              {step === 1 && (
                <StepRole
                  personas={personas}
                  userCards={userCards}
                  roleMode={roleMode}
                  setRoleMode={setRoleMode}
                  pickedCard={pickedCard}
                  setPickedCard={setPickedCard}
                  newCardName={newCardName}
                  setNewCardName={setNewCardName}
                  newCardRole={newCardRole}
                  setNewCardRole={setNewCardRole}
                  newCardBg={newCardBg}
                  setNewCardBg={setNewCardBg}
                />
              )}
              {step === 2 && (
                <StepIdentity
                  scriptId={scriptId}
                  birthpoint={birthpoint}
                  pickedCard={pickedCard}
                  allRoleOptions={allRoleOptions}
                  playerOrigin={playerOrigin}
                  setPlayerOrigin={setPlayerOrigin}
                  identity={identity}
                  setIdentity={setIdentity}
                  identityKnown={identityKnown}
                  setIdentityKnown={setIdentityKnown}
                />
              )}
              {step === 3 && (
                <StepMeta
                  foreknowledge={foreknowledge}
                  setForeknowledge={setForeknowledge}
                  npcAwareness={npcAwareness}
                  setNpcAwareness={setNpcAwareness}
                  steering={steering}
                  setSteering={setSteering}
                  spoiler={spoiler}
                  setSpoiler={setSpoiler}
                  storyIntent={storyIntent}
                  setStoryIntent={setStoryIntent}
                />
              )}
              {step === 4 && (
                <StepConfirm
                  title={title}
                  setTitle={setTitle}
                  scripts={scripts}
                  scriptId={scriptId}
                  birthpoint={birthpoint}
                  roleMode={roleMode}
                  pickedCard={pickedCard}
                  newCardName={newCardName}
                  allRoleOptions={allRoleOptions}
                  playerOrigin={playerOrigin}
                  identity={identity}
                  foreknowledge={foreknowledge}
                  npcAwareness={npcAwareness}
                  steering={steering}
                  spoiler={spoiler}
                  submitErr={submitErr}
                  submitting={submitting}
                />
              )}
            </>
          )}
        </div>
      </div>

      {/* 底部按钮栏 */}
      {!dataLoading && (
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0,
          padding: '12px 16px calc(var(--safe-bottom) + 12px)',
          background: 'linear-gradient(to bottom, transparent, var(--bg) 30%)',
          display: 'flex', gap: 10,
        }}>
          {step > 0 && (
            <button className="pl-btn-ghost" style={{ flex: 1 }} onClick={() => setStep(s => s - 1)}>
              <Icon name="chevron_left" size={15} /> 上一步
            </button>
          )}
          {step < TOTAL_STEPS - 1 ? (
            <button
              className="pl-btn-primary"
              style={{ flex: 2, opacity: canNext ? 1 : 0.45 }}
              disabled={!canNext || dataLoading}
              onClick={() => { if (canNext) setStep(s => s + 1); }}
            >
              下一步 <Icon name="chevron_right" size={15} />
            </button>
          ) : (
            <button
              className="pl-btn-primary"
              style={{ flex: 2, opacity: (step4Valid && !submitting) ? 1 : 0.45 }}
              disabled={!step4Valid || submitting}
              onClick={handleCreate}
            >
              {submitting ? <><Icon name="spinner" size={15} className="spin" /> 创建中…</> : <><Icon name="play" size={15} /> 开始游戏</>}
            </button>
          )}
        </div>
      )}
    </>
  );
}

export default MobileNewGame;
