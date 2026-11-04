"""问题反馈队列：/report 排队、/solve 处理、/check_report 查询。"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from .store import JsonStore, coerce_int

# 提醒和 /cr 最多列多少条：内容最长 200 字，再多一条 QQ 消息就装不下了
DIGEST_LIMIT = 10
HISTORY_LIMIT = 5
# /report 全体成员可用，内容长度和每人同时挂着的数量都得有个头，不然一个人就能把队列刷满。
# /solve 的回复同样按这个长度封顶
MAX_REPORT_LEN = 200
MAX_OPEN_PER_USER = 3


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())


class ReportBook:
    """按群保存报告，一个群一条列表，列表顺序就是排队顺序。

    ponytail: 已解决的报告永久留作历史，整份 JSON 每次全量重写；单群攒到上万条再考虑归档。

    编号 = 提交时前方未解决数 + 1。这个号要是正被另一个未解决的报告占着
    （管理员没按顺序处理时会出现），就往后顺延到空号——未解决的报告之间
    编号必须唯一，否则 ``/solve <编号>`` 不知道指的是哪一个。已解决的号可以再发。
    """

    def __init__(self, store: JsonStore):
        self.store = store

    def _items(self, group_id: str) -> List[Dict[str, Any]]:
        bucket = self.store.get(str(group_id))
        items = bucket.get("reports") if isinstance(bucket, dict) else None
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def open_reports(self, group_id: str) -> List[Dict[str, Any]]:
        return [item for item in self._items(group_id) if not item.get("solved")]

    def groups_with_open(self) -> List[str]:
        return [
            str(group_id)
            for group_id in list(self.store.keys())
            if str(group_id).isdigit() and self.open_reports(group_id)
        ]

    def user_reports(self, group_id: str, user_id: str) -> List[Dict[str, Any]]:
        return [item for item in self._items(group_id) if item.get("user_id") == str(user_id)]

    def ahead(self, group_id: str, report: Dict[str, Any]) -> int:
        """排在 ``report`` 前面、还没解决的报告数。"""
        count = 0
        for item in self._items(group_id):
            if item is report:
                return count
            if not item.get("solved"):
                count += 1
        return count

    async def add(self, group_id: str, user_id: str, content: str) -> Tuple[Dict[str, Any], int]:
        """登记一条报告，返回 ``(报告, 前方未解决数)``。"""
        bucket = self.store.group(str(group_id))
        items = bucket.get("reports")
        if not isinstance(items, list):
            items = bucket["reports"] = []

        waiting = self.open_reports(group_id)
        taken = {coerce_int(item.get("no"), -1) for item in waiting}
        number = len(waiting) + 1
        while number in taken:
            number += 1

        report = {
            "no": number,
            "user_id": str(user_id),
            "content": content,
            "time": int(time.time()),
            "solved": False,
        }
        items.append(report)
        await self.store.save()
        return report, len(waiting)

    async def solve(
        self, group_id: str, number: int, reply: str, solver: str
    ) -> Optional[Dict[str, Any]]:
        """把编号为 ``number`` 的未解决报告标成已解决，找不到返回 None。"""
        for item in self.open_reports(group_id):
            # reports.json 被手改成 "no": "3" 也得认
            if coerce_int(item.get("no"), -1) == number:
                item.update(
                    solved=True, reply=reply, solver=str(solver), solved_at=int(time.time())
                )
                await self.store.save()
                return item
        return None


def remind_targets(members: List[Dict[str, Any]], configured: List[str], bot_id: str) -> List[str]:
    """定时提醒要 @ 谁。

    配置了 QQ 号就 @ 其中在本群的人；一个都不在本群（机器人在多个群时很常见）
    或者没配置，就 @ 全体群主和管理员。机器人自己不 @。
    """
    present = {str(m.get("user_id")) for m in members}
    picked = [uid for uid in configured if uid.isdigit() and (not present or uid in present)]
    if picked:
        return list(dict.fromkeys(picked))
    return [
        str(m.get("user_id"))
        for m in members
        if m.get("role") in ("owner", "admin") and str(m.get("user_id")) != str(bot_id)
    ]


def digest_text(book: ReportBook, group_id: str) -> str:
    """未解决报告一览，定时提醒和不带参数的 /solve 共用。"""
    waiting = book.open_reports(group_id)
    if not waiting:
        return "本群目前没有未解决的问题"

    lines = [f"本群当前还有 {len(waiting)} 个问题未解决："]
    for item in waiting[:DIGEST_LIMIT]:
        when = time.strftime("%m-%d %H:%M", time.localtime(coerce_int(item.get("time"), 0)))
        lines.append(
            f"{item.get('no')}  |  QQ:{item.get('user_id')}  |  {when}  |  "
            f"{_one_line(item.get('content'))}"
        )
    if len(waiting) > DIGEST_LIMIT:
        lines.append(f"……其余 {len(waiting) - DIGEST_LIMIT} 个未列出")
    return "\n".join(lines)


def status_text(book: ReportBook, group_id: str, user_id: str) -> str:
    """/check_report 的回复：最近一次报告的进度 + 历史报告。"""
    mine = book.user_reports(group_id, user_id)
    if not mine:
        return "您在本群还没有提交过报告，发送 /report <内容> 即可提交"

    latest = mine[-1]
    lines = [f"您最近的报告信息为{_one_line(latest.get('content'))} 报告编号为{latest.get('no')}"]
    if latest.get("solved"):
        lines.append("您的问题已经得到了解决 感谢您的支持！")
    else:
        lines.append(
            f"您的问题尚未得到解决 前方还有 {book.ahead(group_id, latest)} 个问题等待解决 "
            "请您耐心等待 感谢配合！"
        )

    lines.append("您的历史报告内容为：")
    if len(mine) > HISTORY_LIMIT:
        lines.append(f"（共 {len(mine)} 条，只显示最近 {HISTORY_LIMIT} 条）")
    for item in mine[-HISTORY_LIMIT:]:
        head = f"{item.get('no')}  |  {_one_line(item.get('content'))}"
        if item.get("solved"):
            lines.append(f"{head}  |  已解决  |  回复的内容↓")
            lines.append(str(item.get("reply") or ""))
        else:
            lines.append(f"{head}  |  未解决")
    return "\n".join(lines)
