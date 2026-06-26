# ops/ — 服务器自愈机制

后端是多用户在线服务,挂了影响所有人。这里是它的自动恢复机制。

## 覆盖的两类故障

| 故障 | 表现 | 谁来救 |
|---|---|---|
| **进程退出**(crash / OOM / 未捕获异常退出) | 进程没了 | systemd `Restart=always`(rpg-backend / rpg-postproc 已配) |
| **进程活着但不响应**(wedge:worker 被在途请求占满 / 事件循环卡死) | 进程在、CPU≈0、health 探测超时 | **本目录的 health watchdog**(`Restart=` 抓不到这种) |

第二类正是 2026-06-14 CF 524 事故的形态:4 个 uvicorn worker 全卡住,进程不退出,
systemd 毫无反应,只能人工 `systemctl restart`。watchdog 把这一步自动化。

## health_watchdog.sh 怎么工作

`rpg-health-watchdog.timer` 每 30s 触发一次 oneshot `rpg-health-watchdog.service` → 跑脚本:

1. `curl -m 10` 探 `http://127.0.0.1:7860/api/health`。
2. 200 → 清零失败计数,退出。
3. 非 200 / 超时 → 失败计数 +1(存 `/run/rpg-watchdog/fails`)。
4. 连续失败 ≥ **阈值**(默认 3 次 ≈ 90s)→ 自愈,但先过三道闸:
   - **导入保护**:有活跃 `import_jobs` 时阈值放宽到 10 次(≈5min),避免打断用户导入。
   - **冷却**:距上次自愈 < 180s 不重启(给恢复留时间)。
   - **防风暴**:30min 内已自愈 ≥4 次 → 判崩溃循环,**上锁停手 + 告警**(重启救不了,需人工)。
     上锁后持续健康 ≥60×30s(≈30min)自动解锁重新武装;或人工删 `/run/rpg-watchdog/escalated`。
5. 自愈动作 = **先 py-spy 抓所有 worker 的 Python 栈**到 `/var/tmp/rpg-diag/pyspy-<时间>.txt`(留证,定位 wedge 根因)→ `systemctl reset-failed`(防 start-limit)→ `systemctl restart`。

所有动作进 journal:`journalctl -u rpg-health-watchdog -f`。
状态在 `/run/rpg-watchdog/`(tmpfs,重启清零);抓栈留证在 `/var/tmp/rpg-diag/`(持久)。
依赖 `py-spy`(装在 venv:`.venv/bin/py-spy`);没装则跳过抓栈、仍会重启。

调参:所有阈值都能用 `WATCHDOG_*` 环境变量覆盖(见脚本头),或加 systemd drop-in。
`WATCHDOG_DRY_RUN=1` 只记日志不真重启(测试用)。

## 安装(ECS06,一次性)

```bash
# 脚本随 git pull 落到 /opt/rpg-roleplay/ops/(本仓内)
sudo chmod +x /opt/rpg-roleplay/ops/health_watchdog.sh
sudo cp /opt/rpg-roleplay/ops/systemd/rpg-health-watchdog.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rpg-health-watchdog.timer
```

## 验证

```bash
systemctl list-timers rpg-health-watchdog.timer        # 下次触发时间
journalctl -u rpg-health-watchdog --since "5 min ago"  # 自愈日志(健康时安静无输出)
```
