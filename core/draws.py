"""抽奖：/draw 发起、/join_draw 参与、/draw_cancel 取消，到点由后台开奖。"""
from __future__ import annotations

import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .store import JsonStore, coerce_int

MAX_DRAWS = 5
MAX_HOURS = 99999
MAX_NAME_LEN = 30
# 一条消息 @ 太多人容易发不出去，中奖的人多就分几条
WINNERS_PER_MESSAGE = 20
# 开奖失败后隔 1、2、4……分钟重试，第 13 次失败（约 68 小时后）放弃：
# 全体禁言或 QQ 掉线可能持续一两天，但回执丢失时也不能每分钟 @ 一遍中奖者
MAX_ATTEMPTS = 13
DEFAULT_CLAIM_TIP = "请以上中奖者尽快联系管理员领奖"

USAGE = (
    "用法: /draw <抽奖名> <中奖人数> <时间> <是否强制群成员抽奖> [最大参与人数]\n"
    f"<时间> 单位为小时，最大 {MAX_HOURS}\n"
    "<是否强制群成员抽奖> true 全体成员自动参与；false 成员发送 /jd <抽奖名> 参与\n"
    "[最大参与人数] 选填，不填不限人数\n"
    "例: /draw 周末福利 3 24 false 100"
)


def _positive_int(text: str) -> Optional[int]:
    # 限制位数：几千位的数字 int() 会直接抛 ValueError
    return int(text) if text.isdecimal() and len(text) <= 9 and int(text) > 0 else None


def parse_draw_args(args: List[str]) -> Tuple[Optional[Dict[str, Any]], str]:
    """校验 /draw 的参数，返回 ``(抽奖字段, 错误提示)``。"""
    if len(args) not in (4, 5):
        return None, USAGE

    name, winners, hours, forced = args[:4]
    if len(name) > MAX_NAME_LEN:
        return None, f"抽奖名最长 {MAX_NAME_LEN} 字"
    winner_count = _positive_int(winners)
    if winner_count is None:
        return None, "<中奖人数> 必须是正整数"
    if not re.fullmatch(r"\d+(\.\d+)?", hours) or not 0 < float(hours) <= MAX_HOURS:
        return None, f"<时间> 单位为小时，须大于 0 且不超过 {MAX_HOURS}"
    if forced.lower() not in ("true", "false"):
        return None, "<是否强制群成员抽奖> 只能填写 true 或 false"

    is_forced = forced.lower() == "true"
    limit = 0
    if len(args) == 5:
        limit = _positive_int(args[4])
        if limit is None:
            return None, "[最大参与人数] 必须是正整数"
        if is_forced:
            # 从全体成员里随机圈 limit 人再抽，和直接抽等价，只是中奖人数不能超过 limit
            winner_count, limit = min(winner_count, limit), 0

    return {
        "name": name,
        "winner_count": winner_count,
        "hours": float(hours),
        "forced": is_forced,
        "limit": limit,
    }, ""


def _people(draw: Dict[str, Any]) -> List[str]:
    """报名名单。手改过的 draws.json 里可能是数字甚至不是列表，统一整理好写回去。"""
    people = draw.get("participants")
    people = list(dict.fromkeys(str(uid) for uid in people)) if isinstance(people, list) else []
    draw["participants"] = people
    return people


def _is_ended(draw: Dict[str, Any], now: float) -> bool:
    # 时间被手改坏的不算到点：宁可等管理员取消，也不能立刻开奖删记录
    return 0 < coerce_int(draw.get("ends_at"), 0) <= now


class DrawBook:
    """按群保存进行中的抽奖：``{群号: {抽奖名: 抽奖}}``，开奖或取消后即删除。"""

    def __init__(self, store: JsonStore):
        self.store = store

    def draws(self, group_id: str) -> Dict[str, Dict[str, Any]]:
        bucket = self.store.get(str(group_id))
        if not isinstance(bucket, dict):
            return {}
        return {name: draw for name, draw in bucket.items() if isinstance(draw, dict)}

    def get(self, group_id: str, name: str) -> Optional[Dict[str, Any]]:
        return self.draws(group_id).get(name)

    def total(self) -> int:
        """所有群进行中的抽奖数，上限按这个算。"""
        return sum(
            len(self.draws(group_id))
            for group_id in list(self.store.keys())
            if str(group_id).isdigit()
        )

    def due(self, now: float) -> List[Tuple[str, str, Dict[str, Any]]]:
        """到点待开奖的抽奖，上次失败的要等到重试时间。"""
        return [
            (str(group_id), name, draw)
            for group_id in list(self.store.keys())
            if str(group_id).isdigit()
            for name, draw in self.draws(group_id).items()
            if _is_ended(draw, now) and coerce_int(draw.get("retry_at"), 0) <= now
        ]

    async def add(self, group_id: str, fields: Dict[str, Any], self_id: str = "") -> Dict[str, Any]:
        draw = {
            "self_id": str(self_id),
            "winner_count": fields["winner_count"],
            "forced": fields["forced"],
            "limit": fields["limit"],
            "ends_at": int(time.time() + fields["hours"] * 3600),
            "participants": [],
        }
        self.store.group(str(group_id))[fields["name"]] = draw
        await self.store.save()
        return draw

    async def remove(self, group_id: str, name: str) -> bool:
        bucket = self.store.get(str(group_id))
        if not isinstance(bucket, dict) or name not in bucket:
            return False
        del bucket[name]
        await self.store.save()
        return True

    def retry_later(self, draw: Dict[str, Any], now: float) -> bool:
        """记一次开奖失败并排好下次重试，次数用完返回 False。"""
        attempts = max(0, coerce_int(draw.get("attempts"), 0)) + 1
        draw["attempts"] = attempts
        if attempts >= MAX_ATTEMPTS:
            return False
        draw["retry_at"] = int(now + 60 * 2 ** max(0, attempts - 1))
        return True

    async def join(self, group_id: str, name: str, user_id: str) -> str:
        """登记参与，返回给成员看的回复。"""
        draw = self.get(group_id, name)
        if draw is None:
            # 不回显抽奖名：全体成员可用，别让人借机器人的嘴说话
            return "没有这个抽奖\n\n" + list_text(self, group_id)
        if draw.get("forced"):
            return f"抽奖「{name}」全体成员自动参与，无需报名"
        if _is_ended(draw, time.time()):
            return f"抽奖「{name}」已截止，正在等待开奖"

        people = _people(draw)
        if str(user_id) in people:
            return f"您已参与抽奖「{name}」，当前共 {len(people)} 人参与"
        limit = coerce_int(draw.get("limit"), 0)
        if limit > 0 and len(people) >= limit:
            return f"抽奖「{name}」参与人数已满（{limit} 人）"

        people.append(str(user_id))
        await self.store.save()
        return f"已参与抽奖「{name}」，当前共 {len(people)} 人参与"

    async def drop_member(self, group_id: str, user_id: str) -> None:
        """成员退群后移出还没开奖的抽奖，空出的名额别人可以补上。"""
        uid = str(user_id)
        changed = False
        for draw in self.draws(group_id).values():
            people = _people(draw)
            if uid in people:
                people.remove(uid)
                changed = True
            # 名单里只剩还没通报的人，退群的直接去掉
            winners = draw.get("winners")
            if isinstance(winners, list) and uid in winners:
                winners.remove(uid)
                changed = True
                # 一个不剩又什么都没公布过，下一轮重抽，别公布无人中奖
                if not winners and not draw.get("announced"):
                    del draw["winners"]
        if changed:
            await self.store.save()


