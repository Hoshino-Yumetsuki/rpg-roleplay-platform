// @ts-nocheck

/**
 * feedback.jsx — 「支持与反馈」页(参考 AWS 支持中心)。路由 /feedback。
 * 职责:历史反馈(状态/官方回复)+ 完整新反馈表单。快速新反馈走顶栏「反馈」弹窗(FeedbackQuickModal)。
 * 后端契约:POST /api/feedback · GET /api/me/feedback · DELETE /api/feedback/{id}
 *
 * 布局:单列居中(无空旷右栏)。内容限制 → 提交反馈 → 我的反馈记录(KPI + 状态筛选 + 卡片)
 *       → 玩家群/提示(等宽双列页脚)。
 */
import React from 'react';
import CSBox from '@cloudscape-design/components/box';
import CSButton from '@cloudscape-design/components/button';
import CSAlert from '@cloudscape-design/components/alert';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSTextarea from '@cloudscape-design/components/textarea';
import CSCheckbox from '@cloudscape-design/components/checkbox';
import CSFormField from '@cloudscape-design/components/form-field';
import CSContainer from '@cloudscape-design/components/container';
import CSHeader from '@cloudscape-design/components/header';
import CSBadge from '@cloudscape-design/components/badge';
import CSColumnLayout from '@cloudscape-design/components/column-layout';
import CSSegmentedControl from '@cloudscape-design/components/segmented-control';
import { sha256hex } from '../../lib/crypto-safe';

const CONSENT_TEXT = '我已阅读 AUP §2.J,理解不得包含成人主题节选,同意(此操作记录我的同意)';
const AUP_LINK = 'https://play.stellatrix.icu/legal/aup#2J';
const MAX_FREE_TEXT = 10000;
const QQ_GROUP_NUMBER = '584876566';
const QQ_JOIN_URL = 'https://qm.qq.com/q/49Dqcr0aw0';
const QQ_QR_SRC = '/qq-group.jpg';

function statusLabel(d) {
  return !d ? '待处理' : d === 'ok' ? '已采纳' : d === 'spam' ? '未采纳' : d === 'nsfw_terminate' ? '违规处理' : d;
}
function statusColor(d) {
  return !d ? 'blue' : d === 'ok' ? 'green' : d === 'spam' ? 'grey' : 'red';
}
function fmtTime(ts) {
  if (!ts) return '—';
  try { return new Date(ts).toLocaleString('zh-CN', { hour12: false }); } catch (_) { return ts; }
}

function Kpi({ label, value, color }) {
  return (
    <div style={{ padding: '14px 16px', border: '1px solid var(--line, #36322d)', borderRadius: 10, background: 'var(--panel, #211f1d)' }}>
      <div style={{ fontSize: 28, fontWeight: 700, lineHeight: 1.1, color: color || 'var(--text, #e8e3d9)' }}>{value}</div>
      <div style={{ fontSize: 12.5, color: 'var(--text-quiet, #968f85)', marginTop: 4 }}>{label}</div>
    </div>
  );
}

