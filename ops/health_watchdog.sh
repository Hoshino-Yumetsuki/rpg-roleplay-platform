#!/usr/bin/env bash
# rpg-health-watchdog —— 后端「活着但不响应」(wedge)自愈 + 重启前抓栈留证
# ==========================================================================
# 背景:systemd 的 Restart=always 只能救「进程退出」(crash)。但 2026-06-14 的
# CF 524 事故是另一种:uvicorn worker 全被在途请求占满 / 事件循环卡死 —— 进程还在
# (CPU≈0、不退出),Restart= 永不触发,health 探测却超时。此脚本由
# rpg-health-watchdog.timer 每 30s 触发一次(oneshot),主动探活,连续失败到阈值就:
#   ① 用 py-spy 抓所有 worker 的 Python 栈到 DIAG_DIR(留证,定位 wedge 根因)
#   ② 重启 rpg-backend
# 带:冷却、防风暴(崩溃循环上锁停手 + 持续健康后自动解锁)、导入保护、flock 防并发。
# 所有动作进 journal:journalctl -u rpg-health-watchdog
#
# 全部阈值可用 WATCHDOG_* 环境变量覆盖(默认即生产值)。WATCHDOG_DRY_RUN=1 只记日志不重启。
# ==========================================================================
set -uo pipefail

HEALTH_URL="${WATCHDOG_HEALTH_URL:-http://127.0.0.1:7860/api/health}"
SERVICE="${WATCHDOG_SERVICE:-rpg-backend}"
CURL_TIMEOUT="${WATCHDOG_CURL_TIMEOUT:-10}"            # 单次探测超时(秒);>此值算「不响应」
THRESHOLD="${WATCHDOG_THRESHOLD:-3}"                   # 连续失败几次才重启(×30s ≈ 90s)
IMPORT_THRESHOLD="${WATCHDOG_IMPORT_THRESHOLD:-10}"   # 有活跃导入时放宽到 ~5min,别打断用户导入
COOLDOWN="${WATCHDOG_COOLDOWN:-180}"                  # 两次自愈最小间隔(秒)
STORM_WINDOW="${WATCHDOG_STORM_WINDOW:-1800}"         # 风暴统计窗口(30min)
STORM_MAX="${WATCHDOG_STORM_MAX:-4}"                  # 窗口内自愈 ≥ 此数 → 判崩溃循环,上锁停手
REARM_OK="${WATCHDOG_REARM_OK:-60}"                  # escalation 后连续健康 ≥此数(×30s≈30min)自动解锁
STATE_DIR="${WATCHDOG_STATE_DIR:-/run/rpg-watchdog}"  # tmpfs,重启清零(可接受)
DIAG_DIR="${WATCHDOG_DIAG_DIR:-/var/tmp/rpg-diag}"   # 持久:py-spy 抓栈留证
PYSPY="${WATCHDOG_PYSPY:-/opt/rpg-roleplay/rpg/.venv/bin/py-spy}"
DRY_RUN="${WATCHDOG_DRY_RUN:-0}"                      # 1 = 只记日志不真重启(测试用)

FAILS_FILE="$STATE_DIR/fails"
OK_FILE="$STATE_DIR/ok"                               # 连续健康计数(供 escalation 自动解锁)
ESCALATED_FILE="$STATE_DIR/escalated"                # 存在=已上锁,停止自动重启
HISTORY_FILE="$STATE_DIR/restart_history"            # 每行一个自愈 epoch(供冷却/防风暴)

log() { echo "[rpg-watchdog] $*"; }                  # systemd 捕获进 journal

# 读一个整数状态文件,非数字/八进制/缺失都归一(fail-safe,防 set -u 在算术里炸 + 八进制误算)
read_int() { local v; v=$(cat "$1" 2>/dev/null || echo 0); [[ "$v" =~ ^[0-9]+$ ]] || v=0; echo "$(( 10#$v ))"; }

mkdir -p "$STATE_DIR"
now=$(date +%s)

# flock 防并发(探测慢时上一轮可能没退完);flock 缺失则降级为不加锁(timer 正常不重叠)
if command -v flock >/dev/null 2>&1; then
  exec 9>"$STATE_DIR/.lock"
  flock -n 9 || { log "另一实例在跑,跳过本轮"; exit 0; }
fi

# ---- 探测 ----
code=$(curl -s -m "$CURL_TIMEOUT" -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null)
code="${code:-000}"

if [ "$code" = "200" ]; then
  prev=$(read_int "$FAILS_FILE")
  [ "$prev" != "0" ] && log "health 恢复 200(此前连续失败 ${prev} 次),清零计数"
  echo 0 > "$FAILS_FILE"
  # 连续健康计数 → escalation 上锁后,持续健康足够久就自动解锁重新武装
  okc=$(( $(read_int "$OK_FILE") + 1 ))
  echo "$okc" > "$OK_FILE"
  if [ -f "$ESCALATED_FILE" ] && [ "$okc" -ge "$REARM_OK" ]; then
    log "health 已连续稳定 ${okc}×探测(≥${REARM_OK})→ 解除 escalation 锁,重新武装自愈"
    rm -f "$ESCALATED_FILE"; : > "$HISTORY_FILE"
  fi
  exit 0