def pick_winners(draw: Dict[str, Any], members: List[Dict[str, Any]], bot_id: str) -> List[str]:
    """随机抽中奖者：强制抽奖从当前全体成员里抽，否则从报名且还在群里的人里抽。"""
    present = {str(m.get("user_id")) for m in members if m.get("user_id")} - {str(bot_id)}
    pool = present if draw.get("forced") else present.intersection(_people(draw))
    count = min(max(1, coerce_int(draw.get("winner_count"), 1)), len(pool))
    return random.SystemRandom().sample(list(pool), count)


def next_message(
    name: str, draw: Dict[str, Any], tip: str
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """下一条开奖消息和它通报的人。

    ``winners`` 只留还没通报的人，``announced`` 记已通报几个：重试和退群都不用管发到第几条。
    用消息段：抽奖名是人写的，不能被当成 CQ 码执行。
    """

    def text(value: str) -> Dict[str, Any]:
        return {"type": "text", "data": {"text": value}}

    pending = [str(uid) for uid in draw.get("winners") or []]
    announced = max(0, coerce_int(draw.get("announced"), 0))
    if not pending and not announced:
        return [text(f"抽奖「{name}」已结束，没有符合条件的参与者，本次无人中奖")], []

    total = announced + len(pending)
    chunk = pending[:WINNERS_PER_MESSAGE]
    segments = [] if announced else [text(f"抽奖「{name}」开奖，共 {total} 人中奖：\n")]
    for uid in chunk:
        segments.append({"type": "at", "data": {"qq": uid}})
        segments.append(text(f"（QQ:{uid}）\n"))
    if len(chunk) == len(pending):
        segments.append(text(tip.replace("{name}", name).replace("{count}", str(total))))
    return segments, chunk


def end_text(draw: Dict[str, Any]) -> str:
    """开奖时间。99999 小时已过 2038 年，32 位系统上 localtime 会溢出。"""
    ends_at = coerce_int(draw.get("ends_at"), 0)
    try:
        if ends_at > 0:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(ends_at))
    except (OverflowError, OSError, ValueError):
        pass
    return "时间异常"


def _draw_line(name: str, draw: Dict[str, Any]) -> str:
    if draw.get("forced"):
        joined = "全体成员自动参与"
    else:
        limit = coerce_int(draw.get("limit"), 0)
        joined = f"已参与 {len(_people(draw))}" + (f"/{limit} 人" if limit > 0 else " 人")
    return f"{name}  |  中奖 {draw.get('winner_count')} 人  |  {end_text(draw)} 开奖  |  {joined}"


def list_text(book: DrawBook, group_id: str) -> str:
    """本群进行中的抽奖一览。"""
    draws = book.draws(group_id)
    if not draws:
        return f"本群当前没有进行中的抽奖（所有群合计 {book.total()}/{MAX_DRAWS}）"

    lines = [f"本群进行中的抽奖（所有群合计 {book.total()}/{MAX_DRAWS}）："]
    lines.extend(_draw_line(name, draw) for name, draw in draws.items())
    return "\n".join(lines)


def all_text(book: DrawBook) -> str:
    """所有群的抽奖一览，给 AstrBot 管理员释放名额用。"""
    lines = [f"所有群进行中的抽奖（{book.total()}/{MAX_DRAWS}）："]
    for group_id in list(book.store.keys()):
        if str(group_id).isdigit():
            lines.extend(
                f"群 {group_id}  |  {_draw_line(name, draw)}"
                for name, draw in book.draws(group_id).items()
            )
    return "\n".join(lines)
