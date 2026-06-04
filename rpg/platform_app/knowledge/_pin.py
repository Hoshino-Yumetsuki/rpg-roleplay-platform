"""platform_app.knowledge._pin — 剧本「引用/pin」的 KB 读取重定向(单一真相)。

剧本若 sharing_mode 是 pinned-snapshot / floating-latest,它本身没有 KB 数据,
所有【读取】(检索 / GM 的 KB 工具 / 常驻世界书注入 / canon 查询)应重定向到 pin 的
目标剧本。

边界(只做读):
  · KB 读取  → 用 effective_kb_script_id(跟随 pin)。
  · KB 写入(GM 编辑世界书等)+ 存档归属/记录 → 保持原 script_id 不动
    (pinned 引用绝不能写到目标剧本,也不能改存档归属)。

commit_id 精确历史版本回放未做:统一读目标【当前】数据 —— floating-latest 语义正确,
pinned-snapshot 近似(不再读空,但不锁版本)。
"""
from __future__ import annotations


def effective_kb_script_id(db, script_id) -> int:
    """KB 读取的有效 script_id:pinned/floating 引用 → 目标剧本;其余原样。

    db: 已打开的连接(dict_row)。任何异常都退回原 script_id(绝不影响主流程)。
    """
    try:
        sid = int(script_id)
    except (TypeError, ValueError):
        return script_id
    try:
        row = db.execute(
            "select sharing_mode, current_pin_script_id from scripts where id = %s",
            (sid,),
        ).fetchone()
        if (
            row
            and row["sharing_mode"] in ("pinned-snapshot", "floating-latest")
            and row["current_pin_script_id"]
        ):
            return int(row["current_pin_script_id"])
    except Exception:
        pass
    return sid