export function FeedbackPage() {
  const [freeText, setFreeText] = React.useState('');
  const [includeRuntime, setIncludeRuntime] = React.useState(true);
  const [includeExcerpts, setIncludeExcerpts] = React.useState(false);
  const [selectedExcerpts, setSelectedExcerpts] = React.useState([]);
  const [recentTurns, setRecentTurns] = React.useState([]);
  const [consent, setConsent] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [done, setDone] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [runtimePreview, setRuntimePreview] = React.useState(null);
  const [history, setHistory] = React.useState([]);
  const [historyLoading, setHistoryLoading] = React.useState(false);
  const [historyError, setHistoryError] = React.useState(null);
  const [filter, setFilter] = React.useState('all');   // all | pending | ok | other

  const loadHistory = React.useCallback(async () => {
    setHistoryLoading(true); setHistoryError(null);
    try {
      const res = await fetch('/api/me/feedback?limit=50', { credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (!data || !data.ok) throw new Error(data?.error || '读取反馈记录失败');
      setHistory(Array.isArray(data.items) ? data.items : []);
    } catch (e) { setHistoryError(e?.message || '读取反馈记录失败'); }
    finally { setHistoryLoading(false); }
  }, []);

  React.useEffect(() => {
    try {
      const snap = window.__getRuntimeSnapshot && window.__getRuntimeSnapshot();
      setRuntimePreview(snap ? snap.__runtime__ : null);
    } catch (_) { setRuntimePreview(null); }
    loadHistory();
  }, [loadHistory]);

  React.useEffect(() => {
    if (!includeExcerpts) return;
    let cancelled = false;
    (async () => {
      try {
        let nodes = null;
        let saveId = '';
        try {
          const state = await window.api?.game?.state?.();
          nodes = state?.history || state?.branch_nodes || state?.turns || null;
          saveId = state?.save_id || state?._raw?.save_id || '';
        } catch (_) { /* 回退 */ }
        if (!Array.isArray(nodes) || nodes.length === 0) {
          if (window.MOCK_STATE && Array.isArray(window.MOCK_STATE.history)) nodes = window.MOCK_STATE.history;
          saveId = saveId || window.MOCK_STATE?._raw?.save_id || '';
        }
        const recent = (Array.isArray(nodes) ? nodes : [])
          .filter((n) => n && (n.role === 'user' || n.role === 'assistant' || n.role === 'gm') && (n.content || n.text));
        const turns = recent.slice(-6).map((n, i) => ({
          idx: i, session_id: saveId, range: String(n.turn_index ?? n.turn ?? i),
          plaintext: ((n.content || n.text || '') + '').slice(0, 200),
          label: n.role === 'user' ? '玩家' : 'GM',
        }));
        if (!cancelled) setRecentTurns(turns);
      } catch (_) { if (!cancelled) setRecentTurns([]); }
    })();
    return () => { cancelled = true; };
  }, [includeExcerpts]);

  const toggleExcerpt = (idx) => setSelectedExcerpts((p) => p.includes(idx) ? p.filter((i) => i !== idx) : [...p, idx]);
  const canSubmit = consent && freeText.trim().length > 0 && freeText.length <= MAX_FREE_TEXT && !busy;

  async function handleSubmit() {
    if (!canSubmit) return;
    setBusy(true); setError(null);
    try {
      const token = await sha256hex(CONSENT_TEXT);
      const excerpts = includeExcerpts
        ? recentTurns.filter((t) => selectedExcerpts.includes(t.idx)).map(({ session_id, range, plaintext }) => ({ session_id, range, plaintext }))
        : [];
      if (includeRuntime) {
        try {
          let freshHistory = null;
          try {
            const st = await window.api?.game?.state?.();
            if (st && Array.isArray(st.history)) freshHistory = st.history;
          } catch (_) {}
          const snap = window.__getRuntimeSnapshot && window.__getRuntimeSnapshot({ includeRecentDialog: true, recentDialog: freshHistory });
          if (snap && snap.__runtime__) excerpts.push(snap);
        } catch (_) {}
      }
      const res = await fetch('/api/feedback', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ free_text: freeText, excerpts, consent_token: token, app_version: window.__APP_VERSION__ || '' }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
      setDone(true); setFreeText(''); setConsent(false); setIncludeExcerpts(false); setSelectedExcerpts([]);
      await loadHistory();
    } catch (e) { setError(e?.message || '提交失败,请稍后重试'); }
    finally { setBusy(false); }
  }

  async function withdraw(id) {
    if (!(window.__confirm ? await window.__confirm({ title: '撤回反馈', message: `撤回反馈 #${id}?`, danger: true, confirmText: '撤回' }) : window.confirm(`撤回反馈 #${id}?`))) return;
    try {
      const res = await fetch(`/api/feedback/${id}`, { method: 'DELETE', credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      window.__apiToast?.('已撤回', { kind: 'ok', duration: 1800 });
      loadHistory();
    } catch (e) { window.__apiToast?.('撤回失败', { kind: 'danger', detail: e?.message }); }
  }

  // 统计 + 筛选
  const counts = React.useMemo(() => {
    let pending = 0, ok = 0;
    for (const it of history) { if (!it.review_decision) pending++; else if (it.review_decision === 'ok') ok++; }
    return { total: history.length, pending, ok };
  }, [history]);
  const filtered = React.useMemo(() => history.filter((it) => {
    if (filter === 'all') return true;
    if (filter === 'pending') return !it.review_decision;
    if (filter === 'ok') return it.review_decision === 'ok';
    return it.review_decision && it.review_decision !== 'ok';
  }), [history, filter]);

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', paddingBottom: 32 }}>
      <CSSpaceBetween size="l">
        <CSHeader
          variant="h1"
          description="提交问题或建议,跟踪处理进度与官方回复。需要快速反馈也可点顶栏「反馈」随时弹窗提交。"
          actions={<CSButton iconName="refresh" loading={historyLoading} onClick={loadHistory}>刷新</CSButton>}
        >支持与反馈</CSHeader>

        <CSAlert type="warning" header="内容限制">
          反馈渠道不得包含性、露骨、NSFW 等成人材料(无论是否年满 18)。违反将永久封号并加入禁注表。详见 <a href={AUP_LINK} target="_blank" rel="noopener noreferrer">AUP §2.J</a>。
        </CSAlert>

        {/* ── 提交反馈 ── */}
        <CSContainer header={<CSHeader variant="h2" description="带运行环境信息能让排查更快(仅管理员可见)。">提交反馈</CSHeader>}>
          <CSSpaceBetween size="m">
            {done && <CSAlert type="success" header="已收到你的反馈" dismissible onDismiss={() => setDone(false)}>感谢反馈!可在下方「我的反馈记录」跟进处理进度。</CSAlert>}
            {error && <CSAlert type="error" header="提交失败">{error}</CSAlert>}
            <CSFormField label="问题 / 建议" description={`最多 ${MAX_FREE_TEXT} 字`} errorText={freeText.length > MAX_FREE_TEXT ? `超过 ${MAX_FREE_TEXT} 字限制` : undefined}>
              <CSTextarea value={freeText} onChange={({ detail }) => setFreeText(detail.value)} placeholder="请描述你遇到的问题或建议…(复现步骤 / 期望 / 实际 越具体越好)" rows={6} disabled={busy} />
            </CSFormField>
            <CSCheckbox checked={includeRuntime} onChange={({ detail }) => setIncludeRuntime(detail.checked)} disabled={busy}>
              附带运行环境信息(页面 / 活动剧本存档 / 最近错误 / 最近 3 轮对话,仅管理员可见,强烈建议)
            </CSCheckbox>
            {includeRuntime && runtimePreview && (
              <CSBox fontSize="body-s" color="text-body-secondary">
                <div>页面 <code>{runtimePreview.hash || runtimePreview.url || '—'}</code> · 剧本 {String(runtimePreview.active?.script_id ?? '—')} / 存档 {String(runtimePreview.active?.save_id ?? '—')}</div>
                <div>错误 {runtimePreview.errors?.length || 0} 条 · 失败 API {runtimePreview.api_failures?.length || 0} 条 · {runtimePreview.viewport}</div>
              </CSBox>
            )}
            <CSCheckbox checked={includeExcerpts} onChange={({ detail }) => setIncludeExcerpts(detail.checked)} disabled={busy}>包含对话节选(最多 5 段)</CSCheckbox>
            {includeExcerpts && (
              recentTurns.length === 0
                ? <CSBox color="text-body-secondary" fontSize="body-s">暂无可用对话节选</CSBox>
                : <CSSpaceBetween size="xs">{recentTurns.map((t) => (
                    <CSCheckbox key={t.idx} checked={selectedExcerpts.includes(t.idx)} onChange={() => toggleExcerpt(t.idx)} disabled={busy}>
                      <strong>{t.label}</strong> <CSBox color="text-body-secondary" fontSize="body-s" display="inline">{t.plaintext.slice(0, 70)}{t.plaintext.length > 70 ? '…' : ''}</CSBox>
                    </CSCheckbox>
                  ))}</CSSpaceBetween>
            )}
            <CSFormField errorText={!consent && freeText.trim() ? '请先勾选同意以启用提交' : undefined}>
              <CSCheckbox checked={consent} onChange={({ detail }) => setConsent(detail.checked)} disabled={busy}>{CONSENT_TEXT}</CSCheckbox>
            </CSFormField>
            <CSBox><CSButton variant="primary" iconName="upload" onClick={handleSubmit} loading={busy} disabled={!canSubmit}>提交反馈</CSButton></CSBox>
          </CSSpaceBetween>
        </CSContainer>

        {/* ── 我的反馈记录 ── */}
        <CSContainer header={<CSHeader variant="h2" counter={history.length ? `(${history.length})` : undefined}>我的反馈记录</CSHeader>}>
          <CSSpaceBetween size="m">
            <CSColumnLayout columns={3} variant="text-grid">
              <Kpi label="全部反馈" value={counts.total} />
              <Kpi label="处理中" value={counts.pending} color="#5b9bd5" />
              <Kpi label="已采纳" value={counts.ok} color="#6cc04a" />
            </CSColumnLayout>

            <CSSegmentedControl
              selectedId={filter}
              onChange={({ detail }) => setFilter(detail.selectedId)}
              options={[
                { id: 'all', text: `全部 ${counts.total}` },
                { id: 'pending', text: `待处理 ${counts.pending}` },
                { id: 'ok', text: `已采纳 ${counts.ok}` },
                { id: 'other', text: '其它' },
              ]}
            />

            {historyError ? <CSAlert type="error" header="读取失败">{historyError}</CSAlert>
              : historyLoading && history.length === 0 ? <CSBox color="text-body-secondary" padding="m">正在读取…</CSBox>
              : history.length === 0 ? (
                <CSBox textAlign="center" color="text-body-secondary" padding={{ vertical: 'xl' }}>
                  还没有提交过反馈。上面写两句,或点顶栏「反馈」随时快速提交。
                </CSBox>
              ) : filtered.length === 0 ? (
                <CSBox textAlign="center" color="text-body-secondary" padding={{ vertical: 'l' }}>该筛选下暂无反馈。</CSBox>
              ) : (
                <CSSpaceBetween size="s">{filtered.map((it) => (
                  <div key={it.id} style={{ padding: '14px 16px', border: '1px solid var(--line, #36322d)', borderRadius: 10, background: 'var(--panel, #211f1d)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
                      <strong style={{ fontSize: 13.5 }}>#{it.id}</strong>
                      <CSBadge color={statusColor(it.review_decision)}>{statusLabel(it.review_decision)}</CSBadge>
                      <CSBox fontSize="body-s" color="text-body-secondary">提交 {fmtTime(it.created_at)}{it.reviewed_at ? ` · 处理 ${fmtTime(it.reviewed_at)}` : ''}</CSBox>
                      {!it.review_decision && <span style={{ marginLeft: 'auto' }}><CSButton variant="inline-link" iconName="remove" onClick={() => withdraw(it.id)}>撤回</CSButton></span>}
                    </div>
                    <CSBox fontSize="body-s" color="text-body-secondary">{it.free_text_preview || '(无文字内容)'}</CSBox>
                    {it.admin_reply && (
                      <div style={{ marginTop: 10, padding: '10px 13px', borderRadius: 8, background: 'var(--accent-soft, rgba(201,100,66,.12))', borderLeft: '3px solid var(--accent, #c96442)', fontSize: 13, lineHeight: 1.6 }}>
                        <strong>官方回复</strong>{it.replied_at ? <span style={{ color: 'var(--text-quiet,#968f85)', fontWeight: 400 }}> · {fmtTime(it.replied_at)}</span> : null}
                        <div style={{ marginTop: 3, whiteSpace: 'pre-wrap' }}>{it.admin_reply}</div>
                      </div>
                    )}
                  </div>
                ))}</CSSpaceBetween>
              )}
          </CSSpaceBetween>
        </CSContainer>

        {/* ── 页脚:玩家群 + 提示(等宽双列,填满宽度,无空旷)── */}
        <CSColumnLayout columns={2} variant="text-grid">
          <CSContainer header={<CSHeader variant="h3">玩家交流群</CSHeader>}>
            <CSSpaceBetween size="s">
              <CSBox fontSize="body-s" color="text-body-secondary">遇到问题、想交流玩法,欢迎加入玩家 QQ 群(群号 {QQ_GROUP_NUMBER})。</CSBox>
              <img src={QQ_QR_SRC} alt={`QQ 群二维码 ${QQ_GROUP_NUMBER}`} loading="lazy" style={{ width: 140, height: 'auto', borderRadius: 10, border: '1px solid var(--line, #36322d)' }} />
              <CSBox><CSButton variant="primary" href={QQ_JOIN_URL} target="_blank" iconName="external">用 QQ 加入群聊</CSButton></CSBox>
            </CSSpaceBetween>
          </CSContainer>
          <CSContainer header={<CSHeader variant="h3">提示</CSHeader>}>
            <CSBox fontSize="body-s" color="text-body-secondary">
              · 描述越具体越好:复现步骤、期望/实际、截图链接。<br />
              · bug 类请保留「附带运行环境信息」勾选,便于定位。<br />
              · 已处理的反馈会显示状态与官方回复。<br />
              · 快速反馈:任意页面点顶栏「反馈」即可弹窗提交,不打断当前操作。
            </CSBox>
          </CSContainer>
        </CSColumnLayout>
      </CSSpaceBetween>
    </div>
  );
}

export default FeedbackPage;