fi

# ---- 失败:计数 + 清零连续健康 ----
echo 0 > "$OK_FILE"
fails=$(( $(read_int "$FAILS_FILE") + 1 ))
echo "$fails" > "$FAILS_FILE"

# 活跃导入 → 放宽阈值(导入若已停滞,失败终会累积到放宽阈值仍触发)。查询异常一律按「无导入」(fail-safe)。
active_import=$(timeout 5 runuser -u postgres -- psql -d rpg -tAc \
  "select count(*) from import_jobs where status in ('pending','running','staging','processing','queued')" \
  2>/dev/null | tr -d '[:space:]')
[[ "$active_import" =~ ^[0-9]+$ ]] || active_import=0
effective_threshold="$THRESHOLD"
[ "$active_import" -gt 0 ] && effective_threshold="$IMPORT_THRESHOLD"

log "health 异常 code=$code,连续失败 ${fails}/${effective_threshold}(活跃导入=${active_import})"
[ "$fails" -lt "$effective_threshold" ] && exit 0

# ---- 冷却:距上次自愈不足 COOLDOWN 就先等(给重启后恢复留时间)----
last_restart=$(tail -n1 "$HISTORY_FILE" 2>/dev/null || echo 0)
[[ "$last_restart" =~ ^[0-9]+$ ]] || last_restart=0
if [ $(( now - last_restart )) -lt "$COOLDOWN" ]; then
  log "距上次自愈 $(( now - last_restart ))s < 冷却 ${COOLDOWN}s,本轮不重启,继续观察"
  exit 0
fi

# ---- 防风暴 / 崩溃循环:窗口内自愈过多 → 上锁停手(重启救不了,需人工)----
recent=0
if [ -f "$HISTORY_FILE" ]; then
  while read -r t; do
    [[ "$t" =~ ^[0-9]+$ ]] || continue
    [ $(( now - t )) -le "$STORM_WINDOW" ] && recent=$(( recent + 1 ))
  done < "$HISTORY_FILE"
fi
if [ "$recent" -ge "$STORM_MAX" ] || [ -f "$ESCALATED_FILE" ]; then
  touch "$ESCALATED_FILE"
  log "ESCALATE: ${STORM_WINDOW}s 内自愈 ${recent} 次(≥${STORM_MAX})— 疑似崩溃循环,已上锁停止自动重启,需人工介入(健康持续 ${REARM_OK}×30s 后自动解锁,或删 ${ESCALATED_FILE})"
  exit 0
fi

# ---- 重启前抓栈留证(py-spy):master + 其 worker 子进程 ----
capture_stacks() {
  [ -x "$PYSPY" ] || { log "py-spy 不存在($PYSPY),跳过抓栈"; return; }
  mkdir -p "$DIAG_DIR"
  local ts master pids dumpf
  ts=$(date +%Y%m%d-%H%M%S)
  dumpf="$DIAG_DIR/pyspy-${ts}.txt"
  master=$(pgrep -f "uvicorn app:app" 2>/dev/null | head -1)
  pids="$master $(pgrep -P "${master:-0}" 2>/dev/null | tr '\n' ' ')"
  log "重启前 py-spy 抓栈 → $dumpf (pids: $pids)"
  { echo "# wedge capture $ts  health=$code fails=$fails"; } > "$dumpf"
  for wp in $pids; do
    [ -n "$wp" ] || continue
    echo "===== pid $wp =====" >> "$dumpf"
    timeout 25 "$PYSPY" dump --pid "$wp" >> "$dumpf" 2>&1 || echo "(py-spy dump failed for $wp)" >> "$dumpf"
  done
}

# ---- 执行自愈 ----
if [ "$DRY_RUN" = "1" ]; then
  log "DRY_RUN: 本应抓栈并 restart ${SERVICE}(连续失败 ${fails} 次)— 不真重启"
  exit 0
fi

capture_stacks
log "AUTO-HEAL: 连续 ${fails} 次 health 失败 → 重启 ${SERVICE}"
systemctl reset-failed "$SERVICE" 2>/dev/null || true
if systemctl restart "$SERVICE"; then
  log "AUTO-HEAL: ${SERVICE} 重启完成"
  echo "$now" >> "$HISTORY_FILE"
  echo 0 > "$FAILS_FILE"
  awk -v now="$now" -v win="$STORM_WINDOW" '($0+0) >= now-win' "$HISTORY_FILE" > "$HISTORY_FILE.tmp" 2>/dev/null \
    && mv "$HISTORY_FILE.tmp" "$HISTORY_FILE"
else
  log "AUTO-HEAL: ${SERVICE} 重启失败(systemctl 非零退出)!需人工介入"
fi
exit 0
