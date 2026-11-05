"""OneBot v11 (aiocqhttp) 协议端调用封装。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from astrbot.api import logger


def is_aiocqhttp(event) -> bool:
    """判断事件是否来自 aiocqhttp 协议端。"""
    try:
        return event.get_platform_name() == "aiocqhttp"
    except Exception:
        return False


def get_client(event):
    """取得协议端 client，非 aiocqhttp 返回 None。"""
    if not is_aiocqhttp(event):
        return None
    return getattr(event, "bot", None)


class OneBotApi:
    """把常用群管理动作包装成方法，统一异常与日志。"""

    def __init__(self, event=None, client=None, self_id: Optional[int] = None):
        self.event = event
        # 后台调用要指明账号：同一适配器连着多个账号时，不指明 aiocqhttp 不知道走哪个
        self.route = {"self_id": self_id} if self_id else {}
        # 后台任务（禁言续期、版本检查）手里没有 event，直接拿适配器的 client
        self.client = client if client is not None else get_client(event)

    @property
    def available(self) -> bool:
        return self.client is not None

    async def call(self, action: str, **payload: Any) -> Any:
        """调用协议端 API，失败时抛出 RuntimeError。"""
        if self.client is None:
            raise RuntimeError("当前平台不支持该操作，仅支持 QQ (aiocqhttp)")
        try:
            return await self.client.api.call_action(action, **self.route, **payload)
        except Exception as exc:
            logger.error(f"[ZM-QQGroupmgr] 调用 {action} 失败: {exc}")
            raise RuntimeError(str(exc)) from exc

    async def try_call(self, action: str, **payload: Any) -> Optional[Any]:
        """调用协议端 API，失败返回 None（用于不应中断流程的场景）。

        只适合"要拿返回数据"的动作。判断成败请用 :meth:`try_ok`。
        """
        try:
            return await self.call(action, **payload)
        except RuntimeError:
            return None

    async def try_ok(self, action: str, **payload: Any) -> bool:
        """调用协议端 API，只关心成功与否。

        ``try_call() is not None`` 并不能用来判断成败：``delete_msg``、
        ``_send_group_notice``、``set_group_portrait`` 这类动作成功时
        ``data`` 本来就是 null，和调用失败返回的 None 分不开。
        """
        try:
            await self.call(action, **payload)
            return True
        except RuntimeError:
            return False

    async def mute(self, group_id: int, user_id: int, duration: int) -> None:
        """禁言成员，``duration`` 为 0 表示解除禁言。"""
        await self.call(
            "set_group_ban", group_id=int(group_id), user_id=int(user_id), duration=int(duration)
        )

    async def mute_all(self, group_id: int, enable: bool) -> None:
        """开启或关闭全体禁言。"""
        await self.call("set_group_whole_ban", group_id=int(group_id), enable=bool(enable))

    async def kick(self, group_id: int, user_id: int, reject: bool = False) -> None:
        await self.call(
            "set_group_kick",
            group_id=int(group_id),
            user_id=int(user_id),
            reject_add_request=bool(reject),
        )

    async def recall(self, message_id: Any) -> None:
        await self.call("delete_msg", message_id=message_id)

    async def recall_detail(self, message_id: Any) -> Tuple[bool, str]:
        """撤回单条消息，返回 (是否成功, 失败原因)。"""
        try:
            await self.call("delete_msg", message_id=message_id)
            return True, ""
        except RuntimeError as exc:
            return False, str(exc)

    async def group_msg_history(self, group_id: int, count: int = 20) -> List[Dict[str, Any]]:
        """取群最近的聊天记录（旧 → 新），协议端不支持时返回空列表。

        各协议端对参数的要求不一致，逐个尝试：NapCat / Lagrange 接受
        count；go-cqhttp 需要 message_seq；个别实现只认 group_id。
        """
        attempts = (
            {"group_id": int(group_id), "count": int(count)},
            {"group_id": int(group_id), "message_seq": 0, "count": int(count)},
            {"group_id": int(group_id)},
        )
        for payload in attempts:
            result = await self.try_call("get_group_msg_history", **payload)
            messages: Any = None
            if isinstance(result, dict):
                messages = result.get("messages")
            elif isinstance(result, list):
                messages = result
            if isinstance(messages, list) and messages:
                return messages
        return []

    async def group_detail(self, group_id: int) -> Dict[str, Any]:
        """取群详细信息（含加群方式 addOption），协议端不支持时返回空 dict。"""
        result = await self.try_call("get_group_detail_info", group_id=str(group_id))
        return result if isinstance(result, dict) else {}

    async def group_add_option(self, group_id: int) -> Optional[int]:
        """当前加群方式：4 = 需要正确回答问题，查不到返回 None。

        字段名各版本不一致（NapCat 直接透传 NTQQ 的 addOption），都试一遍。
        """
        detail = await self.group_detail(group_id)
        for key in ("addOption", "add_option", "add_type", "groupAddOption"):
            value = detail.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        return None

    async def set_group_add_option(
        self, group_id: int, add_type: int, question: str = "", answer: str = ""
    ) -> Tuple[bool, str]:
        """设置加群方式，返回 ``(是否成功, 失败原因)``。

        ``add_type=4`` 即「需要正确回答问题」，此时 question / answer 必填。
        这是 NapCat 的扩展接口，其他协议端可能不支持。
        """
        try:
            await self.call(
                "set_group_add_option",
                group_id=str(group_id),
                add_type=int(add_type),
                group_question=question,
                group_answer=answer,
            )
            return True, ""
        except RuntimeError as exc:
            return False, str(exc)

    async def set_admin(self, group_id: int, user_id: int, enable: bool) -> None:
        await self.call(
            "set_group_admin", group_id=int(group_id), user_id=int(user_id), enable=bool(enable)
        )

    async def set_title(self, group_id: int, user_id: int, title: str) -> None:
        await self.call(
            "set_group_special_title",
            group_id=int(group_id),
            user_id=int(user_id),
            special_title=title,
            duration=-1,
        )

    async def set_card(self, group_id: int, user_id: int, card: str) -> None:
        await self.call(
            "set_group_card", group_id=int(group_id), user_id=int(user_id), card=card
        )

    async def set_group_name(self, group_id: int, name: str) -> None:
        await self.call("set_group_name", group_id=int(group_id), group_name=name)

    async def set_group_portrait(
        self, group_id: int, candidates: List[str]
    ) -> Tuple[bool, str]:
        """设置群头像，返回 ``(是否成功, 最后一次失败原因)``。

        ``file`` 字段的写法各协议端支持度不一（base64 / file:// / 本地路径），
        依次试过去，谁能成就用谁。
        """
        last = "协议端未接受任何一种图片写法"
        for candidate in candidates:
            try:
                await self.call(
                    "set_group_portrait", group_id=int(group_id), file=candidate, cache=1
                )
                return True, ""
            except RuntimeError as exc:
                last = str(exc)
        return False, last

    async def send_group_notice(
        self,
        group_id: int,
        content: str,
        image: Optional[str] = None,
        pinned: bool = False,
    ) -> Tuple[bool, str]:
        """发布群公告，返回 ``(是否成功, 附加说明)``。

        ``pinned`` 只有 NapCat 等部分实现支持，协议端拒绝时退回不带置顶的
        调用，公告照发但会在说明里讲清楚没置顶成功。
        """
        payload: Dict[str, Any] = {"group_id": int(group_id), "content": content}
        if image:
            payload["image"] = image

        if pinned:
            if await self.try_ok("_send_group_notice", **payload, pinned=1):
                return True, ""
            if await self.try_ok("_send_group_notice", **payload):
                return True, "当前协议端不支持置顶参数，公告已发布但未置顶"
            return False, ""

        return await self.try_ok("_send_group_notice", **payload), ""

    async def stranger_name(self, user_id: str) -> str:
        """取任意 QQ 的昵称，用于成员已退群、查不到群名片的场景。"""
        info = await self.try_call("get_stranger_info", user_id=int(user_id))
        if isinstance(info, dict):
            return str(info.get("nickname") or user_id)
        return str(user_id)

    async def member_list(self, group_id: int, no_cache: bool = False) -> List[Dict[str, Any]]:
        # 只在需要时才带 no_cache，其余调用的请求内容保持不变
        extra = {"no_cache": True} if no_cache else {}
        result = await self.try_call("get_group_member_list", group_id=int(group_id), **extra)
        return result if isinstance(result, list) else []

    async def member_info(self, group_id: int, user_id: int) -> Dict[str, Any]:
        result = await self.try_call(
            "get_group_member_info", group_id=int(group_id), user_id=int(user_id), no_cache=True
        )
        return result if isinstance(result, dict) else {}

    async def group_list(self) -> List[Dict[str, Any]]:
        result = await self.try_call("get_group_list")
        return result if isinstance(result, list) else []

    async def send_group_msg(self, group_id: int, message: Any) -> Optional[Any]:
        return await self.try_call("send_group_msg", group_id=int(group_id), message=message)

    async def send_forward(
        self,
        group_id: int,
        nodes: List[Dict[str, Any]],
        source: Optional[str] = None,
        summary: Optional[str] = None,
        prompt: Optional[str] = None,
        news: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[Any]:
        """发送合并转发消息。

        source/summary/prompt/news 用于自定义卡片外观（NapCat、Lagrange 等支持）：
        - source: 卡片标题，默认「群聊的聊天记录」
        - news:   卡片中间的摘要行
        - summary: 卡片底部「查看 N 条转发消息」
        - prompt: 会话列表里的外显文本，默认「[聊天记录]」
        协议端若不支持这些字段，会自动退回不带自定义样式的发送。
        """
        extra: Dict[str, Any] = {}
        if source:
            extra["source"] = source
        if news:
            extra["news"] = news
        if summary:
            extra["summary"] = summary
        if prompt:
            extra["prompt"] = prompt

        if extra:
            result = await self.try_call(
                "send_group_forward_msg",
                group_id=int(group_id),
                messages=nodes,
                **extra,
            )
            if result is not None:
                return result

        return await self.try_call(
            "send_group_forward_msg", group_id=int(group_id), messages=nodes
        )


def forward_node(user_id: str, nickname: str, content: str) -> Dict[str, Any]:
    """构造一条合并转发节点。"""
    return {
        "type": "node",
        "data": {
            "uin": str(user_id),
            "name": nickname or str(user_id),
            "content": [{"type": "text", "data": {"text": content}}],
        },
    }


async def resolve_member_name(api: OneBotApi, group_id: int, user_id: str) -> str:
    """尽力取得成员昵称，失败时退回 QQ 号。"""
    info = await api.member_info(group_id, int(user_id))
    return info.get("card") or info.get("nickname") or str(user_id)
