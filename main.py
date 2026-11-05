"""ZM-QQGroupmgr - 功能强大的 QQ 群管理插件

作者: ZM
所有管理命令均限制为 AstrBot 管理员可用。
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import List, Optional

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .core.detector import CardCache, FloodDetector, ad_score
from .core.draws import (
    DEFAULT_CLAIM_TIP,
    MAX_DRAWS,
    USAGE as DRAW_USAGE,
    DrawBook,
    all_text as draw_all_text,
    end_text as draw_end_text,
    list_text as draw_list_text,
    next_message as draw_next_message,
    parse_draw_args,
    pick_winners,
)
from .core.files import FileRepository, format_size
from .core.media import (
    cleanup_temp,
    extract_images,
    file_candidates,
    guess_image_ext,
    image_bytes,
    save_named_image,
    to_base64_uri,
)
from .core.joinapproval import (
    CODE_SHA,
    CODE_TYPE_LABELS,
    CODE_TYPES,
    MAX_POLL_MINUTES,
    MAX_VERIFY_MINUTES,
    VALID_DIGITS,
    ShaCache,
    code_matches,
    is_sha_text,
    latest_release_tag,
    make_code,
    parse_repo,
    version_tuple,
)
from .core.mutes import MuteTracker, chunk_duration
from .core.onebot import OneBotApi, forward_node, resolve_member_name
from .core.pending import PendingRegistry, session_key
from .core.reports import (
    MAX_OPEN_PER_USER,
    MAX_REPORT_LEN,
    ReportBook,
    digest_text,
    remind_targets,
    status_text,
)
from .core.sensitive import (
    MODE_BOTH,
    MODE_CUSTOM,
    MODE_LABELS,
    MODE_LIBRARY,
    VALID_MODES,
    SensitiveWordEngine,
)
from .core.server import DownloadServer
from .core.store import (
    GroupToggle,
    JsonStore,
    backup_on_upgrade,
    coerce_int,
    coerce_str_list,
    get_data_dir,
)
from .core.utils import (
    MAX_DURATION,
    MUTE_CHUNK,
    escape_cq,
    extract_targets,
    is_target_token,
    format_duration,
    parse_duration,
    parse_group_ids,
    render_cq,
    split_trailing_bool,
    split_trailing_group_ids,
    truncate,
)

PLUGIN_NAME = "ZM-QQGroupmgr"
PLUGIN_VERSION = "1.0.8"

# 版本检查与更新提示指向的仓库
PLUGIN_REPO = "ZomebieMask/astrbot_plugin_zm_qqgroupmgr"
PLUGIN_MARKET_URL = (
    "https://cloud.astrbot.app/plugin/ZomebieMask/astrbot_plugin_zm_qqgroupmgr"
)
UPDATE_CARD_TITLE = "ZM_QQGroupmgr New-Update-Available!!!"

# GitHub 未认证 API 每小时只有 60 次，默认半小时查一次足够
DEFAULT_POLL_MINUTES = 30
# 入群验证时成员发来的 sha 对不上，最多这么频繁地去 GitHub 复核一次
SHA_RECHECK_TTL = 60
# 同一个人连错这么多次 sha 就直接踢，别让他把 GitHub 配额刷光
MAX_SHA_TRIES = 5
DEFAULT_MUTE_REASON = "管理员手动禁言"

ADMIN_ONLY = "此命令仅群聊可用"
QQ_ONLY = "此功能仅支持 QQ (aiocqhttp) 平台"
REPORT_HANDLER_ONLY = "{command} 仅 AstrBot 管理员、群主、群管理员及插件配置 report_solve_users 中的成员可用"

# /file 的写操作仅管理员可用；download/list/log 查看对全体成员开放。
ADMIN_FILE_ACTIONS = {"upload", "delete", "del", "rm"}

# /file 子命令缩写，例如 /f dl == /file download、/f l == /file log
FILE_ACTION_ALIASES = {
    "dl": "download",
    "down": "download",
    "up": "upload",
    "ls": "list",
    "l": "log",
}

# /file log update 的缩写：/f l up <name> <version> <内容>
LOG_UPDATE_KEYWORDS = {"update", "up"}

# /file download cdreset：重置成员的下载冷却
CD_RESET_KEYWORDS = {"cdreset", "cdrs", "resetcd"}

DEFAULT_PRIVATE_ONLY_TIP = "需要私聊才可以下载"

# /group 子命令缩写，例如 /g nn == /group newname、/g avatar == /group pp
GROUP_ACTION_ALIASES = {
    "nn": "newname",
    "name": "newname",
    "rename": "newname",
    "群名": "newname",
    "avatar": "pp",
    "icon": "pp",
    "portrait": "pp",
    "头像": "pp",
}

# 一次最多改多少个群，兼作误操作与刷接口的兜底
MAX_BATCH_GROUPS = 20

# QQ 群名上限约 30 字，留点余量后仍超长的直接挡下来
MAX_GROUP_NAME = 45

# 批量改头像时的间隔，太快容易被协议端限流
BATCH_INTERVAL = 0.5

GROUP_USAGE = (
    "群资料管理（/group 可简写为 /g）\n"
    "/group newname <文本> [qq群号]   修改群名称（缩写 /g nn）\n"
    "/group pp [图片] [qq群号]        修改群头像（缩写 /g avatar）\n"
    "\n"
    "[qq群号] 省略时作用于当前群；用 - 连接可批量操作:\n"
    "  /g pp 3366-1009-10032   给这三个群换同一张头像\n"
    "/g pp 未带图片时，机器人会等你在 1 分钟内补发图片\n"
    "群名本身以数字结尾时请加引号: /g newname \"某某群 2025\" 12345678\n"
    f"单次最多 {MAX_BATCH_GROUPS} 个群；机器人需为目标群的群主或管理员"
)

BROADCAST_USAGE = (
    "发布群公告（/broadcast 可简写为 /bc）\n"
    "/broadcast <内容> <是否置顶公告>\n"
    "  <是否置顶公告> 只能填 true 或 false\n"
    "例: /bc 本周六停服维护 true\n"
    "内容里可以直接插入图片（电脑端粘贴即可）；\n"
    "只发了文字的话，机器人会再问一次要不要补图片"
)

FAREWELL_USAGE = (
    "退群提示（/bye）\n"
    "/bye                 预览当前设置\n"
    "/bye set <文本>       设置提示内容\n"
    "/bye image           设置附带图片（随后 1 分钟内发送图片）\n"
    "/bye image clear     清除附带图片\n"
    "/bye on | off        开启 / 关闭退群提示\n"
    "/bye reset           恢复默认内容并开启\n"
    "/bye status          查看当前状态\n"
    "占位符: {at} {name} {user_id} {group_id} {reason} {operator}"
)

DEFAULT_FAREWELL = "{name}（{user_id}）{reason}，本群还剩下我们这些人。"

JOIN_APPROVAL_USAGE = (
    "进群审批（/join_approval 可简写为 /ja）\n"
    "/ja set verification_code <number|letter|mix|sha>\n"
    "    入群后二次验证：机器人发验证码，成员限时回发，超时踢出\n"
    "    number 数字 / letter 6 位字母 / mix 数字+字母 / sha GitHub 最新 commit\n"
    "    缩写: /ja set vc number\n"
    "/ja set static <内容>    把 <内容> 设为本群「回答正确问题」的答案\n"
    "/ja set dynamic          把 GitHub 最新 commit 的 sha 设为答案，定时刷新\n"
    "/ja off                  关闭本群进群审批\n"
    "/ja status               查看当前设置\n"
    "static / dynamic 需要本群加群方式为「需要正确回答问题」，"
    "不是的话机器人会先问你要不要改"
)

# /ja set verification_code 的缩写
JOIN_CODE_KEYWORDS = {"verification_code", "vc", "code", "验证码"}

# 加群方式：4 = 需要正确回答问题（答对即入群）
ADD_OPTION_ANSWER = 4

DEFAULT_JOIN_QUESTION = "请输入管理员提供的验证内容"
DEFAULT_JOIN_DECLINE_TIP = "收到 :)"
DEFAULT_JOIN_VERIFY_TIP = (
    "{at} 欢迎加入！请在 {minutes} 分钟内发送验证码完成验证，否则将被移出本群\n"
    "验证码: {code}"
)
DEFAULT_JOIN_SHA_TIP = (
    "{at} 欢迎加入！请在 {minutes} 分钟内发送 {repo} 最新 commit 的 sha 值"
    "（前 7 位即可）完成验证，否则将被移出本群"
)
DEFAULT_JOIN_PASS_TIP = "{at} 验证通过，欢迎 :)"
DEFAULT_JOIN_TIMEOUT_TIP = "{name}（{user_id}）未在 {minutes} 分钟内完成验证，已移出本群"
DEFAULT_UPDATE_TIP = (
    "zm_qqgroupmgr插件有新的版本可更新!\n" + PLUGIN_MARKET_URL
)

YES_WORDS = {"是", "yes", "y", "要", "需要", "有", "1", "true", "好", "嗯"}
NO_WORDS = {"否", "no", "n", "不", "不要", "不需要", "没有", "0", "false", "算了"}

_MASK_48 = (1 << 48) - 1
_JAVA_MULTIPLIER = 0x5DEECE66D


def _find_slime_chunks(seed: int, search_range: int) -> List[tuple]:
    """按 Java 版算法在 ±search_range 区块内查找史莱姆区块。"""
    found = []
    for x in range(-search_range, search_range):
        for z in range(-search_range, search_range):
            chunk_seed = (
                seed
                + x * x * 0x4C1906
                + x * 0x5AC0DB
                + z * z * 0x4307A7
                + z * 0x5F24F
            ) ^ 0x3AD8025F
            state = (chunk_seed ^ _JAVA_MULTIPLIER) & _MASK_48
            # java.util.Random.nextInt(10)
            for _ in range(2):
                state = (state * _JAVA_MULTIPLIER + 0xB) & _MASK_48
                candidate = state >> 17
                if candidate - (candidate % 10) + 9 <= _MASK_48 >> 17:
                    break
            if candidate % 10 == 0:
                found.append((x, z))
    return found


@register("astrbot_plugin_zm_qqgroupmgr", "ZM", "功能全面的 QQ 群管理插件", PLUGIN_VERSION,
          "https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr")
class ZMQQGroupmgr(Star):
    """群管理插件主体。"""

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}

        self.settings = JsonStore("settings.json")
        self.words_store = JsonStore("sensitive_words.json")
        self.mutes_store = JsonStore("mutes.json")
        self.files_store = JsonStore("files.json")
        self.reports_store = JsonStore("reports.json")
        self.draws_store = JsonStore("draws.json")

        self.sensitive = SensitiveWordEngine(self.words_store, self.config)
        self.mutes = MuteTracker(self.mutes_store)
        self.files = FileRepository(self.files_store, self.config)
        self.cards = CardCache()
        self.reports = ReportBook(self.reports_store)
        self.draws = DrawBook(self.draws_store)

        self.flood = FloodDetector(
            threshold=coerce_int(self.config.get("flood_threshold"), 5),
            window=coerce_int(self.config.get("flood_window"), 10),
            repeat_limit=coerce_int(self.config.get("flood_repeat_limit"), 3),
        )

        self.flood_toggle = GroupToggle(self.settings, "flood")
        self.sw_toggle = GroupToggle(self.settings, "sensitive")
        self.adban_toggle = GroupToggle(self.settings, "adban")
        self.card_toggle = GroupToggle(self.settings, "card")

        self.server: Optional[DownloadServer] = None
        self._pending_upload = {}
        # /group pp、/broadcast、/bye image 的两步交互状态
        self._pending_media = PendingRegistry(
            ttl=coerce_int(self.config.get("media_wait_timeout"), 60)
        )
        self._message_history = {}
        self._max_history = 200
        # 持有后台任务引用，否则可能被 GC 掉导致定时解除全体禁言失效
        self._tasks: set = set()

        self._sha_cache = ShaCache()
        # 待验证的新成员：(群号, QQ号) -> {code, is_sha, deadline}
        # 只放内存：重载后没人还记得当初发的验证码，留着也没意义
        self._pending_verify: dict = {}
        # 正在发开奖消息的抽奖，这期间 /draw_cancel 不能再答应取消
        self._announcing: Optional[dict] = None
        # 已提示过未连接的账号，免得每分钟记一条日志
        self._draw_offline: set = set()

    async def initialize(self):
        """插件加载后启动文件下载服务。"""
        made = backup_on_upgrade(PLUGIN_VERSION)
        if made:
            logger.info(f"[ZM-QQGroupmgr] 升级前数据已备份到 {made}")

        if self.config.get("file_server_enabled", True):
            # 强制使用 0.0.0.0 以避免云服务器绑定问题
            configured_host = str(self.config.get("file_host") or "0.0.0.0")
            # 云服务器无法直接绑定公网IP，强制使用 0.0.0.0
            if configured_host not in ("0.0.0.0", "127.0.0.1", "localhost"):
                logger.warning(f"[ZM-QQGroupmgr] 检测到公网IP配置 {configured_host}，自动改为 0.0.0.0")
                configured_host = "0.0.0.0"

            port = coerce_int(self.config.get("file_port"), 9977)

            self.server = DownloadServer(self.files, host=configured_host, port=port)
            error = await self.server.start()

            # 如果仍然失败，最后尝试回退到 0.0.0.0
            if error and "could not bind" in str(error) and configured_host != "0.0.0.0":
                logger.warning(f"[ZM-QQGroupmgr] 配置的地址 {configured_host} 不可用，尝试使用 0.0.0.0")
                self.server = DownloadServer(self.files, host="0.0.0.0", port=port)
                error = await self.server.start()

            if error:
                logger.warning(f"[ZM-QQGroupmgr] {error}")

            # 0.0.0.0 只是监听地址，直接写进下载链接的话谁都打不开
            if "0.0.0.0" in self.files.base_url():
                logger.warning(
                    "[ZM-QQGroupmgr] 下载链接当前会生成 http://0.0.0.0:%s，外部无法访问；"
                    "请在插件配置 file_base_url 填写实际可访问的地址（如 http://公网IP:%s）"
                    % (port, port)
                )
        self._spawn(self._ticker())
        logger.info(f"[{PLUGIN_NAME}] 插件已加载 v{PLUGIN_VERSION}")

    def _spawn(self, coro) -> None:
        """启动后台任务并持有引用，直到它自己结束。"""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def terminate(self):
        """插件卸载时释放端口并落盘。"""
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        self._pending_media.clear()
        if self.server is not None:
            await self.server.stop()
            self.server = None
        for store in (
            self.settings,
            self.words_store,
            self.mutes_store,
            self.files_store,
            self.reports_store,
            self.draws_store,
        ):
            await store.save()
        logger.info("[ZM-QQGroupmgr] 插件已卸载")

    # ------------------------------------------------------------------
    # 通用辅助
    # ------------------------------------------------------------------

    def _render(self, template: str, event: AstrMessageEvent, escape: bool = True, **extra) -> str:
        """渲染提示语模板中的占位符。

        除 ``{at}``（由插件自己生成的 CQ 码）外，填入的值都会转义 ``[`` ``]``：
        昵称、群名片、敏感词等都是成员可控内容，不转义就能靠
        ``[CQ:at,qq=all]`` 之类的写法借机器人之口执行 CQ 码。
        设置头衔等"值不会进入消息"的场景可传 ``escape=False``。
        """
        values = {
            "name": event.get_sender_name() or str(event.get_sender_id()),
            "user_id": str(event.get_sender_id()),
            "group_id": str(event.get_group_id() or ""),
        }
        values.update({k: str(v) for k, v in extra.items()})
        if escape:
            values = {k: escape_cq(v) for k, v in values.items()}
        values["at"] = f"[CQ:at,qq={event.get_sender_id()}]"

        text = template or ""
        for key, value in values.items():
            text = text.replace("{" + key + "}", value)
        return text

    def _require_group(self, event: AstrMessageEvent) -> Optional[str]:
        group_id = event.get_group_id()
        return str(group_id) if group_id else None

    def _raw_after(self, event: AstrMessageEvent, *names: str) -> str:
        """去掉开头的命令名（含 / 等唤醒前缀），返回剩余原始文本。

        只比对消息的第一个 token，不做全文搜索——否则命令名出现在参数里时
        会把参数截断（例如 /f dl myfile 中的 "file"），别名也会失效
        （/af on 里根本没有 "antiflood"）。首个 token 不是命令名时，说明框架
        已经剥掉了命令头，原样返回。
        """
        text = (event.message_str or "").strip()
        if not text:
            return ""

        parts = text.split(None, 1)
        head = parts[0].lstrip("/!#！＃").lower()
        if head in {name.lower() for name in names}:
            return parts[1].strip() if len(parts) > 1 else ""
        return text

    def _args(self, event: AstrMessageEvent, *names: str) -> List[str]:
        """同 :meth:`_raw_after`，但按空白切分成参数列表。"""
        return self._raw_after(event, *names).split()

    def _record_message(self, event: AstrMessageEvent) -> None:
        group_id = self._require_group(event)
        if not group_id:
            return
        history = self._message_history.setdefault(group_id, [])
        history.append(
            {
                "message_id": event.message_obj.message_id,
                "user_id": str(event.get_sender_id()),
                "timestamp": time.time(),
                "content": event.message_str,
            }
        )
        if len(history) > self._max_history:
            del history[: -self._max_history]

    async def _punish(
        self,
        event: AstrMessageEvent,
        api: OneBotApi,
        group_id: str,
        user_id: str,
        duration: int,
        reason: str,
        recall: bool,
    ) -> None:
        """撤回 + 禁言的组合处理，用于自动检测场景。"""
        if recall:
            await api.try_call("delete_msg", message_id=event.message_obj.message_id)
        if duration > 0:
            try:
                await api.mute(int(group_id), int(user_id), chunk_duration(duration))
                await self.mutes.record(group_id, user_id, duration, reason, "自动检测")
            except RuntimeError as exc:
                logger.warning(f"[ZM-QQGroupmgr] 自动禁言失败: {exc}")

    async def _bot_role(self, api: OneBotApi, group_id: str, event: AstrMessageEvent) -> str:
        """机器人在该群的身份：owner / admin / member。"""
        bot_id = str(event.get_self_id() or "")
        if not api.available or not group_id or not bot_id:
            return "member"
        info = await api.member_info(int(group_id), int(bot_id))
        return str(info.get("role") or "member")

    @staticmethod
    def _looks_like_command(event: AstrMessageEvent) -> bool:
        """尽力判断这条消息是不是一次指令调用。

        用于两步交互等待期间放行其他指令：管理员重新执行 ``/g pp [图片] 222``
        时，等待中的旧登记不能把它当成"补发的图片"抢走。``message_str`` 里
        的唤醒前缀不一定还在，所以顺带看一眼原始的 Plain 组件。
        """
        texts = [(event.message_str or "").lstrip()]
        for component in getattr(event.message_obj, "message", None) or []:
            if type(component).__name__ == "Plain":
                texts.append((getattr(component, "text", "") or "").lstrip())
                break
        return any(text[:1] in "/!#！＃" for text in texts if text)

    def _media_timeout(self) -> int:
        """等待补发图片 / 确认答复的秒数。"""
        return max(10, coerce_int(self.config.get("media_wait_timeout"), 60))

    async def _notify(self, origin: str, text: str) -> None:
        """在指令的原会话里主动发一条消息（超时提醒等场景）。"""
        if not origin:
            return
        try:
            from astrbot.api.event import MessageChain

            await self.context.send_message(origin, MessageChain().message(text))
        except Exception as exc:
            logger.warning(f"[ZM-QQGroupmgr] 主动发送消息失败: {exc}")

    async def _expire_pending(
        self, origin: str, key: str, token: str, delay: int, label: str
    ) -> None:
        """到点仍没等到图片 / 答复时作废这次登记并告知管理员。

        用 token 校验是为了只作废"自己那一次"：管理员在等待期内重新执行了
        指令的话，旧任务醒来不能把新登记一起清掉。
        """
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if not self._pending_media.drop_if(key, token):
            return
        await self._notify(
            origin, f"{label}：超过 {format_duration(delay)} 未收到内容，指令已失效，执行失败"
        )

    def _arm_pending(self, event: AstrMessageEvent, label: str, **payload) -> int:
        """登记一次待续交互并挂上超时任务，返回等待秒数。"""
        timeout = self._media_timeout()
        key = session_key(event)
        token = self._pending_media.put(key, origin=event.unified_msg_origin, **payload)
        self._spawn(
            self._expire_pending(event.unified_msg_origin, key, token, timeout, label)
        )
        return timeout

    async def _recall_media(
        self,
        event: AstrMessageEvent,
        api: OneBotApi,
        message_id,
        config_key: str,
    ) -> str:
        """按开关撤回携带图片的那条消息，返回给管理员看的说明。

        撤回自己发的消息谁都能做，撤回别人的要群主或管理员，所以先看身份，
        免得白白发一次注定失败的请求。
        """
        if not self.config.get(config_key, True):
            return ""
        group_id = self._require_group(event)
        if not group_id or not message_id or not api.available:
            return ""

        role = await self._bot_role(api, group_id, event)
        if role not in {"owner", "admin"}:
            return "机器人不是群主或管理员，图片消息未撤回"
        if not await api.try_ok("delete_msg", message_id=message_id):
            return "撤回图片消息失败，请手动删除"
        return "已撤回图片消息"

    async def _prepare_image(self, component, with_file: bool = True) -> tuple:
        """把图片组件转成 ``(候选 file 列表, 原始字节, 临时文件, 错误)``。

        ``with_file=False`` 时只给 base64，不落临时文件——群公告接口只吃
        base64，没必要为它白写一次磁盘。
        """
        data, error = await image_bytes(component)
        if error or not data:
            return [], b"", None, error or "未能读取图片内容"

        ext = guess_image_ext(data)
        if ext is None:
            return [], b"", None, "无法识别的图片格式，仅支持 jpg / png / gif / bmp / webp"

        if not with_file:
            return [to_base64_uri(data)], data, None, ""

        candidates, temp = file_candidates(data, ext)
        return candidates, data, temp, ""

    def _resolve_group_targets(
        self, event: AstrMessageEvent, ids: Optional[List[str]]
    ) -> tuple:
        """确定要操作哪些群，返回 ``(群号列表, 错误说明)``。"""
        if ids:
            if len(ids) > MAX_BATCH_GROUPS:
                return [], f"一次最多操作 {MAX_BATCH_GROUPS} 个群，当前给了 {len(ids)} 个"
            return ids, ""

        current = self._require_group(event)
        if current:
            return [current], ""
        return [], "私聊使用时必须显式指定群号，例: /g pp 12345678"

    # ------------------------------------------------------------------
    # 后台定时任务：长禁言续期 / 动态答案刷新 / 新版本检查 / 报告提醒 / 抽奖开奖
    # ------------------------------------------------------------------

    def _clients(self) -> list:
        """全部 aiocqhttp 适配器的 client。后台任务手里没有 event，只能这样拿。"""
        try:
            return [
                platform.get_client()
                for platform in self.context.platform_manager.platform_insts
                if platform.meta().name == "aiocqhttp"
            ]
        except Exception as exc:
            logger.debug(f"[ZM-QQGroupmgr] 获取 aiocqhttp client 失败: {exc}")
            return []

    def _bg_api(self) -> Optional[OneBotApi]:
        clients = self._clients()
        return OneBotApi(client=clients[0]) if clients else None

    def _meta(self) -> dict:
        """settings.json 里的全局小状态（上次检查时间等）。

        其余顶层键都是群号，这里刻意用一个不可能与群号重合的名字。
        """
        bucket = self.settings.get("__meta__")
        if not isinstance(bucket, dict):
            bucket = {}
            self.settings.set("__meta__", bucket)
        return bucket

    def _poll_minutes(self) -> int:
        """GitHub sha 的查询间隔（分钟）。"""
        value = coerce_int(self.config.get("join_sha_poll_minutes"), DEFAULT_POLL_MINUTES)
        return max(1, min(value, MAX_POLL_MINUTES))

    async def _ticker(self) -> None:
        """一个循环干五件事，省掉五套定时器。

        ponytail: 60 秒粒度的轮询，够用；要秒级精度再改成每条记录一个定时器。
        """
        jobs = (
            self._renew_long_mutes,
            self._refresh_dynamic_answers,
            self._check_update,
            self._remind_reports,
            self._settle_draws,
        )
        while True:
            await asyncio.sleep(60)
            for job in jobs:
                try:
                    await job()
                except Exception as exc:  # 一件事出错不能耽误另外几件，也不能让循环停掉
                    logger.warning(f"[ZM-QQGroupmgr] 后台任务 {job.__name__} 异常: {exc}")

    async def _renew_long_mutes(self) -> None:
        """超过 30 天的禁言到点续期。"""
        due = self.mutes.due_for_renew()
        if not due:
            return
        api = self._bg_api()
        if api is None:
            return
        for item in due:
            try:
                await api.mute(
                    int(item["group_id"]),
                    int(item["user_id"]),
                    chunk_duration(item["remaining"]),
                )
            except (RuntimeError, ValueError) as exc:
                gave_up = await self.mutes.mark_renew_failed(
                    item["group_id"], item["user_id"]
                )
                logger.warning(
                    f"[ZM-QQGroupmgr] 续期禁言 {item['user_id']}@{item['group_id']} 失败: {exc}"
                    + ("，已放弃这条记录（成员可能已退群）" if gave_up else "，5 分钟后重试")
                )
                continue
            await self.mutes.mark_renewed(item["group_id"], item["user_id"])
            logger.info(
                f"[ZM-QQGroupmgr] 已为 {item['user_id']}@{item['group_id']} 续期禁言，"
                f"剩余 {format_duration(item['remaining'])}"
            )

    async def _refresh_dynamic_answers(self) -> None:
        """把开了 /ja set dynamic 的群的加群答案换成最新 sha。"""
        interval = self._poll_minutes() * 60
        meta = self._meta()
        now = int(time.time())
        if now - int(meta.get("sha_checked_at") or 0) < interval:
            return
        meta["sha_checked_at"] = now
        await self.settings.save()

        targets = [
            (group_id, bucket["join_approval"])
            for group_id, bucket in self.settings.items()
            if isinstance(bucket, dict)
            and isinstance(bucket.get("join_approval"), dict)
            and bucket["join_approval"].get("mode") == "dynamic"
        ]
        if not targets:
            return

        api = self._bg_api()
        if api is None:
            return
        for group_id, state in targets:
            repo = state.get("repo") or ""
            if not repo:
                continue
            sha, error = await self._sha_cache.latest(repo, ttl=interval, force=True)
            if not sha:
                logger.warning(f"[ZM-QQGroupmgr] 群 {group_id} 刷新 sha 失败: {error}")
                continue
            if sha == state.get("answer"):
                continue
            ok, why = await api.set_group_add_option(
                int(group_id),
                ADD_OPTION_ANSWER,
                state.get("question") or DEFAULT_JOIN_QUESTION,
                sha,
            )
            if not ok:
                logger.warning(f"[ZM-QQGroupmgr] 群 {group_id} 更新加群答案失败: {why}")
                continue
            state["answer"] = sha
            await self.settings.save()
            logger.info(f"[ZM-QQGroupmgr] 群 {group_id} 加群答案已更新为 {sha[:7]}")

    async def _check_update(self) -> None:
        """按配置的天数查一次最新 release，有新版本就在开了 /update on 的群里说一声。"""
        days = max(1, min(coerce_int(self.config.get("update_check_days"), 5), 30))
        meta = self._meta()
        now = int(time.time())
        if now - int(meta.get("update_checked_at") or 0) < days * 86400:
            return
        meta["update_checked_at"] = now
        await self.settings.save()

        latest, error = await latest_release_tag(PLUGIN_REPO)
        if not latest:
            logger.debug(f"[ZM-QQGroupmgr] 版本检查失败: {error}")
            return
        if version_tuple(latest) <= version_tuple(PLUGIN_VERSION):
            return
        # 同一个新版本只提示一次，别每 5 天刷一遍
        if meta.get("update_notified") == latest:
            return

        api = self._bg_api()
        if api is None:
            return
        groups = [str(item.get("group_id")) for item in await api.group_list()]
        text = str(self.config.get("update_tip") or DEFAULT_UPDATE_TIP).replace(
            "{version}", latest
        )
        login = await api.try_call("get_login_info") or {}
        bot_id = str(login.get("user_id") or "10000")
        sent = 0
        for group_id in groups:
            if not group_id or not self._update_notify_enabled(group_id):
                continue
            result = await api.send_forward(
                int(group_id),
                [forward_node(bot_id, UPDATE_CARD_TITLE, text)],
                source=UPDATE_CARD_TITLE,
                news=[{"text": f"v{latest} 已发布"}],
                summary="查看 1 条转发消息",
                prompt=f"[{UPDATE_CARD_TITLE}]",
            )
            if result is None:
                await api.send_group_msg(int(group_id), text)
            sent += 1
            await asyncio.sleep(BATCH_INTERVAL)

        meta["update_notified"] = latest
        await self.settings.save()
        logger.info(f"[ZM-QQGroupmgr] 发现新版本 v{latest}，已在 {sent} 个群提示")

    async def _remind_reports(self) -> None:
        """每 report_remind_minutes 分钟，在还有未解决报告且开着提醒的群里列一遍。"""
        minutes = max(1, coerce_int(self.config.get("report_remind_minutes"), 60))
        meta = self._meta()
        now = int(time.time())
        if now - int(meta.get("report_reminded_at") or 0) < minutes * 60:
            return
        api = self._bg_api()
        if api is None:
            return
        meta["report_reminded_at"] = now
        await self.settings.save()

        at_admins = self.config.get("report_remind_at", True)
        configured = coerce_str_list(self.config.get("report_remind_users"))
        bot_id = ""
        if at_admins:
            login = await api.try_call("get_login_info") or {}
            bot_id = str(login.get("user_id") or "")

        # 机器人已经退出的群跳过，不然那里的未解决报告会每轮发送失败刷一次日志
        joined = {str(item.get("group_id")) for item in await api.group_list()}
        for group_id in self.reports.groups_with_open():
            if (joined and group_id not in joined) or not self._group_flag(
                group_id, "report_remind", self._remind_default()
            ):
                continue
            # 用消息段而不是 CQ 字符串：报告内容是成员写的，拼进字符串就得逐个转义
            segments = []
            if at_admins:
                members = await api.member_list(int(group_id))
                for uid in remind_targets(members, configured, bot_id):
                    segments.append({"type": "at", "data": {"qq": uid}})
            # 查成员期间队列可能刚被清空，别 @ 完了说没有问题
            if not self.reports.open_reports(group_id):
                continue
            text = digest_text(self.reports, group_id)
            segments.append({"type": "text", "data": {"text": ("\n" if segments else "") + text}})
            await api.send_group_msg(int(group_id), segments)
            await asyncio.sleep(BATCH_INTERVAL)

    async def _draw_account(self, self_id: str) -> Optional[tuple]:
        """发起抽奖的 QQ 账号：返回 ``(api, 账号, 所在群号)``，没连着返回 None。

        按账号找而不是取第一个适配器：适配器顺序会因为改配置而变。
        """
        # 手改过的 self_id 可能是 "²" 或几千位数字，int() 会抛异常，把整轮开奖都卡住
        target = int(self_id) if self_id.isdecimal() and len(self_id) <= 20 else None
        for client in self._clients():
            api = OneBotApi(client=client, self_id=target)
            # 账号不在这个适配器上是常态，不走 api.call，免得每分钟记一条错误日志
            try:
                login = await client.api.call_action("get_login_info", **api.route)
                groups = await client.api.call_action("get_group_list", **api.route)
                bot_id = str(login.get("user_id") or "")
                joined = {str(item.get("group_id")) for item in groups}
            except Exception:
                continue
            if bot_id and (target is None or bot_id == self_id):
                return api, bot_id, joined
        return None

    async def _settle_draws(self) -> None:
        """到点的抽奖开奖。账号离线期间到点的，连上后第一轮补开。"""
        accounts = {}
        for group_id, name, draw in self.draws.due(time.time()):
            self_id = str(draw.get("self_id") or "")
            if self_id not in accounts:
                accounts[self_id] = await self._draw_account(self_id)
            account = accounts[self_id]
            if account is None:  # 没连着不算开奖失败，等多久都行
                if self_id not in self._draw_offline:
                    self._draw_offline.add(self_id)
                    logger.warning(f"[ZM-QQGroupmgr] 账号 {self_id} 未连接，到点的抽奖等它连上后开奖")
                continue
            self._draw_offline.discard(self_id)
            # 等协议端或开上一条的时候，这条可能已被取消
            if self.draws.get(group_id, name) is not draw:
                continue
            api, bot_id, joined = account
            try:
                failure = (
                    await self._settle_draw(api, group_id, name, draw, bot_id)
                    if group_id in joined
                    else "机器人不在该群"
                )
            except Exception as exc:  # 一条坏记录不能卡住别的群开奖
                failure = f"{type(exc).__name__}: {exc}"
            if failure:
                await self._retry_draw(group_id, name, draw, failure)
            await asyncio.sleep(BATCH_INTERVAL)

    async def _retry_draw(self, group_id: str, name: str, draw: dict, failure: str) -> None:
        if self.draws.get(group_id, name) is not draw:
            return
        if self.draws.retry_later(draw, time.time()):
            await self.draws_store.save()
            logger.warning(f"[ZM-QQGroupmgr] 群 {group_id} 抽奖「{name}」开奖失败（{failure}），稍后重试")
            return
        await self.draws.remove(group_id, name)
        logger.error(
            f"[ZM-QQGroupmgr] 群 {group_id} 抽奖「{name}」多次开奖失败（{failure}），已放弃。"
            f"已公布 {coerce_int(draw.get('announced'), 0)} 人，"
            f"未通报的中奖者: {draw.get('winners') or '无'}"
        )

    async def _settle_draw(
        self, api: OneBotApi, group_id: str, name: str, draw: dict, bot_id: str
    ) -> str:
        """开奖一条，返回失败原因；开完或已被取消返回空串。"""
        if not isinstance(draw.get("winners"), list):
            # 开奖时才取成员：强制抽奖要算上后来进群的，报名抽奖要去掉退群的
            members = await api.member_list(int(group_id), no_cache=True)
            if self.draws.get(group_id, name) is not draw:  # 查询期间被取消
                return ""
            if not members:  # 查不到不能当成没人参与，否则接口抖一下抽奖就作废了
                return "查询群成员失败"
            draw["winners"] = pick_winners(draw, members, bot_id)

        tip = str(self.config.get("draw_claim_tip") or DEFAULT_CLAIM_TIP)
        self._announcing = draw
        try:
            # 先落盘再发：发送超时不代表没发出去，重试时必须还是同一批人
            await self.draws_store.save()
            # ponytail: 至少一次语义，回执丢失或进程崩溃时这一条会重发；恰好一次要协议端支持幂等
            while True:
                # 落盘期间中奖者可能全退了、名单已被清掉：等下一轮重抽，不能公布无人中奖
                if not isinstance(draw.get("winners"), list):
                    return "中奖者已退群，等待重新抽取"
                message, chunk = draw_next_message(name, draw, tip)
                # 领奖提示只在最后一条。要在发送前判断：发送期间剩下的人退群时，提示还得单独补发
                last = len(chunk) == len(draw["winners"])
                if not await api.try_ok("send_group_msg", group_id=int(group_id), message=message):
                    return "开奖消息发送失败"
                # 按人移除而不是切片：发送期间名单可能因有人退群而变
                draw["winners"] = [
                    uid for uid in draw.get("winners") or [] if str(uid) not in chunk
                ]
                # 有进展就重新计数，否则人多的抽奖发到一半就用完重试次数
                draw["announced"] = coerce_int(draw.get("announced"), 0) + len(chunk)
                draw["attempts"] = 0
                if last:
                    break
                await self.draws_store.save()
                await asyncio.sleep(BATCH_INTERVAL)
            await self.draws.remove(group_id, name)
        finally:
            self._announcing = None
        logger.info(
            f"[ZM-QQGroupmgr] 群 {group_id} 抽奖「{name}」已开奖，中奖 {draw['announced']} 人"
        )
        return ""

    def _group_flag(self, group_id: str, key: str, default: bool = True) -> bool:
        """settings.json 里按群保存的开关，没设置过就用 ``default``。"""
        value = self.settings.group(str(group_id)).get(key)
        return default if value is None else bool(value)

    def _remind_default(self) -> bool:
        """没用过 /rmd 的群是否提醒未解决的报告，听插件配置的。"""
        return bool(self.config.get("report_remind_enabled", True))

    def _update_notify_enabled(self, group_id: str) -> bool:
        """/update 开关，默认开启。"""
        return self._group_flag(group_id, "update_notify")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("update")
    async def cmd_update(self, event: AstrMessageEvent):
        """/update on|off - 本群是否接收插件更新提示"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        args = self._args(event, "update")
        action = args[0].lower() if args else ""
        if action not in {"on", "off"}:
            state = "开启" if self._update_notify_enabled(group_id) else "关闭"
            days = max(1, min(coerce_int(self.config.get("update_check_days"), 5), 30))
            yield event.plain_result(
                f"用法: /update on|off\n当前状态: {state}（每 {days} 天检查一次新版本）"
            )
            return

        self.settings.group(group_id)["update_notify"] = action == "on"
        await self.settings.save()
        yield event.plain_result(
            "已开启更新通知，有新版本时会在本群提示" if action == "on" else "已关闭本群的更新通知"
        )

    # ------------------------------------------------------------------
    # 禁言相关命令
    # ------------------------------------------------------------------

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("mute", alias={"m"})
    async def cmd_mute(self, event: AstrMessageEvent):
        """/mute <成员> [时长] [理由] - 禁言成员，默认 10 分钟（缩写 /m）"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        raw = self._raw_after(event, "mute", "m")
        # 目标只从开头那几段里认：理由是自由文本，里面出现的 5-12 位数字
        # （比如「小号 123456789 也是他」）不能被当成第二个禁言对象
        tokens = [p for p in raw.split() if p.strip()]
        head = []
        while tokens and is_target_token(tokens[0]):
            head.append(tokens.pop(0))
        targets = extract_targets(event, " ".join(head))
        if not targets:
            yield event.plain_result(
                "用法: /mute <成员> [时长] [理由]\n"
                "例: /mute @某人 10m 刷屏、/m 12345 1h"
            )
            return

        # 去掉目标后，第一段能当时长解析的就是时长，剩下的整段算理由
        duration = 600
        capped = 0
        rest = [p for p in tokens if not any(t in p for t in targets)]
        if rest:
            parsed = parse_duration(rest[0], default_unit="m")
            if parsed is not None:
                duration = min(parsed, MAX_DURATION)
                if parsed > MAX_DURATION:
                    capped = parsed
                rest = rest[1:]
        # 理由会落进 settings.json，截断一下，别让人把一整篇聊天记录存进来
        reason = truncate(" ".join(rest), 100) or DEFAULT_MUTE_REASON

        succeeded, failed = [], []
        for user_id in targets:
            try:
                # QQ 只接受 30 天以内的禁言，更长的先禁 30 天，由后台定时续期
                await api.mute(int(group_id), int(user_id), chunk_duration(duration))
                await self.mutes.record(
                    group_id, user_id, duration, reason, str(event.get_sender_id())
                )
                succeeded.append(user_id)
            except RuntimeError as exc:
                failed.append(f"{user_id}({exc})")

        lines = []
        if capped:
            lines.append(
                f"{format_duration(capped)} 超过上限，已按 {format_duration(MAX_DURATION)} 处理"
            )
        if succeeded:
            label = "解除禁言" if duration == 0 else f"禁言 {format_duration(duration)}"
            lines.append(f"已对 {len(succeeded)} 名成员{label}: {', '.join(succeeded)}")
            if duration != 0 and reason != DEFAULT_MUTE_REASON:
                lines.append(f"理由: {truncate(reason, 60)}")
            if duration > MUTE_CHUNK:
                lines.append(
                    f"QQ 单次最多禁言 {format_duration(MUTE_CHUNK)}，"
                    "机器人会自动续期到时长走完（期间请保持插件运行）"
                )
        if failed:
            lines.append(f"失败: {', '.join(failed)}")
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("unmute", alias={"um"})
    async def cmd_unmute(self, event: AstrMessageEvent):
        """/unmute <成员> - 解除禁言（缩写 /um）"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        targets = extract_targets(event, self._raw_after(event, "unmute", "um"))
        if not targets:
            yield event.plain_result("用法: /unmute <成员>（缩写 /um）")
            return

        succeeded, failed = [], []
        for user_id in targets:
            try:
                await api.mute(int(group_id), int(user_id), 0)
                await self.mutes.clear(group_id, user_id)
                succeeded.append(user_id)
            except RuntimeError as exc:
                failed.append(f"{user_id}({exc})")

        lines = []
        if succeeded:
            lines.append(f"已解除禁言: {', '.join(succeeded)}")
        if failed:
            lines.append(f"失败: {', '.join(failed)}")
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("mutelist")
    async def cmd_mutelist(self, event: AstrMessageEvent):
        """/mutelist - 查看被禁言的成员及其剩余时长"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        muted = await self.mutes.list_muted(api, group_id)
        if not muted:
            yield event.plain_result("当前没有被禁言的成员")
            return

        lines = [f"本群禁言列表（共 {len(muted)} 人）"]
        for index, item in enumerate(muted, start=1):
            remaining = format_duration(item["remaining"]) if item["remaining"] else "永久"
            line = f"{index}. {item['name']}（{item['user_id']}）剩余 {remaining}"
            reason = item.get("reason") or "未记录（非本插件发起的禁言）"
            line += f"\n   原因: {truncate(reason, 40)}"
            if item.get("operator"):
                line += f" | 操作者: {item['operator']}"
            lines.append(line)
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("muteall")
    async def cmd_muteall(self, event: AstrMessageEvent):
        """/muteall [时长] - 全体禁言，默认永久；/muteall off 解除"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        args = self._args(event, "muteall")
        first = args[0].lower() if args else ""

        if first in {"off", "关闭", "解除", "cancel"}:
            try:
                await api.mute_all(int(group_id), False)
            except RuntimeError as exc:
                yield event.plain_result(f"解除全体禁言失败: {exc}")
                return
            state = self.settings.group(group_id)
            state.pop("muteall_until", None)
            await self.settings.save()
            yield event.plain_result("已解除全体禁言")
            return

        duration = 0
        if args:
            parsed = parse_duration(args[0], default_unit="m")
            if parsed is None:
                yield event.plain_result(
                    "时长格式错误。支持: 30s、10m、2h、1d，或省略表示永久\n例: /muteall 10m"
                )
                return
            duration = min(parsed, MAX_DURATION)

        try:
            await api.mute_all(int(group_id), True)
        except RuntimeError as exc:
            yield event.plain_result(f"全体禁言失败: {exc}")
            return

        if duration <= 0:
            yield event.plain_result("已开启全体禁言（永久），使用 /muteall off 解除")
            return

        state = self.settings.group(group_id)
        state["muteall_until"] = int(time.time()) + duration
        await self.settings.save()
        self._spawn(self._auto_unmute_all(event, group_id, duration))
        yield event.plain_result(
            f"已开启全体禁言 {format_duration(duration)}，到期后自动解除"
        )

    async def _auto_unmute_all(self, event: AstrMessageEvent, group_id: str, duration: int) -> None:
        """全体禁言到期后自动解除。"""
        await asyncio.sleep(duration)
        state = self.settings.group(group_id)
        until = state.get("muteall_until") or 0
        # 期间被手动解除或重新设置了更晚的到期时间，就不再处理
        if not until or until > int(time.time()) + 5:
            return

        api = OneBotApi(event)
        try:
            await api.mute_all(int(group_id), False)
        except RuntimeError as exc:
            logger.warning(f"[ZM-QQGroupmgr] 自动解除全体禁言失败: {exc}")
            return

        state.pop("muteall_until", None)
        await self.settings.save()
        await api.send_group_msg(int(group_id), "全体禁言已到期，自动解除")

    # ------------------------------------------------------------------
    # 进群审批
    # ------------------------------------------------------------------

    def _join_state(self, group_id: str) -> dict:
        state = self.settings.group(str(group_id)).get("join_approval")
        return state if isinstance(state, dict) else {}

    def _verify_minutes(self) -> int:
        """新成员必须在多少分钟内发出验证码。"""
        value = coerce_int(self.config.get("join_verify_minutes"), 1)
        return max(1, min(value, MAX_VERIFY_MINUTES))

    def _code_digits(self) -> int:
        value = coerce_int(self.config.get("join_code_digits"), 6)
        return value if value in VALID_DIGITS else 6

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("join_approval", alias={"ja"})
    async def cmd_join_approval(self, event: AstrMessageEvent):
        """/join_approval - 进群审批（缩写 /ja）"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        raw = self._raw_after(event, "join_approval", "ja")
        args = raw.split()
        action = args[0].lower() if args else ""

        if action in {"off", "关闭", "disable"}:
            self.settings.group(group_id)["join_approval"] = {"mode": ""}
            await self.settings.save()
            yield event.plain_result(
                "已关闭本群进群审批（QQ 侧的加群方式不会自动改回，需要的话请手动调整）"
            )
            return

        if action in {"status", "状态"} or not action:
            yield event.plain_result(self._join_status_text(group_id))
            return

        if action != "set" or len(args) < 2:
            yield event.plain_result(JOIN_APPROVAL_USAGE)
            return

        sub = args[1].lower()

        if sub in JOIN_CODE_KEYWORDS:
            code_type = args[2].lower() if len(args) > 2 else ""
            if code_type not in CODE_TYPES:
                yield event.plain_result(
                    "验证码类型只能是 number / letter / mix / sha\n"
                    "例: /ja set vc mix"
                )
                return
            if code_type == CODE_SHA:
                timeout = self._arm_pending(
                    event, "设置进群验证码", kind="ja_repo", group_id=group_id, target="code"
                )
                yield event.plain_result(
                    f"请在 {format_duration(timeout)}内发送 GitHub 仓库链接"
                    "（例: https://github.com/owner/repo）"
                )
                return

            state = {
                "mode": "code",
                "code_type": code_type,
                "repo": "",
            }
            self.settings.group(group_id)["join_approval"] = state
            await self.settings.save()
            yield event.plain_result(
                f"指令执行成功 已启用进群验证码（{CODE_TYPE_LABELS[code_type]}）\n"
                f"新成员需在 {self._verify_minutes()} 分钟内回发验证码，超时自动踢出"
            )
            return

        if sub == "static":
            content = raw.split(None, 2)[2].strip() if len(args) > 2 else ""
            if not content:
                yield event.plain_result("用法: /ja set static <内容>\n例: /ja set static 你好")
                return
            yield event.plain_result(
                await self._apply_join_answer(event, api, group_id, "static", content, "")
            )
            return

        if sub == "dynamic":
            timeout = self._arm_pending(
                event, "设置动态加群答案", kind="ja_repo", group_id=group_id, target="dynamic"
            )
            yield event.plain_result(
                f"请在 {format_duration(timeout)}内发送 GitHub 仓库链接"
                "（例: https://github.com/owner/repo）"
            )
            return

        yield event.plain_result(JOIN_APPROVAL_USAGE)

    def _join_status_text(self, group_id: str) -> str:
        state = self._join_state(group_id)
        mode = state.get("mode") or ""
        if not mode:
            return "本群未启用进群审批\n" + JOIN_APPROVAL_USAGE
        if mode == "code":
            code_type = state.get("code_type") or ""
            lines = [
                f"进群审批: 入群验证码（{CODE_TYPE_LABELS.get(code_type, code_type)}）",
                f"限时: {self._verify_minutes()} 分钟，超时踢出",
            ]
            if code_type == CODE_SHA:
                lines.append(f"仓库: {state.get('repo') or '未设置'}")
                lines.append(f"查询间隔: {self._poll_minutes()} 分钟")
            else:
                lines.append(f"验证码位数: {self._code_digits()}（letter 固定 6 位字母）")
            return "\n".join(lines)
        if mode == "static":
            return (
                "进群审批: 回答正确问题（固定答案）\n"
                f"问题: {state.get('question') or ''}\n"
                f"答案: {state.get('answer') or ''}"
            )
        return (
            "进群审批: 回答正确问题（动态 sha）\n"
            f"仓库: {state.get('repo') or '未设置'}\n"
            f"当前 sha: {state.get('answer') or '未取到'}\n"
            f"刷新间隔: {self._poll_minutes()} 分钟"
        )

    async def _apply_join_answer(
        self,
        event: AstrMessageEvent,
        api: OneBotApi,
        group_id: str,
        mode: str,
        answer: str,
        repo: str,
    ) -> str:
        """设置「需要正确回答问题」的答案，加群方式不对时先问管理员。"""
        option = await api.group_add_option(int(group_id))
        if option == ADD_OPTION_ANSWER:
            return await self._commit_join_answer(api, group_id, mode, answer, repo)

        timeout = self._arm_pending(
            event, "设置加群方式", kind="ja_confirm",
            group_id=group_id, mode=mode, answer=answer, repo=repo,
        )
        current = "查不到当前加群方式" if option is None else f"当前加群方式代码 {option}"
        return (
            f"本群的加群方式不是「需要正确回答问题」（{current}）。\n"
            f"是否现在改为该方式？请在 {format_duration(timeout)}内回复 是 / 否"
        )

    async def _commit_join_answer(
        self, api: OneBotApi, group_id: str, mode: str, answer: str, repo: str
    ) -> str:
        question = str(self.config.get("join_question_text") or DEFAULT_JOIN_QUESTION)
        ok, why = await api.set_group_add_option(
            int(group_id), ADD_OPTION_ANSWER, question, answer
        )
        if not ok:
            return (
                f"设置加群方式失败: {why}\n"
                "该接口是 NapCat 扩展，且机器人需为本群群主或管理员"
            )

        self.settings.group(group_id)["join_approval"] = {
            "mode": mode,
            "question": question,
            "answer": answer,
            "repo": repo,
        }
        await self.settings.save()

        if mode == "dynamic":
            return f"已将群正确密码更换为动态值 当前sha值为 {answer}"
        return (
            "指令执行成功 本群加群方式已设为「需要正确回答问题」\n"
            f"问题: {question}\n答案: {answer}"
        )

    async def _handle_ja_repo(self, event: AstrMessageEvent, key: str, pending: dict):
        """收下管理员补发的 GitHub 仓库链接。"""
        text = (event.message_str or "").strip()
        if not text or self._looks_like_command(event):
            return

        self._pending_media.drop(key)
        repo = parse_repo(text)
        if not repo:
            await event.send(
                event.plain_result("无法识别的 GitHub 仓库链接，指令已结束，请重新执行")
            )
            event.stop_event()
            return

        api = OneBotApi(event)
        group_id = str(pending.get("group_id") or "")
        sha, error = await self._sha_cache.latest(repo, force=True)
        if not sha:
            await event.send(event.plain_result(f"获取最新 commit 失败: {error}"))
            event.stop_event()
            return

        if pending.get("target") == "code":
            self.settings.group(group_id)["join_approval"] = {
                "mode": "code",
                "code_type": CODE_SHA,
                "repo": repo,
            }
            await self.settings.save()
            await event.send(
                event.plain_result(
                    f"指令执行成功 目前sha值为 {sha}\n"
                    f"新成员需在 {self._verify_minutes()} 分钟内发送该 sha（前 7 位即可），"
                    f"每 {self._poll_minutes()} 分钟刷新一次"
                )
            )
        else:
            await event.send(
                event.plain_result(
                    await self._apply_join_answer(event, api, group_id, "dynamic", sha, repo)
                )
            )
        event.stop_event()

    async def _handle_ja_confirm(self, event: AstrMessageEvent, key: str, pending: dict):
        """处理「要不要把加群方式改成需要正确回答问题」的答复。"""
        answer = (event.message_str or "").strip().lower()
        if not answer or (answer not in YES_WORDS and answer not in NO_WORDS):
            return

        self._pending_media.drop(key)
        if answer in NO_WORDS:
            tip = str(self.config.get("join_decline_tip") or DEFAULT_JOIN_DECLINE_TIP)
            await event.send(event.plain_result(tip))
            event.stop_event()
            return

        api = OneBotApi(event)
        if not api.available:
            await event.send(event.plain_result(QQ_ONLY))
        else:
            await event.send(
                event.plain_result(
                    await self._commit_join_answer(
                        api,
                        str(pending.get("group_id") or ""),
                        str(pending.get("mode") or "static"),
                        str(pending.get("answer") or ""),
                        str(pending.get("repo") or ""),
                    )
                )
            )
        event.stop_event()

    async def _start_verify(self, api: OneBotApi, group_id: str, user_id: str) -> None:
        """新成员进群后发出验证码并挂上超时踢出。"""
        state = self._join_state(group_id)
        if state.get("mode") != "code":
            return

        code_type = str(state.get("code_type") or "")
        if code_type not in CODE_TYPES:
            return

        minutes = self._verify_minutes()
        repo = ""
        if code_type == CODE_SHA:
            repo = str(state.get("repo") or "")
            if not repo:
                # 没仓库就永远没有正确答案，这是配置坏了，不能拿新成员撒气
                logger.warning(f"[ZM-QQGroupmgr] 群 {group_id} 选了 sha 却没有仓库，跳过验证")
                return
            code, error = await self._sha_cache.latest(repo, ttl=self._poll_minutes() * 60)
            if not code:
                # 取不到也照常挂验证：成员发来的 sha 会当场再问一次 GitHub，
                # 到点还没发对就照踢，不能因为 GitHub 抽风就放人进来
                logger.warning(f"[ZM-QQGroupmgr] 群 {group_id} 取 sha 失败: {error}")
            template = str(self.config.get("join_sha_tip") or DEFAULT_JOIN_SHA_TIP)
            message = render_cq(
                template,
                {
                    "at": f"[CQ:at,qq={user_id}]",
                    "minutes": str(minutes),
                    "repo": escape_cq(repo),
                    "user_id": str(user_id),
                    "group_id": str(group_id),
                },
            )
        else:
            code = make_code(code_type, self._code_digits())
            template = str(self.config.get("join_verify_tip") or DEFAULT_JOIN_VERIFY_TIP)
            message = render_cq(
                template,
                {
                    "at": f"[CQ:at,qq={user_id}]",
                    "minutes": str(minutes),
                    "code": code,
                    "user_id": str(user_id),
                    "group_id": str(group_id),
                },
            )

        self._prune_verify()
        self._pending_verify[(str(group_id), str(user_id))] = {
            "code": code,
            "is_sha": code_type == CODE_SHA,
            "repo": repo,
            "deadline": time.time() + minutes * 60,
        }
        await api.send_group_msg(int(group_id), message)
        self._spawn(self._verify_timeout(api, group_id, user_id, minutes))

    def _prune_verify(self) -> None:
        now = time.time()
        for key in [k for k, v in self._pending_verify.items() if v["deadline"] <= now]:
            self._pending_verify.pop(key, None)

    async def _verify_timeout(
        self, api: OneBotApi, group_id: str, user_id: str, minutes: int
    ) -> None:
        """限时内没验证就踢出。"""
        try:
            await asyncio.sleep(minutes * 60)
        except asyncio.CancelledError:
            return

        key = (str(group_id), str(user_id))
        item = self._pending_verify.get(key)
        if item is None:
            return
        # 期间退群又进群的话，登记已经被换成更晚的那次，踢人交给新的定时任务
        if item["deadline"] > time.time() + 1:
            return
        self._pending_verify.pop(key, None)

        name = await api.stranger_name(user_id)
        try:
            await api.kick(int(group_id), int(user_id))
        except RuntimeError as exc:
            logger.warning(f"[ZM-QQGroupmgr] 验证超时踢出 {user_id} 失败: {exc}")
            return

        template = str(self.config.get("join_timeout_tip") or DEFAULT_JOIN_TIMEOUT_TIP)
        await api.send_group_msg(
            int(group_id),
            render_cq(
                template,
                {
                    "at": escape_cq(name),
                    "name": escape_cq(name),
                    "user_id": str(user_id),
                    "group_id": str(group_id),
                    "minutes": str(minutes),
                },
            ),
        )
        logger.info(f"[ZM-QQGroupmgr] 群 {group_id} 成员 {user_id} 验证超时，已踢出")

    async def _kick_wrong_sha(self, api: OneBotApi, group_id: str, user_id: str) -> None:
        """sha 连错 MAX_SHA_TRIES 次，不等超时直接踢。"""
        name = await api.stranger_name(user_id)
        try:
            await api.kick(int(group_id), int(user_id))
        except RuntimeError as exc:
            logger.warning(f"[ZM-QQGroupmgr] 连错踢出 {user_id} 失败: {exc}")
            return
        await api.send_group_msg(
            int(group_id),
            f"{escape_cq(name)}（{user_id}）连续 {MAX_SHA_TRIES} 次验证失败，已踢出",
        )
        logger.info(
            f"[ZM-QQGroupmgr] 群 {group_id} 成员 {user_id} 连错 {MAX_SHA_TRIES} 次，已踢出"
        )

    async def _verify_matches(self, pending: dict, text: str) -> bool:
        """比对验证码；sha 模式下允许成员发的是比缓存更新的那个 commit。

        查询间隔可以设到几十分钟，期间仓库完全可能又推了几个 commit，
        照着 GitHub 页面抄的成员不该因为我们缓存旧就被踢。
        """
        is_sha = bool(pending.get("is_sha"))
        if code_matches(pending.get("code", ""), text, is_sha):
            return True
        repo = str(pending.get("repo") or "")
        if not is_sha or not repo or not is_sha_text(text):
            return False
        fresh, _ = await self._sha_cache.latest(repo, ttl=SHA_RECHECK_TTL)
        return bool(fresh) and code_matches(fresh, text, True)

    async def _check_verify(self, event, api, group_id, user_id, text) -> bool:
        """待验证成员发言时比对验证码，返回是否已处理这条消息。"""
        key = (str(group_id), str(user_id))
        pending = self._pending_verify.get(key)
        if not pending:
            return False
        if time.time() > pending["deadline"]:
            self._pending_verify.pop(key, None)
            return False
        if not await self._verify_matches(pending, text):
            # 每次「像 sha 但不对」的消息都要去问一次 GitHub，放着不管等于
            # 把未认证 API 那 60 次/小时的配额交给刷屏的人，错够 5 次直接踢
            if pending.get("is_sha") and is_sha_text(text):
                pending["tries"] = int(pending.get("tries") or 0) + 1
                if pending["tries"] >= MAX_SHA_TRIES:
                    self._pending_verify.pop(key, None)
                    await self._kick_wrong_sha(api, group_id, user_id)
                    event.stop_event()
                    return True
            return False

        self._pending_verify.pop(key, None)
        tip = str(self.config.get("join_pass_tip") or DEFAULT_JOIN_PASS_TIP)
        await api.send_group_msg(int(group_id), self._render(tip, event))
        logger.info(f"[ZM-QQGroupmgr] 群 {group_id} 成员 {user_id} 验证通过")
        event.stop_event()
        return True

    # ------------------------------------------------------------------
    # 敏感词系统
    # ------------------------------------------------------------------

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("sensitive-words", alias={"sw"})
    async def cmd_sensitive(self, event: AstrMessageEvent):
        """敏感词系统: on/off/add/del/list/mode/reload/status"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        raw = self._raw_after(event, "sensitive-words", "sw")

        parts = raw.split()
        action = parts[0].lower() if parts else "status"
        rest = raw[len(parts[0]):].strip() if parts else ""

        if action == "on":
            default_minutes = coerce_int(self.config.get("sensitive_default_duration"), 10)
            if self.sw_toggle.is_enabled(group_id):
                current = self.sw_toggle.value(group_id, "duration", default_minutes * 60)
                yield event.plain_result(
                    f"敏感词系统已处于开启状态，当前禁言时长 {format_duration(current)}\n"
                    f"如需修改时长，请先 /sw off 再 /sw on <时长>"
                )
                return

            duration = default_minutes * 60
            if rest:
                parsed = parse_duration(rest, default_unit="m")
                if parsed is None:
                    yield event.plain_result(
                        "时长格式错误。默认单位为分钟\n例: /sw on 10（10分钟）、/sw on 2h"
                    )
                    return
                duration = min(parsed, MAX_DURATION)

            await self.sw_toggle.enable(group_id, duration=duration)
            mode = self.sensitive.mode(group_id)
            label = "永久" if duration == 0 else format_duration(duration)
            yield event.plain_result(
                f"敏感词系统已开启\n禁言时长: {label}\n"
                f"词库模式: {MODE_LABELS[mode]}\n"
                f"命中后将自动撤回消息并禁言"
            )
            return

        if action == "off":
            if not self.sw_toggle.is_enabled(group_id):
                yield event.plain_result("敏感词系统当前已是关闭状态")
                return
            await self.sw_toggle.disable(group_id)
            yield event.plain_result("敏感词系统已关闭。重新开启可使用 /sw on <时长> 设置新时长")
            return

        if action == "add":
            if not rest:
                yield event.plain_result("用法: /sw add <文本>")
                return
            ok, message = await self.sensitive.add_word(group_id, rest)
            yield event.plain_result(message)
            return

        if action in {"del", "delete", "remove", "rm"}:
            if not rest:
                yield event.plain_result("用法: /sw del <文本>")
                return
            ok, message = await self.sensitive.remove_word(group_id, rest)
            yield event.plain_result(message)
            return

        if action == "list":
            words = self.sensitive.custom_words(group_id)
            if not words:
                yield event.plain_result("自定义敏感词库为空，可用 /sw add <文本> 添加")
                return
            listing = "\n".join(f"{i}. {w}" for i, w in enumerate(words, start=1))
            yield event.plain_result(f"自定义敏感词（共 {len(words)} 条）\n{listing}")
            return

        if action == "mode":
            target = rest.lower()
            if target not in VALID_MODES:
                current = self.sensitive.mode(group_id)
                yield event.plain_result(
                    "用法: /sw mode <custom|library|both>\n"
                    f"custom  - {MODE_LABELS[MODE_CUSTOM]}\n"
                    f"library - {MODE_LABELS[MODE_LIBRARY]}\n"
                    f"both    - {MODE_LABELS[MODE_BOTH]}\n"
                    f"当前: {MODE_LABELS[current]}"
                )
                return
            await self.sensitive.set_mode(group_id, target)
            note = ""
            if target in (MODE_LIBRARY, MODE_BOTH):
                count, error = await self.sensitive.reload_library()
                note = f"\n远程词库已加载 {count} 条" if not error else f"\n远程词库加载失败: {error}"
            yield event.plain_result(f"词库模式已切换为: {MODE_LABELS[target]}{note}")
            return

        if action == "reload":
            count, error = await self.sensitive.reload_library()
            if error:
                yield event.plain_result(f"远程词库加载失败: {error}")
                return
            yield event.plain_result(f"远程词库已刷新，共 {count} 条")
            return

        enabled = self.sw_toggle.is_enabled(group_id)
        duration = self.sw_toggle.value(group_id, "duration", 600)
        mode = self.sensitive.mode(group_id)
        yield event.plain_result(
            "敏感词系统状态\n"
            f"开关: {'开启' if enabled else '关闭'}\n"
            f"禁言时长: {'永久' if duration == 0 else format_duration(duration)}\n"
            f"词库模式: {MODE_LABELS[mode]}\n"
            f"自定义词条: {len(self.sensitive.custom_words(group_id))}\n"
            f"远程词条: {self.sensitive.library_size}\n\n"
            "可用: /sw on [时长] | /sw off | /sw add <文本> | /sw del <文本>\n"
            "      /sw list | /sw mode <custom|library|both> | /sw reload"
        )

    # ------------------------------------------------------------------
    # 刷屏检测开关
    # ------------------------------------------------------------------

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("antiflood", alias={"flood", "af"})
    async def cmd_antiflood(self, event: AstrMessageEvent):
        """/antiflood on|off - 刷屏检测开关"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        args = self._args(event, "antiflood", "flood", "af")
        action = args[0].lower() if args else "status"

        if action == "on":
            duration = coerce_int(self.config.get("flood_mute_duration"), 600)
            if len(args) > 1:
                parsed = parse_duration(args[1], default_unit="m")
                if parsed is None:
                    yield event.plain_result("时长格式错误。例: /antiflood on 10m")
                    return
                duration = min(parsed, MAX_DURATION)

            await self.flood_toggle.enable(group_id, duration=duration)
            yield event.plain_result(
                "刷屏检测已开启\n"
                f"判定: {self.flood.window} 秒内 {self.flood.threshold} 条，"
                f"或连续重复 {self.flood.repeat_limit} 次\n"
                f"处理: {'撤回并禁言 ' + format_duration(duration) if duration else '仅撤回'}"
            )
            return

        if action == "off":
            await self.flood_toggle.disable(group_id)
            self.flood.reset(group_id)
            yield event.plain_result("刷屏检测已关闭")
            return

        enabled = self.flood_toggle.is_enabled(group_id)
        duration = self.flood_toggle.value(
            group_id, "duration", coerce_int(self.config.get("flood_mute_duration"), 600)
        )
        yield event.plain_result(
            "刷屏检测状态\n"
            f"开关: {'开启' if enabled else '关闭'}\n"
            f"窗口: {self.flood.window} 秒 / {self.flood.threshold} 条\n"
            f"重复阈值: {self.flood.repeat_limit} 次\n"
            f"禁言时长: {'仅撤回' if not duration else format_duration(duration)}\n\n"
            "可用: /antiflood on [时长] | /antiflood off"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("cardcheck", alias={"cc"})
    async def cmd_cardcheck(self, event: AstrMessageEvent):
        """/cardcheck on|off - 群成员名片检测开关"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        args = self._args(event, "cardcheck", "cc")
        action = args[0].lower() if args else "status"

        if action == "on":
            await self.card_toggle.enable(group_id)
            yield event.plain_result(
                "群名片检测已开启\n"
                f"检测内容: 广告特征（评分阈值 "
                f"{coerce_int(self.config.get('card_ad_threshold'), 4)}）与敏感词\n"
                f"处理方式: {self.config.get('card_action', 'warn')}（可在插件配置修改）"
            )
            return

        if action == "off":
            await self.card_toggle.disable(group_id)
            yield event.plain_result("群名片检测已关闭")
            return

        enabled = self.card_toggle.is_enabled(group_id)
        yield event.plain_result(
            "群名片检测状态\n"
            f"开关: {'开启' if enabled else '关闭'}\n"
            f"处理方式: {self.config.get('card_action', 'warn')}\n\n"
            "可用: /cardcheck on | /cardcheck off"
        )

    # ------------------------------------------------------------------
    # 文件仓库
    # ------------------------------------------------------------------

    @filter.command("file", alias={"f"})
    async def cmd_file(self, event: AstrMessageEvent):
        """文件仓库: upload/download/log/list/delete

        download/list/log 查看对全体群成员开放，
        upload/delete/log update 仅 AstrBot 管理员可用。
        """
        raw = self._raw_after(event, "file", "f")

        parts = raw.split()
        action = parts[0].lower() if parts else "help"
        action = FILE_ACTION_ALIASES.get(action, action)

        is_log_update = (
            action == "log" and len(parts) > 1 and parts[1].lower() in LOG_UPDATE_KEYWORDS
        )
        if (action in ADMIN_FILE_ACTIONS or is_log_update) and not event.is_admin():
            label = "log update" if is_log_update else action
            yield event.plain_result(f"/file {label} 仅 AstrBot 管理员可用")
            return

        if action == "upload":
            async for result in self._file_upload(event, parts[1:]):
                yield result
            return

        if action == "download":
            async for result in self._file_download(event, parts[1:]):
                yield result
            return

        if action == "log":
            async for result in self._file_log(event, parts[1:], raw):
                yield result
            return

        if action == "list":
            names = self.files.names()
            if not names:
                yield event.plain_result("文件仓库为空")
                return
            lines = ["文件仓库"]
            for name in names:
                entry = self.files.get(name) or {}
                version = entry.get("version") or "未标记版本"
                lines.append(
                    f"· {name} | {version} | {format_size(entry.get('size', 0))} "
                    f"| 下载 {entry.get('downloads', 0)} 次"
                )
            yield event.plain_result("\n".join(lines))
            return

        if action in {"delete", "del", "rm"}:
            if len(parts) < 2:
                yield event.plain_result("用法: /file delete <name>")
                return
            ok, message = await self.files.delete(parts[1])
            yield event.plain_result(message)
            return

        cooldown = self.files.cooldown_seconds()
        yield event.plain_result(
            "文件仓库用法（/file 可简写为 /f）\n"
            "/file download <name>      获取临时下载链接（简写 /f dl，仅私聊可用）\n"
            "/file log <name> [次数]     查看更新日志（简写 /f l）\n"
            "/file list                 查看全部文件（简写 /f ls）\n"
            "以下仅管理员可用:\n"
            "/file upload <name> <时长>  上传文件（简写 /f up，随后发送文件即可）\n"
            "/file log update <name> <version> <内容>  简写 /f l up\n"
            "                           更新已上传目标文件的版本字段，内容为补充解释更新内容\n"
            "/file download cdreset <成员>  重置成员的下载冷却（简写 /f dl cdreset）\n"
            "/file delete <name>        删除文件（可简写为 del）\n"
            f"下载冷却: {'不限制' if cooldown <= 0 else format_duration(cooldown)}\n"
            "时长支持: 30s / 10m / 2h / 7d"
        )

    async def _file_upload(self, event: AstrMessageEvent, args: List[str]):
        """/file upload <name> <时长> - 登记一次上传，等待随后发送的文件。"""
        if not args:
            yield event.plain_result("用法: /file upload <name> <时长>\n例: /file upload guoclient 3m")
            return

        from .core.utils import safe_name

        name = safe_name(args[0])
        if not name:
            yield event.plain_result("文件名不合法，仅允许中英文、数字、-、_、.")
            return

        ttl = coerce_int(self.config.get("file_default_ttl"), 600)
        if len(args) > 1:
            parsed = parse_duration(args[1], default_unit="m")
            if parsed is None:
                yield event.plain_result("时长格式错误。例: /file upload guoclient 3m")
                return
            ttl = parsed if parsed > 0 else MAX_DURATION

        # 清掉超时未发送文件的登记，避免字典无限增长
        now = time.time()
        for stale in [
            k for k, item in self._pending_upload.items() if now - item["created"] > 300
        ]:
            self._pending_upload.pop(stale, None)

        key = f"{event.get_group_id() or 'private'}:{event.get_sender_id()}"
        self._pending_upload[key] = {
            "name": name,
            "ttl": ttl,
            "created": time.time(),
            "unified_origin": event.unified_msg_origin,
        }

        yield event.plain_result(
            f"已准备接收文件「{name}」\n"
            f"下载链接有效期: {format_duration(ttl)}\n"
            "请在 5 分钟内发送该文件（支持 zip 等任意格式）"
        )

    async def _file_download(self, event: AstrMessageEvent, args: List[str]):
        """/file download <name> - 签发临时下载链接（仅私聊）。

        另有 /file download cdreset <成员>（简写 /f dl cdreset）用于重置下载冷却。
        """
        if args and args[0].lower() in CD_RESET_KEYWORDS:
            async for result in self._file_cd_reset(event, args[1:]):
                yield result
            return

        # 下载链接只在私聊下发，群内一律只给提示语
        if event.get_group_id():
            tip = str(self.config.get("file_private_only_tip") or DEFAULT_PRIVATE_ONLY_TIP)
            yield event.plain_result(tip)
            return

        if not args:
            yield event.plain_result("用法: /file download <name>（可简写为 /f dl <name>）")
            return

        if not self.config.get("file_server_enabled", True):
            yield event.plain_result("文件下载服务未启用，请在插件配置中开启 file_server_enabled")
            return

        # 管理员不受下载冷却限制
        user_id = str(event.get_sender_id())
        if not event.is_admin():
            remaining = self.files.cooldown_remaining(user_id)
            if remaining > 0:
                tip = str(
                    self.config.get("file_cooldown_tip")
                    or "下载冷却中，请在 {remaining} 后再试（冷却时长 {cooldown}）"
                )
                yield event.plain_result(
                    self._render(
                        tip,
                        event,
                        remaining=format_duration(remaining),
                        cooldown=format_duration(self.files.cooldown_seconds()),
                    )
                )
                return

        url, error = await self.files.issue_token(args[0], user_id)
        if error:
            yield event.plain_result(error)
            return

        cooldown_note = ""
        if not event.is_admin():
            cooldown = self.files.cooldown_seconds()
            if cooldown > 0:
                await self.files.mark_cooldown(user_id)
                cooldown_note = f"\n下载冷却: {format_duration(cooldown)}，冷却结束后才能再次获取链接"

        entry = self.files.get(args[0]) or {}
        ttl = int(entry.get("ttl") or 600)
        version = entry.get("version") or "未标记版本"
        yield event.plain_result(
            f"文件: {args[0]}（{version}，{format_size(entry.get('size', 0))}）\n"
            f"下载链接: {url}\n"
            f"有效期: {format_duration(ttl)}，过期后需重新获取"
            f"{cooldown_note}"
        )

    async def _file_cd_reset(self, event: AstrMessageEvent, args: List[str]):
        """/file download cdreset <成员> - 重置成员的下载冷却（仅管理员）。"""
        if not event.is_admin():
            yield event.plain_result("/file download cdreset 仅 AstrBot 管理员可用")
            return

        targets = extract_targets(event, " ".join(args))
        if not targets:
            yield event.plain_result(
                "用法: /file download cdreset <成员>（简写 /f dl cdreset <成员>）\n"
                "例: /f dl cdreset @某人、/f dl cdreset 12345678"
            )
            return

        cooldown = self.files.cooldown_seconds()
        cleared, idle = [], []
        for user_id in targets:
            if await self.files.reset_cooldown(user_id):
                cleared.append(user_id)
            else:
                idle.append(user_id)

        lines = []
        if cleared:
            lines.append(f"已重置下载冷却: {', '.join(cleared)}")
        if idle:
            lines.append(f"本就不在冷却中（已确保可下载）: {', '.join(idle)}")
        lines.append(
            f"当前冷却时长: {'不限制' if cooldown <= 0 else format_duration(cooldown)}"
        )
        logger.info(
            f"[ZM-QQGroupmgr] {event.get_sender_id()} 重置了 {', '.join(targets)} 的下载冷却"
        )
        yield event.plain_result("\n".join(lines))

    async def _file_log(self, event: AstrMessageEvent, args: List[str], raw: str):
        """/file log <name> [次数] 与 /file log update <name> <version> <内容>"""
        if not args:
            yield event.plain_result(
                "用法: /file log <name> [次数]（简写 /f l）\n"
                "      /file log update <name> <version> <内容>（简写 /f l up）"
            )
            return

        if args[0].lower() in LOG_UPDATE_KEYWORDS:
            if not event.is_admin():
                yield event.plain_result("/file log update 仅 AstrBot 管理员可用")
                return
            if len(args) < 4:
                yield event.plain_result(
                    "用法: /file log update <name> <version> <内容>（简写 /f l up）\n"
                    "说明: 更新已上传目标文件的版本字段，内容为补充解释更新内容\n"
                    "例: /file log update guoclient 1.2.0 修复了启动崩溃"
                )
                return
            name, version = args[1], args[2]
            # args[0] 是用户实际输入的关键字（update 或缩写 up），据此在原文中定位内容
            marker = f"{args[0]} {name} {version}"
            index = raw.find(marker)
            contents = raw[index + len(marker):].strip() if index >= 0 else " ".join(args[3:])
            ok, message = await self.files.add_changelog(
                name, version, contents, str(event.get_sender_id())
            )
            yield event.plain_result(message)
            return

        name = args[0]
        count = 10
        if len(args) > 1:
            try:
                count = max(1, min(int(args[1]), 100))
            except ValueError:
                yield event.plain_result("次数必须是数字。例: /file log guoclient 20")
                return

        if not self.files.get(name):
            yield event.plain_result(f"文件「{name}」不存在")
            return

        records = self.files.changelog(name, count)
        if not records:
            yield event.plain_result(f"「{name}」暂无更新记录")
            return

        api = OneBotApi(event)
        group_id = event.get_group_id()
        title = f"{name}近{len(records)}次更新记录"

        if api.available and group_id:
            bot_id = str(event.get_self_id() or "10000")
            nodes = [forward_node(bot_id, title, f"【{title}】")]
            for index, record in enumerate(records, start=1):
                stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(record.get("time", 0)))
                nodes.append(
                    forward_node(
                        bot_id,
                        f"v{record.get('version', '?')}",
                        f"#{index} 版本 {record.get('version', '?')}\n"
                        f"时间: {stamp}\n"
                        f"更新内容: {record.get('contents', '')}",
                    )
                )
            # 卡片名称与目标文件保持一致（对应 /merge 的 <标题> 参数）
            news = [
                {
                    "text": f"v{record.get('version', '?')}: "
                    f"{truncate(record.get('contents', ''), 30)}"
                }
                for record in records[:3]
            ]
            sent = await api.send_forward(
                int(group_id),
                nodes,
                source=name,
                news=news,
                summary=f"查看 {len(records)} 条更新记录",
                prompt=f"[{name}]",
            )
            if sent is not None:
                return

        lines = [f"【{title}】"]
        for index, record in enumerate(records, start=1):
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(record.get("time", 0)))
            lines.append(
                f"#{index} v{record.get('version', '?')} | {stamp}\n{record.get('contents', '')}"
            )
        yield event.plain_result("\n\n".join(lines))

    @filter.event_message_type(filter.EventMessageType.ALL, priority=5)
    async def on_file_received(self, event: AstrMessageEvent):
        """接收管理员紧接 /file upload 之后发送的文件。"""
        key = f"{event.get_group_id() or 'private'}:{event.get_sender_id()}"
        pending = self._pending_upload.get(key)
        if not pending:
            return

        if time.time() - pending["created"] > 300:
            self._pending_upload.pop(key, None)
            return

        file_component = None
        for component in event.message_obj.message or []:
            if type(component).__name__ == "File":
                file_component = component
                break
        if file_component is None:
            return

        self._pending_upload.pop(key, None)
        path = getattr(file_component, "file_", None) or getattr(file_component, "file", None)
        original = getattr(file_component, "name", None) or "upload.zip"

        # 必须先把文件落到本地，再去撤回消息 / 删除群文件，否则来不及下载
        if not path or not Path(str(path)).exists():
            try:
                path = await file_component.get_file()
            except Exception as exc:
                logger.error(f"[ZM-QQGroupmgr] 获取文件失败: {exc}")

        if not path or not Path(str(path)).exists():
            await event.send(event.plain_result(f"未能获取文件「{pending['name']}」的本地路径，上传失败"))
            event.stop_event()
            return

        # 群内上传：机器人必须能把文件从群里清掉（群主撤回 / 管理员删群文件），
        # 否则视为上传失败，不入库。
        group_id_str = str(event.get_group_id() or "")
        cleanup = ""
        if group_id_str:
            api = OneBotApi(event)
            bot_role = await self._bot_role(api, group_id_str, event)

            if bot_role == "owner":
                await api.try_ok("delete_msg", message_id=event.message_obj.message_id)
                # 群主同样有权删群文件，顺手清理，失败不影响结果
                await self._delete_group_file(api, group_id_str, file_component)
                cleanup = "\n已撤回群内的文件消息"
                logger.info(f"[ZM-QQGroupmgr] 机器人是群主，已撤回群 {group_id_str} 的上传消息")
            elif bot_role == "admin":
                if not await self._delete_group_file(api, group_id_str, file_component):
                    await event.send(event.plain_result("上传失败：删除群文件失败，请手动删除后重试"))
                    event.stop_event()
                    return
                cleanup = "\n已删除群文件中的该文件"
                logger.info(f"[ZM-QQGroupmgr] 机器人是群管理员，已删除群 {group_id_str} 的群文件")
            else:
                await event.send(
                    event.plain_result(
                        "上传失败：机器人既不是群主也不是群管理员，"
                        "无法撤回消息或删除群文件。请提升机器人权限后重试。"
                    )
                )
                event.stop_event()
                return

        ok, message = await self.files.save_upload(
            pending["name"], str(path), str(original), str(event.get_sender_id()), pending["ttl"]
        )
        detail = ""
        if ok:
            detail = (
                f"\n下载命令: /f dl {pending['name']}（需私聊机器人）"
                f"\n链接有效期: {format_duration(pending['ttl'])}"
                f"{cleanup}"
            )

        await event.send(event.plain_result(message + detail))
        event.stop_event()

    async def _delete_group_file(self, api: OneBotApi, group_id: str, file_component) -> bool:
        """删除群文件，兼容需要 busid 的协议端。"""
        file_id = (
            getattr(file_component, "file_id", None)
            or getattr(file_component, "id", None)
        )
        if not file_id:
            logger.warning("[ZM-QQGroupmgr] 未能取得群文件 file_id，无法删除群文件")
            return False

        # 用 try_ok 而不是"返回值非 None"：delete_group_file 成功时 data 就是
        # null，按返回值判断会把成功当成失败，进而误报"上传失败"。
        busid = getattr(file_component, "busid", None)
        if busid is not None and await api.try_ok(
            "delete_group_file",
            group_id=int(group_id),
            file_id=str(file_id),
            busid=int(busid),
        ):
            return True

        return await api.try_ok(
            "delete_group_file", group_id=int(group_id), file_id=str(file_id)
        )

    # ------------------------------------------------------------------
    # 合并转发伪造
    # ------------------------------------------------------------------

    @filter.command("merge")
    async def cmd_merge(self, event: AstrMessageEvent):
        """/merge <title> <qq> <内容> [<qq> <内容> ...] - 构造合并转发消息"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        # 该命令能以任意 QQ 号的身份伪造聊天记录（含群主、管理员），
        # 默认沿用"全体可用"，需要收紧时把 merge_admin_only 打开。
        if self.config.get("merge_admin_only", False) and not event.is_admin():
            yield event.plain_result("/merge 仅 AstrBot 管理员可用")
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        parts = self._raw_after(event, "merge").split()
        if len(parts) < 3:
            yield event.plain_result(
                "用法: /merge <标题> <qq> <内容> [<qq> <内容> ...]\n"
                "标题即卡片上显示的名字（替换默认的「群聊的聊天记录」），不能带空格\n"
                "例: /merge 关于一个故事 3332 你好呀\n"
                "多人: /merge 关于一个故事 3332 你好 4443 在的"
            )
            return

        title = parts[0]
        # 从第二段开始，遇到 QQ 号就切换发言人，其余内容归当前发言人
        entries: List[tuple] = []
        current_qq = None
        buffer: List[str] = []

        for token in parts[1:]:
            if token.isdigit() and 5 <= len(token) <= 12:
                if current_qq is not None and buffer:
                    entries.append((current_qq, " ".join(buffer)))
                current_qq = token
                buffer = []
            elif current_qq is not None:
                buffer.append(token)

        if current_qq is not None and buffer:
            entries.append((current_qq, " ".join(buffer)))

        if not entries:
            yield event.plain_result("未解析到有效的 <qq> <内容> 组合，请检查格式")
            return

        nodes = []
        for qq, content in entries:
            name = await resolve_member_name(api, int(group_id), qq)
            nodes.append(forward_node(qq, name, content))

        # title 直接作为卡片标题（替换默认的「群聊的聊天记录」），
        # news 为卡片中间的摘要行，取前几条内容预览。
        news = [
            {"text": f"{await resolve_member_name(api, int(group_id), qq)}: {content}"}
            for qq, content in entries[:3]
        ]

        sent = await api.send_forward(
            int(group_id),
            nodes,
            source=title,
            news=news,
            summary=f"查看 {len(entries)} 条转发消息",
            prompt=f"[{title}]",
        )
        if sent is None:
            yield event.plain_result("合并转发发送失败，可能是协议端不支持或内容被拦截")
            return

        logger.info(
            f"[ZM-QQGroupmgr] {event.get_sender_id()} 在群 {group_id} 构造合并转发「{title}」"
            f"，共 {len(entries)} 条"
        )

    # ------------------------------------------------------------------
    # 赛博击杀
    # ------------------------------------------------------------------

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("kill")
    async def cmd_kill(self, event: AstrMessageEvent):
        """/kill <成员> <理由> - 在该成员所在的群同步播报"""
        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        raw = self._raw_after(event, "kill")
        targets = extract_targets(event, raw)
        if not targets:
            yield event.plain_result("用法: /kill <成员> <理由>\n例: /kill @某人 恶意刷屏")
            return

        target = targets[0]
        reason = raw
        for token in list(targets) + [f"@{target}"]:
            reason = reason.replace(token, " ")
        reason = " ".join(reason.split()).strip() or "未说明原因"

        current_group = event.get_group_id()
        template = str(
            self.config.get("kill_template")
            or "检测到 {name}（{target}）因为 {reason} 被赛博击杀，建议管理踢出此成员"
        )

        groups = []
        if self.config.get("kill_notify_all_groups", True):
            for item in await api.group_list():
                gid = str(item.get("group_id") or "")
                if not gid:
                    continue
                info = await api.member_info(int(gid), int(target))
                if info.get("user_id"):
                    groups.append(gid)
        elif current_group:
            groups = [str(current_group)]

        if not groups and current_group:
            groups = [str(current_group)]

        name = target
        if groups:
            name = await resolve_member_name(api, int(groups[0]), target)

        message = template
        # name（群名片）与 reason（命令原文）都可能带 [CQ:...]，填进消息前先转义
        for key, value in {
            "at": f"[CQ:at,qq={target}]",
            "target": target,
            "name": escape_cq(name),
            "reason": escape_cq(reason),
            "operator": str(event.get_sender_id()),
            "group_id": str(current_group or ""),
        }.items():
            message = message.replace("{" + key + "}", value)

        sent = 0
        for gid in groups:
            if await api.send_group_msg(int(gid), message) is not None:
                sent += 1

        if not sent:
            yield event.plain_result("播报失败，未能向任何群发送消息")
            return

        if sent > 1 or (groups and str(current_group) not in groups):
            yield event.plain_result(f"已在 {sent} 个共同群播报对 {name}（{target}）的击杀信息")

    # ------------------------------------------------------------------
    # 自动检测：刷屏 / 敏感词 / 名片
    # ------------------------------------------------------------------

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=1)
    async def on_group_message(self, event: AstrMessageEvent):
        """群消息自动检测入口。"""
        group_id = self._require_group(event)
        if not group_id:
            return

        api = OneBotApi(event)
        if not api.available:
            return

        user_id = str(event.get_sender_id())
        text = event.message_str or ""
        self._record_message(event)

        # 入群验证优先于其他检测：验证码本身可能长得像刷屏或广告
        if await self._check_verify(event, api, group_id, user_id, text):
            return

        # 管理员自己不受自动检测约束
        if event.is_admin():
            return

        # 封禁名单成员直接踢出
        if user_id in self._ban_list(group_id):
            try:
                await api.kick(int(group_id), int(user_id), reject=True)
                logger.info(f"[ZM-QQGroupmgr] 封禁用户 {user_id} 在群 {group_id} 发言，已踢出")
            except RuntimeError as exc:
                logger.warning(f"[ZM-QQGroupmgr] 踢出封禁用户失败: {exc}")
            event.stop_event()
            return

        if await self._check_sensitive(event, api, group_id, user_id, text):
            return
        if await self._check_ad(event, api, group_id, user_id, text):
            return
        if await self._check_flood(event, api, group_id, user_id, text):
            return
        await self._check_card(event, api, group_id, user_id)

    async def _check_ad(self, event, api, group_id, user_id, text) -> bool:
        """广告评分命中则撤回 + 禁言，返回是否已处理。"""
        if not self.adban_toggle.is_enabled(group_id) or not text:
            return False

        threshold = coerce_int(self.config.get("ad_threshold"), 6)
        score = ad_score(text)
        if score < threshold:
            return False

        duration = coerce_int(self.config.get("ad_mute_duration"), 600)
        await self._punish(
            event, api, group_id, user_id, duration, f"广告评分 {score}", recall=True
        )

        tip = self.config.get("ad_tip") or "{at} 消息被判定为广告（评分 {score}），已撤回并禁言 {duration}"
        await api.send_group_msg(
            int(group_id),
            self._render(
                tip,
                event,
                score=str(score),
                duration="永久" if duration == 0 else format_duration(duration),
            ),
        )
        logger.info(
            f"[ZM-QQGroupmgr] 群 {group_id} 成员 {user_id} 触发广告拦截（评分 {score}）"
        )
        event.stop_event()
        return True

    async def _check_sensitive(self, event, api, group_id, user_id, text) -> bool:
        """敏感词命中则撤回 + 禁言，返回是否已处理。"""
        if not self.sw_toggle.is_enabled(group_id) or not text:
            return False

        word = await self.sensitive.check(group_id, text)
        if not word:
            return False

        duration = int(self.sw_toggle.value(group_id, "duration", 600))
        await self._punish(
            event, api, group_id, user_id, duration, f"敏感词: {word}", recall=True
        )

        tip = self.config.get("sensitive_tip") or "{at} 消息包含敏感内容，已撤回并禁言 {duration}"
        message = self._render(
            tip,
            event,
            word=word,
            duration="永久" if duration == 0 else format_duration(duration),
        )
        await api.send_group_msg(int(group_id), message)
        logger.info(
            f"[ZM-QQGroupmgr] 群 {group_id} 成员 {user_id} 命中敏感词「{word}」"
            f"，已撤回并禁言 {duration} 秒"
        )
        event.stop_event()
        return True

    async def _check_flood(self, event, api, group_id, user_id, text) -> bool:
        """刷屏命中则按配置撤回 + 禁言，返回是否已处理。"""
        if not self.flood_toggle.is_enabled(group_id):
            return False

        self.flood.configure(
            coerce_int(self.config.get("flood_threshold"), 5),
            coerce_int(self.config.get("flood_window"), 10),
            coerce_int(self.config.get("flood_repeat_limit"), 3),
        )
        reason = self.flood.record(group_id, user_id, text)
        if not reason:
            return False

        duration = int(
            self.flood_toggle.value(
                group_id, "duration", coerce_int(self.config.get("flood_mute_duration"), 600)
            )
        )
        await self._punish(
            event,
            api,
            group_id,
            user_id,
            duration,
            f"刷屏: {reason}",
            recall=bool(self.config.get("flood_recall", True)),
        )

        tip = self.config.get("flood_tip") or "{at} 检测到刷屏（{reason}），已禁言 {duration}"
        message = self._render(
            tip,
            event,
            reason=reason,
            duration="永久" if duration == 0 else format_duration(duration),
        )
        await api.send_group_msg(int(group_id), message)
        logger.info(f"[ZM-QQGroupmgr] 群 {group_id} 成员 {user_id} 触发刷屏检测: {reason}")
        event.stop_event()
        return True

    async def _check_card(self, event, api, group_id, user_id) -> None:
        """检测群名片是否含广告或敏感词。"""
        if not (
            self.card_toggle.is_enabled(group_id)
            or self.config.get("card_check_enabled", False)
        ):
            return

        card = ""
        try:
            card = str(getattr(event.message_obj.sender, "card", "") or "")
        except AttributeError:
            card = ""
        if not card:
            info = await api.member_info(int(group_id), int(user_id))
            card = str(info.get("card") or "")
        if not card or not self.cards.should_check(group_id, user_id, card):
            return

        reason = ""
        threshold = coerce_int(self.config.get("card_ad_threshold"), 4)
        score = ad_score(card)
        if score >= threshold:
            reason = f"广告特征评分 {score}"
        else:
            word = await self.sensitive.check(group_id, card)
            if word:
                reason = f"敏感词: {word}"
        if not reason:
            return

        action = str(self.config.get("card_action") or "warn").lower()
        tip = self.config.get("card_tip") or "{at} 你的群名片（{card}）疑似包含违规内容（{reason}），请及时修改"
        message = self._render(tip, event, card=truncate(card, 30), reason=reason)

        if action == "reset":
            await api.try_call(
                "set_group_card", group_id=int(group_id), user_id=int(user_id), card=""
            )
            message += "\n已清空你的群名片"
        elif action == "mute":
            duration = coerce_int(self.config.get("card_mute_duration"), 600)
            try:
                await api.mute(int(group_id), int(user_id), chunk_duration(duration))
                await self.mutes.record(group_id, user_id, duration, f"名片违规: {reason}", "自动检测")
                message += f"\n已禁言 {format_duration(duration)}"
            except RuntimeError as exc:
                logger.warning(f"[ZM-QQGroupmgr] 名片违规禁言失败: {exc}")
        elif action == "kick":
            try:
                await api.kick(int(group_id), int(user_id))
                message += "\n已移出本群"
            except RuntimeError as exc:
                logger.warning(f"[ZM-QQGroupmgr] 名片违规踢出失败: {exc}")

        await api.send_group_msg(int(group_id), message)
        logger.info(f"[ZM-QQGroupmgr] 群 {group_id} 成员 {user_id} 名片违规: {reason}")

    # ------------------------------------------------------------------
    # 成员管理（踢出 / 封禁 / 管理员 / 头衔）
    # ------------------------------------------------------------------

    def _ban_list(self, group_id: str) -> List[str]:
        bucket = self.settings.group(str(group_id))
        banned = bucket.get("banlist")
        if not isinstance(banned, list):
            banned = []
            bucket["banlist"] = banned
        return banned

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("kick")
    async def cmd_kick(self, event: AstrMessageEvent):
        """/kick <成员> - 踢出成员；/kick <时间> - 清理不活跃成员"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        raw = self._raw_after(event, "kick")
        targets = extract_targets(event, raw)

        if targets:
            succeeded, failed = [], []
            for user_id in targets:
                try:
                    await api.kick(int(group_id), int(user_id))
                    succeeded.append(user_id)
                except RuntimeError as exc:
                    failed.append(f"{user_id}({exc})")
            lines = []
            if succeeded:
                lines.append(f"已踢出: {', '.join(succeeded)}")
            if failed:
                lines.append(f"失败: {', '.join(failed)}")
            yield event.plain_result("\n".join(lines))
            return

        # 无目标时按"清理 N 天未发言"处理
        threshold = parse_duration(raw, default_unit="d") if raw else None
        if not threshold:
            yield event.plain_result(
                "用法: /kick <成员> 踢出成员\n"
                "      /kick <时间> 清理该时长内未发言的成员（例: /kick 20d）"
            )
            return

        members = await api.member_list(int(group_id))
        if not members:
            yield event.plain_result("无法获取群成员列表，操作已取消")
            return

        now = int(time.time())
        self_id = str(event.get_self_id() or "")
        stale = []
        for member in members:
            uid = str(member.get("user_id") or "")
            if not uid or uid == self_id:
                continue
            if str(member.get("role") or "member") != "member":
                continue
            last = member.get("last_sent_time") or member.get("join_time") or 0
            try:
                last = int(last)
            except (TypeError, ValueError):
                continue
            if last and now - last >= threshold:
                stale.append(uid)

        if not stale:
            yield event.plain_result(f"没有超过 {format_duration(threshold)} 未发言的普通成员")
            return

        removed = 0
        for uid in stale:
            try:
                await api.kick(int(group_id), int(uid))
                removed += 1
                await asyncio.sleep(0.5)
            except RuntimeError:
                continue
        yield event.plain_result(
            f"已清理 {removed}/{len(stale)} 名超过 {format_duration(threshold)} 未发言的成员"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("ban")
    async def cmd_ban(self, event: AstrMessageEvent):
        """/ban <成员> - 封禁并踢出，后续自动拒绝加群"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        targets = extract_targets(event, self._raw_after(event, "ban"))
        if not targets:
            yield event.plain_result("用法: /ban <成员>")
            return

        banned = self._ban_list(group_id)
        added = []
        for user_id in targets:
            if user_id not in banned:
                banned.append(user_id)
            added.append(user_id)
            try:
                await api.kick(int(group_id), int(user_id), reject=True)
            except RuntimeError as exc:
                logger.warning(f"[ZM-QQGroupmgr] 封禁踢出失败 {user_id}: {exc}")
        await self.settings.save()
        yield event.plain_result(
            f"已封禁 {len(added)} 人: {', '.join(added)}\n后续加群申请将被自动拒绝"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("unban")
    async def cmd_unban(self, event: AstrMessageEvent):
        """/unban <QQ号> - 解除封禁"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        targets = extract_targets(event, self._raw_after(event, "unban"))
        if not targets:
            yield event.plain_result("用法: /unban <QQ号>")
            return

        banned = self._ban_list(group_id)
        removed = [uid for uid in targets if uid in banned]
        for uid in removed:
            banned.remove(uid)
        await self.settings.save()

        if not removed:
            yield event.plain_result("这些用户不在封禁列表中")
            return
        yield event.plain_result(f"已解除封禁: {', '.join(removed)}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("banlist")
    async def cmd_banlist(self, event: AstrMessageEvent):
        """/banlist - 查看封禁列表"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        banned = self._ban_list(group_id)
        if not banned:
            yield event.plain_result("本群封禁列表为空")
            return
        yield event.plain_result(
            f"本群封禁列表（共 {len(banned)} 人）\n" + "\n".join(f"· {uid}" for uid in banned)
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("op")
    async def cmd_op(self, event: AstrMessageEvent):
        """/op <成员> - 设置群管理员"""
        async for result in self._toggle_admin(event, "op", True):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("deop")
    async def cmd_deop(self, event: AstrMessageEvent):
        """/deop <成员> - 取消群管理员"""
        async for result in self._toggle_admin(event, "deop", False):
            yield result

    async def _toggle_admin(self, event: AstrMessageEvent, command: str, enable: bool):
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        targets = extract_targets(event, self._raw_after(event, command))
        if not targets:
            yield event.plain_result(f"用法: /{command} <成员>")
            return

        succeeded, failed = [], []
        for user_id in targets:
            try:
                await api.set_admin(int(group_id), int(user_id), enable)
                succeeded.append(user_id)
            except RuntimeError as exc:
                failed.append(f"{user_id}({exc})")

        lines = []
        if succeeded:
            lines.append(
                f"已{'设置' if enable else '取消'}管理员: {', '.join(succeeded)}"
            )
        if failed:
            lines.append(f"失败: {', '.join(failed)}（此操作通常需要群主权限）")
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("title")
    async def cmd_title(self, event: AstrMessageEvent):
        """/title @成员 <文本> - 设置群头衔；/title unset @成员 - 取消"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        raw = self._raw_after(event, "title")
        parts = raw.split()
        unset = bool(parts) and parts[0].lower() in {"unset", "clear", "取消"}
        targets = extract_targets(event, raw)
        if not targets:
            yield event.plain_result(
                "用法: /title @成员 <文本>\n      /title unset @成员"
            )
            return

        user_id = targets[0]
        if unset:
            title = ""
        else:
            title = raw
            for token in targets:
                title = title.replace(token, " ")
            # 头衔是 API 参数、不进消息文本，转义反而会把实体码写进头衔
            title = self._render(" ".join(title.split()).strip(), event, escape=False)
            if not title:
                yield event.plain_result("请提供头衔文本，或使用 /title unset @成员 取消")
                return

        try:
            await api.set_title(int(group_id), int(user_id), title)
        except RuntimeError as exc:
            yield event.plain_result(f"设置头衔失败: {exc}（此操作通常需要群主权限）")
            return

        yield event.plain_result(
            f"已取消 {user_id} 的群头衔" if unset else f"已为 {user_id} 设置头衔「{title}」"
        )

    # ------------------------------------------------------------------
    # 消息撤回
    # ------------------------------------------------------------------

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("recall")
    async def cmd_recall(self, event: AstrMessageEvent):
        """/recall - 撤回被回复的消息；/recall <数量> [是否包含机器人] - 批量撤回近期消息"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        # 优先处理引用回复
        target_id = self._reply_id(event)
        if target_id is not None:
            ok, error = await api.recall_detail(target_id)
            if not ok:
                yield event.plain_result(
                    f"撤回失败: {error or '协议端未返回原因'}"
                    "（消息可能已被撤回，或机器人权限不足）"
                )
                return
            # 顺带撤回 /recall 指令本身
            await api.try_call("delete_msg", message_id=event.message_obj.message_id)
            return

        args = self._args(event, "recall")
        if not args:
            yield event.plain_result(
                "用法: 回复某条消息后使用 /recall\n"
                "      或 /recall <数量> [是否包含机器人]\n"
                "      例: /recall 5 或 /recall 5 false（不包含机器人）"
            )
            return

        try:
            count = max(1, min(int(args[0]), 50))
        except ValueError:
            yield event.plain_result("数量必须是数字。例: /recall 5 或 /recall 5 false")
            return

        # 解析第二个参数：是否包含机器人本身的消息
        include_bot = True
        if len(args) > 1:
            arg_lower = args[1].lower()
            if arg_lower in {"false", "f", "0", "no", "否"}:
                include_bot = False

        bot_id = str(event.get_self_id() or "")
        self_message_id = event.message_obj.message_id

        pending, source = await self._recall_targets(
            api, group_id, count, include_bot, bot_id, self_message_id
        )

        if not pending:
            yield event.plain_result(
                "没有可撤回的消息（协议端未返回历史记录，且插件内存中也没有记录）"
            )
            return

        removed = 0
        failures: List[str] = []
        # 从新到旧逐条撤回
        for item in reversed(pending):
            ok, error = await api.recall_detail(item["message_id"])
            if ok:
                removed += 1
                continue
            who = item.get("user_id") or "?"
            failures.append(f"{item['message_id']}(发送者 {who}): {error or '协议端未返回原因'}")

        await api.try_call("delete_msg", message_id=self_message_id)

        total = len(pending)
        logger.info(
            f"[ZM-QQGroupmgr] 群 {group_id} 批量撤回：来源 {source}，"
            f"目标 {total} 条，成功 {removed} 条，失败 {len(failures)} 条"
        )
        for line in failures:
            logger.warning(f"[ZM-QQGroupmgr] 群 {group_id} 撤回失败 {line}")

        if not failures:
            yield event.plain_result(f"已撤回 {removed} 条消息")
            return

        report = [f"撤回完成：成功 {removed} 条，失败 {len(failures)} 条（共 {total} 条）"]
        for line in failures[:5]:
            report.append(f"· {line}")
        if len(failures) > 5:
            report.append(f"· 其余 {len(failures) - 5} 条失败详情见日志")
        report.append("失败通常是消息已被撤回/已过期，或机器人权限不足（需群管理员或群主）")
        yield event.plain_result("\n".join(report))

    async def _recall_targets(
        self,
        api: OneBotApi,
        group_id: str,
        count: int,
        include_bot: bool,
        bot_id: str,
        skip_message_id,
    ) -> tuple:
        """挑出待撤回的消息，返回 (消息列表, 来源说明)。

        优先向协议端拉取群历史记录——这样机器人自己发的消息、以及插件启动前
        的消息都能撤回；协议端不支持时退回插件内存里的记录。
        """
        raw = await api.group_msg_history(int(group_id), max(count * 2, 20))
        source = "协议端历史记录"
        items: List[dict] = []

        for message in raw:
            if not isinstance(message, dict):
                continue
            message_id = message.get("message_id")
            if message_id is None:
                continue
            sender = message.get("sender")
            user_id = ""
            if isinstance(sender, dict):
                user_id = str(sender.get("user_id") or "")
            if not user_id:
                user_id = str(message.get("user_id") or "")
            items.append({"message_id": message_id, "user_id": user_id})

        if not items:
            source = "插件内存记录"
            items = [
                {"message_id": item["message_id"], "user_id": item["user_id"]}
                for item in self._message_history.get(group_id, [])
            ]

        # 去重并保持时间顺序（旧 → 新）
        seen = set()
        ordered: List[dict] = []
        for item in items:
            key = str(item["message_id"])
            if key in seen:
                continue
            seen.add(key)
            ordered.append(item)

        # 跳过 /recall 指令自身，它在最后单独撤回
        ordered = [
            item
            for item in ordered
            if str(item["message_id"]) != str(skip_message_id)
        ]

        if not include_bot and bot_id:
            ordered = [item for item in ordered if item["user_id"] != bot_id]

        return ordered[-count:], source

    # ------------------------------------------------------------------
    # 群广告与欢迎
    # ------------------------------------------------------------------

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("ad")
    async def cmd_ad(self, event: AstrMessageEvent):
        """/ad - 发布广告；/ad set <文本> | /ad clear | /ad reset"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        bucket = self.settings.group(group_id)
        raw = self._raw_after(event, "ad")
        parts = raw.split()

        if not parts:
            content = (bucket.get("ad") or {}).get("content")
            if not content:
                yield event.plain_result("本群尚未设置广告，可用 /ad set <文本> 设置")
                return
            yield event.plain_result(self._render(content, event))
            return

        action = parts[0].lower()
        rest = raw[len(parts[0]):].strip()

        if action == "set":
            if not rest:
                yield event.plain_result("用法: /ad set <文本>")
                return
            bucket["ad"] = {"content": rest, "updated_at": int(time.time())}
            await self.settings.save()
            yield event.plain_result("广告已保存，使用 /ad 发布")
            return

        if action == "clear":
            bucket.pop("ad", None)
            await self.settings.save()
            yield event.plain_result("广告已清空")
            return

        if action == "reset":
            default_ad = "这是一条默认广告，请使用 /ad set 设置自定义广告"
            bucket["ad"] = {"content": default_ad, "updated_at": int(time.time())}
            await self.settings.save()
            yield event.plain_result("已恢复默认广告")
            return

        yield event.plain_result("未知子命令，可用: set, clear, reset")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("adban")
    async def cmd_adban(self, event: AstrMessageEvent):
        """/adban [on|off] - 广告拦截开关"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        args = self._args(event, "adban")
        action = args[0].lower() if args else ""

        if action == "on":
            await self.adban_toggle.enable(group_id)
            yield event.plain_result("广告拦截已开启（评分 ≥ 6 判定为广告，撤回并禁言 10 分钟）")
            return
        if action == "off":
            await self.adban_toggle.disable(group_id)
            yield event.plain_result("广告拦截已关闭")
            return

        # 无参数时切换开关，保持原有行为
        if self.adban_toggle.is_enabled(group_id):
            await self.adban_toggle.disable(group_id)
            yield event.plain_result("广告拦截已关闭")
        else:
            await self.adban_toggle.enable(group_id)
            yield event.plain_result("广告拦截已开启")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("wel")
    async def cmd_welcome(self, event: AstrMessageEvent):
        """/wel - 预览欢迎语；/wel set <文本> | on | off | reset | status"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        bucket = self.settings.group(group_id)
        welcome = bucket.get("welcome")
        if not isinstance(welcome, dict):
            welcome = {}
            bucket["welcome"] = welcome

        raw = self._raw_after(event, "wel")
        parts = raw.split()

        if not parts:
            content = welcome.get("content")
            if not content:
                yield event.plain_result("尚未设置欢迎消息，可用 /wel set <文本> 设置")
                return
            yield event.plain_result(self._render(content, event))
            return

        action = parts[0].lower()
        rest = raw[len(parts[0]):].strip()

        if action == "set":
            if not rest:
                yield event.plain_result("用法: /wel set <文本>，支持 {at} {name} {user_id} {group_id}")
                return
            welcome.update({"content": rest, "enabled": True})
            await self.settings.save()
            yield event.plain_result("欢迎消息已保存并开启自动欢迎")
            return

        if action == "on":
            if not welcome.get("content"):
                welcome["content"] = "欢迎 {at} 加入本群！"
            welcome["enabled"] = True
            await self.settings.save()
            yield event.plain_result("自动入群欢迎已开启")
            return

        if action == "off":
            welcome["enabled"] = False
            await self.settings.save()
            yield event.plain_result("自动入群欢迎已关闭")
            return

        if action == "reset":
            welcome.update({"content": "欢迎 {at} 加入本群！", "enabled": True})
            await self.settings.save()
            yield event.plain_result("已恢复默认欢迎内容")
            return

        if action == "status":
            yield event.plain_result(
                "欢迎消息状态\n"
                f"开关: {'开启' if welcome.get('enabled') else '关闭'}\n"
                f"内容: {welcome.get('content') or '（未设置）'}"
            )
            return

        yield event.plain_result("未知子命令，可用: set, on, off, reset, status")

    # ------------------------------------------------------------------
    # 群资料管理 /group
    # ------------------------------------------------------------------

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("group", alias={"g"})
    async def cmd_group(self, event: AstrMessageEvent):
        """/group newname <文本> [群号] | /group pp [图片] [群号]"""
        raw = self._raw_after(event, "group", "g")
        parts = raw.split()
        action = GROUP_ACTION_ALIASES.get(parts[0].lower(), parts[0].lower()) if parts else ""

        if action not in {"newname", "pp"}:
            yield event.plain_result(GROUP_USAGE)
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        # 动作词后面的原文，保留空格与换行，交给各自的解析逻辑
        rest = raw[len(parts[0]):].strip()

        if action == "newname":
            async for result in self._group_newname(event, api, rest):
                yield result
            return

        async for result in self._group_avatar(event, api, rest):
            yield result

    async def _group_newname(self, event: AstrMessageEvent, api: OneBotApi, rest: str):
        """/group newname <文本> [qq群号] - 修改一个或多个群的名称。"""
        name, ids = split_trailing_group_ids(rest)
        # 群名不能换行，粘贴多行文本时压成一行而不是直接报错
        name = " ".join(name.split())

        if not name:
            yield event.plain_result(GROUP_USAGE)
            return
        if len(name) > MAX_GROUP_NAME:
            yield event.plain_result(
                f"群名过长（{len(name)} 字），请控制在 {MAX_GROUP_NAME} 字以内"
            )
            return

        targets, error = self._resolve_group_targets(event, ids)
        if error:
            yield event.plain_result(error)
            return

        succeeded, failed = [], []
        for index, group_id in enumerate(targets):
            if index:
                await asyncio.sleep(BATCH_INTERVAL)
            try:
                await api.set_group_name(int(group_id), name)
                succeeded.append(group_id)
            except RuntimeError as exc:
                failed.append(f"{group_id}({truncate(str(exc), 30)})")

        logger.info(
            f"[ZM-QQGroupmgr] {event.get_sender_id()} 将 {len(succeeded)} 个群改名为「{name}」"
        )
        yield event.plain_result(
            self._batch_report(f"群名称已改为「{name}」", succeeded, failed)
        )

    async def _group_avatar(self, event: AstrMessageEvent, api: OneBotApi, rest: str):
        """/group pp [图片] [qq群号] - 修改群头像，未带图片则等待补发。"""
        ids, leftover = None, ""
        if rest:
            # 整段就是群号（/g pp 3366-1009-10032），或末尾才是群号
            # （/g pp 图片.png 3366-1009-10032，图片名是手机端粘贴留下的文字）
            ids = parse_group_ids(rest)
            if ids is None:
                leftover, ids = split_trailing_group_ids(rest)
            if ids is None:
                # 参数解析不出群号就直接报错。若在这里退回"当前群"，
                # /g pp 1234x 这种笔误会悄悄把本群头像换掉。
                yield event.plain_result(
                    f"无法识别的群号「{truncate(rest, 30)}」\n\n{GROUP_USAGE}"
                )
                return

        targets, error = self._resolve_group_targets(event, ids)
        if error:
            yield event.plain_result(error)
            return

        note = f"\n（已忽略无关参数「{truncate(leftover, 20)}」）" if leftover else ""

        images = extract_images(event)
        if images:
            async for result in self._apply_avatar(
                event, api, targets, images[0], event.message_obj.message_id
            ):
                yield result
            return

        timeout = self._arm_pending(
            event, "更换群头像", kind="avatar", targets=targets
        )
        yield event.plain_result(
            f"{format_duration(timeout)}内 请发送图片 否则上传失败\n"
            f"目标群（{len(targets)} 个）: {', '.join(targets)}{note}"
        )

    async def _apply_avatar(
        self,
        event: AstrMessageEvent,
        api: OneBotApi,
        targets: List[str],
        image,
        recall_message_id,
    ):
        """真正执行换头像，并按开关撤回承载图片的那条消息。"""
        candidates, _, temp, error = await self._prepare_image(image)
        if error:
            yield event.plain_result(f"更换群头像失败: {error}")
            return

        try:
            succeeded, failed = [], []
            for index, group_id in enumerate(targets):
                if index:
                    await asyncio.sleep(BATCH_INTERVAL)
                ok, reason = await api.set_group_portrait(int(group_id), candidates)
                if ok:
                    succeeded.append(group_id)
                else:
                    failed.append(f"{group_id}({truncate(reason, 30)})")
        finally:
            cleanup_temp(temp)

        lines = [self._batch_report("群头像已更换", succeeded, failed)]
        if succeeded:
            note = await self._recall_media(event, api, recall_message_id, "avatar_recall")
            if note:
                lines.append(note)
            lines.append("提示: 部分协议端即使返回成功也可能被腾讯侧拒绝，请自行确认效果")

        logger.info(
            f"[ZM-QQGroupmgr] {event.get_sender_id()} 为 {len(succeeded)} 个群更换了头像"
        )
        yield event.plain_result("\n".join(lines))

    @staticmethod
    def _batch_report(title: str, succeeded: List[str], failed: List[str]) -> str:
        """批量操作的统一回执。"""
        lines = []
        if succeeded:
            lines.append(f"{title}（{len(succeeded)} 个群）: {', '.join(succeeded)}")
        if failed:
            lines.append(f"失败 {len(failed)} 个: {'; '.join(failed)}")
        if not lines:
            lines.append(f"{title}：没有任何群操作成功")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 群公告 /broadcast
    # ------------------------------------------------------------------

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("broadcast", alias={"bc"})
    async def cmd_broadcast(self, event: AstrMessageEvent):
        """/broadcast <内容> <是否置顶公告> - 发布群公告"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        raw = self._raw_after(event, "broadcast", "bc")
        images = extract_images(event)
        content, pinned = split_trailing_bool(raw)

        if pinned is None:
            yield event.plain_result(
                ("缺少 <是否置顶公告> 参数，最后必须是 true 或 false\n\n" if raw else "")
                + BROADCAST_USAGE
            )
            return
        if not content and not images:
            yield event.plain_result("公告内容不能为空\n\n" + BROADCAST_USAGE)
            return

        # 内容里已经带图（电脑端直接粘贴）就一步到位，不再追问
        if images:
            async for result in self._send_notice(
                event, api, group_id, content, pinned, images[0], event.message_obj.message_id
            ):
                yield result
            return

        timeout = self._arm_pending(
            event, "发布群公告", kind="notice_ask", group_id=group_id,
            content=content, pinned=pinned,
        )
        yield event.plain_result(
            "公告文本已记录，检测到内容中没有图片。\n"
            "是否需要上传图片？请回答「是」或「否」\n"
            f"（{format_duration(timeout)}内未回答则指令失效）"
        )

    async def _send_notice(
        self,
        event: AstrMessageEvent,
        api: OneBotApi,
        group_id: str,
        content: str,
        pinned: bool,
        image,
        recall_message_id,
    ):
        """发布群公告，image 为 None 时只发文本。"""
        payload = None
        if image is not None:
            candidates, _, _, error = await self._prepare_image(image, with_file=False)
            if error:
                yield event.plain_result(f"发布群公告失败: {error}")
                return
            payload = candidates[0]

        ok, note = await api.send_group_notice(
            int(group_id), content, image=payload, pinned=pinned
        )

        if not ok:
            yield event.plain_result(
                "发布群公告失败：协议端拒绝了请求。\n"
                "请确认机器人在本群是群主或管理员，且协议端支持 _send_group_notice"
            )
            return

        lines = [
            f"群公告已发布（{'已置顶' if pinned else '未置顶'}"
            f"{'，含图片' if image is not None else '，纯文本'}）"
        ]
        if note:
            lines.append(note)
        if image is not None:
            recall = await self._recall_media(
                event, api, recall_message_id, "broadcast_recall"
            )
            if recall:
                lines.append(recall)

        logger.info(f"[ZM-QQGroupmgr] {event.get_sender_id()} 在群 {group_id} 发布了公告")
        yield event.plain_result("\n".join(lines))

    # ------------------------------------------------------------------
    # 退群提示 /bye
    # ------------------------------------------------------------------

    def _farewell(self, group_id: str) -> dict:
        bucket = self.settings.group(str(group_id))
        state = bucket.get("farewell")
        if not isinstance(state, dict):
            state = {}
            bucket["farewell"] = state
        return state

    @staticmethod
    def _farewell_dir():
        return get_data_dir() / "farewell"

    @staticmethod
    def _farewell_stem(group_id: str) -> str:
        """群号用作文件名前，先剥掉非数字字符，杜绝路径穿越。"""
        return "".join(ch for ch in str(group_id) if ch.isdigit()) or "unknown"

    def _farewell_image(self, group_id: str, state: dict):
        """取该群的退群提示图，文件被手工删掉时返回 None。"""
        name = state.get("image")
        if not name:
            return None
        # 只按文件名取，忽略存量数据里可能混进的路径分隔符
        path = self._farewell_dir() / Path(str(name)).name
        return path if path.is_file() else None

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("bye", alias={"farewell", "退群提示"})
    async def cmd_farewell_config(self, event: AstrMessageEvent):
        """/bye - 退群提示的开关与内容设置"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        state = self._farewell(group_id)
        raw = self._raw_after(event, "bye", "farewell", "退群提示")
        parts = raw.split()

        if not parts:
            content = state.get("content")
            if not content:
                yield event.plain_result("尚未设置退群提示\n\n" + FAREWELL_USAGE)
                return
            has_image = self._farewell_image(group_id, state) is not None
            yield event.plain_result(
                f"当前退群提示（{'开启' if state.get('enabled') else '关闭'}）:\n"
                f"{content}\n"
                f"附带图片: {'有' if has_image else '无'}"
            )
            return

        action = parts[0].lower()
        rest = raw[len(parts[0]):].strip()

        if action == "set":
            if not rest:
                yield event.plain_result("用法: /bye set <文本>\n占位符: {at} {name} {user_id} {group_id} {reason} {operator}")
                return
            state.update({"content": rest, "enabled": True})
            await self.settings.save()
            yield event.plain_result("退群提示已保存并开启")
            return

        if action == "image":
            async for result in self._farewell_image_cmd(event, group_id, state, rest):
                yield result
            return

        if action == "on":
            if not state.get("content"):
                state["content"] = DEFAULT_FAREWELL
            state["enabled"] = True
            await self.settings.save()
            yield event.plain_result("退群提示已开启")
            return

        if action == "off":
            state["enabled"] = False
            await self.settings.save()
            yield event.plain_result("退群提示已关闭")
            return

        if action == "reset":
            state.update({"content": DEFAULT_FAREWELL, "enabled": True})
            await self.settings.save()
            yield event.plain_result("已恢复默认退群提示并开启（图片设置保持不变）")
            return

        if action == "status":
            has_image = self._farewell_image(group_id, state) is not None
            yield event.plain_result(
                "退群提示状态\n"
                f"开关: {'开启' if state.get('enabled') else '关闭'}\n"
                f"内容: {state.get('content') or '（未设置）'}\n"
                f"图片: {'已设置' if has_image else '未设置'}"
            )
            return

        yield event.plain_result(FAREWELL_USAGE)

    async def _farewell_image_cmd(
        self, event: AstrMessageEvent, group_id: str, state: dict, rest: str
    ):
        """/bye image [clear] - 设置或清除退群提示的附带图片。"""
        if rest.lower() in {"clear", "del", "delete", "remove", "off", "清除"}:
            path = self._farewell_image(group_id, state)
            if path is not None:
                try:
                    path.unlink()
                except OSError:
                    pass
            state.pop("image", None)
            await self.settings.save()
            yield event.plain_result("退群提示的附带图片已清除")
            return

        images = extract_images(event)
        if images:
            async for result in self._save_farewell_image(event, group_id, images[0]):
                yield result
            return

        timeout = self._arm_pending(
            event, "设置退群提示图片", kind="farewell_image", group_id=group_id
        )
        yield event.plain_result(
            f"{format_duration(timeout)}内 请发送图片 否则上传失败"
        )

    async def _save_farewell_image(self, event: AstrMessageEvent, group_id: str, image):
        """把图片落到插件数据目录，退群时再读出来发送。"""
        data, error = await image_bytes(image)
        if error or not data:
            yield event.plain_result(f"设置失败: {error or '未能读取图片内容'}")
            return

        ext = guess_image_ext(data)
        if ext is None:
            yield event.plain_result("无法识别的图片格式，仅支持 jpg / png / gif / bmp / webp")
            return

        path = save_named_image(
            data, self._farewell_dir(), self._farewell_stem(group_id), ext
        )
        if path is None:
            yield event.plain_result("保存图片失败，请查看后台日志")
            return

        state = self._farewell(group_id)
        state["image"] = path.name
        if not state.get("content"):
            state["content"] = DEFAULT_FAREWELL
        await self.settings.save()

        api = OneBotApi(event)
        note = await self._recall_media(
            event, api, event.message_obj.message_id, "farewell_recall"
        )
        lines = [
            f"退群提示图片已设置（{format_size(len(data))}）",
            "退群提示当前为关闭状态，用 /bye on 开启" if not state.get("enabled") else "",
            note,
        ]
        yield event.plain_result("\n".join(line for line in lines if line))

    # ------------------------------------------------------------------
    # 两步指令：等待补发的图片与确认答复
    # ------------------------------------------------------------------

    @filter.event_message_type(filter.EventMessageType.ALL, priority=5)
    async def on_pending_media(self, event: AstrMessageEvent):
        """接收 /group pp、/broadcast、/bye image 之后补发的图片与答复。"""
        key = session_key(event)
        pending = self._pending_media.peek(key)
        if not pending:
            return

        kind_now = pending.get("kind")
        if kind_now == "notice_ask":
            await self._handle_notice_answer(event, key, pending)
            return
        if kind_now == "ja_repo":
            await self._handle_ja_repo(event, key, pending)
            return
        if kind_now == "ja_confirm":
            await self._handle_ja_confirm(event, key, pending)
            return

        # 等的是图片，这条消息里没有就继续等，别把中间的闲聊吃掉
        images = extract_images(event)
        if not images:
            return
        # 带图的指令交给指令本身处理，否则重新执行 /g pp [图片] <新群号>
        # 会被旧登记抢走、按旧群号执行
        if self._looks_like_command(event):
            return

        self._pending_media.drop(key)
        api = OneBotApi(event)
        if not api.available:
            await event.send(event.plain_result(QQ_ONLY))
            event.stop_event()
            return

        kind = pending.get("kind")
        if kind == "avatar":
            async for result in self._apply_avatar(
                event, api, pending.get("targets") or [], images[0],
                event.message_obj.message_id,
            ):
                await event.send(result)
        elif kind == "notice_image":
            async for result in self._send_notice(
                event, api, str(pending.get("group_id")), pending.get("content") or "",
                bool(pending.get("pinned")), images[0], event.message_obj.message_id,
            ):
                await event.send(result)
        elif kind == "farewell_image":
            async for result in self._save_farewell_image(
                event, str(pending.get("group_id")), images[0]
            ):
                await event.send(result)

        event.stop_event()

    async def _handle_notice_answer(self, event: AstrMessageEvent, key: str, pending: dict):
        """/broadcast 只发了文本时，处理“要不要配图”的答复。

        只认严格相等的「是」「否」，其余一律放行。不能靠"以 / 开头"来区分
        指令：AstrBot 有时已经把唤醒前缀从 ``message_str`` 里剥掉了，照那样
        判断会把等待期内的其他指令当成答复吃掉并 ``stop_event``。
        """
        answer = (event.message_str or "").strip().lower()
        if not answer or (answer not in YES_WORDS and answer not in NO_WORDS):
            return

        api = OneBotApi(event)

        if answer in YES_WORDS:
            timeout = self._arm_pending(
                event, "发布群公告", kind="notice_image",
                group_id=pending.get("group_id"),
                content=pending.get("content"),
                pinned=pending.get("pinned"),
            )
            await event.send(
                event.plain_result(f"{format_duration(timeout)}内 请发送图片 否则上传失败")
            )
            event.stop_event()
            return

        if answer in NO_WORDS:
            self._pending_media.drop(key)
            if not api.available:
                await event.send(event.plain_result(QQ_ONLY))
            else:
                async for result in self._send_notice(
                    event, api, str(pending.get("group_id")),
                    pending.get("content") or "", bool(pending.get("pinned")), None, None,
                ):
                    await event.send(result)
            event.stop_event()
            return

    # ------------------------------------------------------------------
    # 我的世界工具
    # ------------------------------------------------------------------

    @filter.command("slimefinder", alias={"sf"})
    async def cmd_slimefinder(self, event: AstrMessageEvent):
        """/slimefinder <version> <seed> - 查找史莱姆区块"""
        raw = self._raw_after(event, "slimefinder", "sf")
        parts = raw.split()

        if len(parts) < 2:
            yield event.plain_result(
                "用法: /slimefinder <version> <seed>\n示例: /slimefinder 1.20.1 12345678"
            )
            return

        version = parts[0]
        try:
            seed = int(parts[1])
        except ValueError:
            yield event.plain_result("种子必须是整数")
            return

        chunks = await asyncio.to_thread(_find_slime_chunks, seed, 10)
        if not chunks:
            yield event.plain_result("在附近 10 区块内未找到史莱姆区块")
            return

        lines = [f"Minecraft {version} 种子 {seed} 的史莱姆区块:"]
        lines.extend(f"区块 ({x}, {z})" for x, z in chunks[:10])
        if len(chunks) > 10:
            lines.append(f"... 还有 {len(chunks) - 10} 个区块")
        yield event.plain_result("\n".join(lines))

    # ------------------------------------------------------------------
    # 进群 / 退群事件
    # ------------------------------------------------------------------

    @filter.event_message_type(filter.EventMessageType.ALL, priority=3)
    async def on_group_notice(self, event: AstrMessageEvent):
        """群成员增减事件的统一入口。"""
        raw = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw, dict):
            return

        notice_type = raw.get("notice_type")
        if notice_type == "group_increase":
            await self._on_member_increase(event, raw)
        elif notice_type == "group_decrease":
            await self._on_member_decrease(event, raw)

    async def _on_member_increase(self, event: AstrMessageEvent, raw: dict):
        """封禁名单拦截与入群欢迎。"""
        group_id = str(raw.get("group_id") or "")
        user_id = str(raw.get("user_id") or "")
        if not group_id or not user_id:
            return

        api = OneBotApi(event)
        if not api.available:
            return

        if user_id in self._ban_list(group_id):
            try:
                await api.kick(int(group_id), int(user_id), reject=True)
                logger.info(f"[ZM-QQGroupmgr] 封禁用户 {user_id} 尝试加入群 {group_id}，已自动踢出")
            except RuntimeError as exc:
                logger.warning(f"[ZM-QQGroupmgr] 踢出封禁用户失败: {exc}")
            event.stop_event()
            return

        await self._start_verify(api, group_id, user_id)

        welcome = self.settings.group(group_id).get("welcome")
        if not isinstance(welcome, dict) or not welcome.get("enabled"):
            return

        content = welcome.get("content") or ""
        if not content:
            return

        # 昵称是成员自己能改的，必须转义后再拼进 CQ 文本；
        # 模板本身由管理员编写，保留其中的 CQ 码不动。
        message = render_cq(
            content,
            {
                "at": f"[CQ:at,qq={user_id}]",
                "name": escape_cq(await api.stranger_name(user_id)),
                "user_id": user_id,
                "group_id": group_id,
            },
        )
        if message:
            await api.send_group_msg(int(group_id), message)

    async def _on_member_decrease(self, event: AstrMessageEvent, raw: dict):
        """成员退群后按配置发送自定义提示（可带图片）。"""
        group_id = str(raw.get("group_id") or "")
        user_id = str(raw.get("user_id") or "")
        if not group_id or not user_id:
            return

        # 机器人自己被踢出群，没人可提示了
        sub_type = str(raw.get("sub_type") or "leave")
        if sub_type == "kick_me" or user_id == str(event.get_self_id() or ""):
            return

        # 人已经不在群里，报告没法再回复，连同历史一起清掉
        removed = await self.reports.remove_user(group_id, user_id)
        if removed:
            logger.info(f"[ZM-QQGroupmgr] {user_id} 已离开群 {group_id}，删除其 {removed} 条报告")
        await self.draws.drop_member(group_id, user_id)

        state = self._farewell(group_id)
        if not state.get("enabled"):
            return
        content = state.get("content") or DEFAULT_FAREWELL

        api = OneBotApi(event)
        if not api.available:
            return

        operator_id = str(raw.get("operator_id") or "")
        reason = "被移出群聊" if sub_type == "kick" else "退出了本群"
        operator = ""
        if sub_type == "kick" and operator_id and operator_id != user_id:
            operator = await resolve_member_name(api, int(group_id), operator_id)

        # 人已经不在群里，群名片查不到，退回陌生人昵称
        nickname = escape_cq(await api.stranger_name(user_id))
        message = render_cq(
            content,
            {
                # 已退群的成员 at 不出来，{at} 退化成昵称
                "at": nickname,
                "name": nickname,
                "user_id": user_id,
                "group_id": group_id,
                "reason": reason,
                "operator": escape_cq(operator) if operator else "管理员",
            },
        )

        image = self._farewell_image(group_id, state)
        if image is not None:
            try:
                data = await asyncio.to_thread(image.read_bytes)
                # base64 字符集里没有 , [ ]，可以直接拼进 CQ 码
                message += f"[CQ:image,file={to_base64_uri(data)}]"
            except OSError as exc:
                logger.warning(f"[ZM-QQGroupmgr] 读取退群提示图片失败: {exc}")

        if message:
            await api.send_group_msg(int(group_id), message)

    # ------------------------------------------------------------------
    # 群精华
    # ------------------------------------------------------------------

    @staticmethod
    def _reply_id(event: AstrMessageEvent):
        """被引用（回复）的那条消息的 id，没引用返回 None。"""
        for component in event.message_obj.message or []:
            if type(component).__name__ == "Reply":
                target_id = getattr(component, "id", None)
                if target_id is not None:
                    return target_id
        return None

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("star")
    async def cmd_star(self, event: AstrMessageEvent):
        """/star - 把引用的消息设为群精华"""
        async for result in self._toggle_essence(event, "star", True):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("remove_star", alias={"rs"})
    async def cmd_remove_star(self, event: AstrMessageEvent):
        """/remove_star - 取消引用消息的群精华（缩写 /rs）"""
        async for result in self._toggle_essence(event, "remove_star", False):
            yield result

    async def _toggle_essence(self, event: AstrMessageEvent, command: str, enable: bool):
        if not self._require_group(event):
            yield event.plain_result(ADMIN_ONLY)
            return

        api = OneBotApi(event)
        if not api.available:
            yield event.plain_result(QQ_ONLY)
            return

        message_id = self._reply_id(event)
        if message_id is None:
            yield event.plain_result(f"用法: 引用（回复）一条消息后发送 /{command}")
            return

        verb = "设为" if enable else "取消"
        try:
            await api.call(
                "set_essence_msg" if enable else "delete_essence_msg", message_id=message_id
            )
        except RuntimeError as exc:
            yield event.plain_result(f"{verb}群精华失败: {exc}（机器人需为群主或管理员）")
            return
        yield event.plain_result("已设为群精华" if enable else "已取消群精华")

    # ------------------------------------------------------------------
    # 问题反馈：/report 排队、/solve 处理、/check_report 查进度
    # ------------------------------------------------------------------

    @staticmethod
    def _quote(event: AstrMessageEvent, text: str):
        """引用发指令的那条消息来回复。"""
        import astrbot.api.message_components as Comp

        return event.chain_result(
            [Comp.Reply(id=event.message_obj.message_id), Comp.Plain(text)]
        )

    @filter.command("report")
    async def cmd_report(self, event: AstrMessageEvent):
        """/report <内容> - 提交问题反馈，自动排队编号（全体成员可用）"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return
        if not self._group_flag(group_id, "report_enabled"):
            yield event.plain_result("本群的问题反馈功能已关闭")
            return

        content = self._raw_after(event, "report")
        if not content:
            yield event.plain_result("用法: /report <问题内容>\n例: /report 下载链接打不开")
            return
        if len(content) > MAX_REPORT_LEN:
            yield event.plain_result(
                f"报告内容最长 {MAX_REPORT_LEN} 字，当前 {len(content)} 字，请精简后再提交"
            )
            return

        user_id = str(event.get_sender_id())
        waiting = [r for r in self.reports.user_reports(group_id, user_id) if not r.get("solved")]
        if len(waiting) >= MAX_OPEN_PER_USER:
            yield event.plain_result(
                f"您已有 {len(waiting)} 个报告尚未解决，请等处理后再提交（发送 /cr 查看进度）"
            )
            return

        report, ahead = await self.reports.add(group_id, user_id, content)
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(report["time"]))
        yield self._quote(
            event,
            f"报告已收到，报告编号为 {report['no']}\n"
            f"提交时间: {when}\n"
            f"前方还有 {ahead} 个问题等待解决，发送 /cr 可随时查看进度",
        )

    async def _can_handle_reports(self, event: AstrMessageEvent, group_id: str) -> bool:
        """处理报告的指令谁能用：群管理（见下）和 report_solve_users 里的 QQ。"""
        if str(event.get_sender_id()) in coerce_str_list(self.config.get("report_solve_users")):
            return True
        return await self._is_group_manager(event, group_id)

    async def _is_group_manager(self, event: AstrMessageEvent, group_id: str) -> bool:
        """AstrBot 管理员，或本群群主、管理员。"""
        if event.is_admin():
            return True
        user_id = str(event.get_sender_id())
        raw = getattr(event.message_obj, "raw_message", None)
        sender = raw.get("sender") if isinstance(raw, dict) else None
        role = sender.get("role") if isinstance(sender, dict) else None
        # 消息里没带群身份时现查一次
        if role is None and user_id.isdigit():
            api = OneBotApi(event)
            if api.available:
                role = (await api.member_info(int(group_id), int(user_id))).get("role")
        return role in ("owner", "admin")

    @filter.command("solve")
    async def cmd_solve(self, event: AstrMessageEvent):
        """/solve <编号> <回复> - 解决报告并回复报告人；不带参数列出未解决报告"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return
        if not await self._can_handle_reports(event, group_id):
            yield event.plain_result(REPORT_HANDLER_ONLY.format(command="/solve"))
            return

        parts = self._raw_after(event, "solve").split(None, 1)
        number = parts[0].lstrip("#＃") if parts else ""
        if not number.isdecimal() or len(parts) < 2:
            yield event.plain_result(
                digest_text(self.reports, group_id) + "\n\n用法: /solve <编号> <回复内容>"
            )
            return

        reply = parts[1].strip()
        if len(reply) > MAX_REPORT_LEN:
            yield event.plain_result(f"回复最长 {MAX_REPORT_LEN} 字，当前 {len(reply)} 字")
            return

        report = await self.reports.solve(group_id, int(number), reply, event.get_sender_id())
        if report is None:
            yield event.plain_result(
                f"没有编号为 {number} 的未解决报告\n\n" + digest_text(self.reports, group_id)
            )
            return

        import astrbot.api.message_components as Comp

        yield event.chain_result(
            [
                Comp.At(qq=report["user_id"]),
                Comp.Plain(
                    f" 您的报告（编号 {report['no']}）已解决\n管理员回复：{report['reply']}"
                ),
            ]
        )

    @filter.command("check_report", alias={"cr"})
    async def cmd_check_report(self, event: AstrMessageEvent):
        """/check_report - 查看自己报告的处理进度（缩写 /cr，全体成员可用）"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return
        yield self._quote(event, status_text(self.reports, group_id, str(event.get_sender_id())))

    @filter.command("drh")
    async def cmd_delete_report_history(self, event: AstrMessageEvent):
        """/drh <成员> - 删除成员在本群的全部报告记录，@ 或 QQ 号均可"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return
        if not await self._can_handle_reports(event, group_id):
            yield event.plain_result(REPORT_HANDLER_ONLY.format(command="/drh"))
            return

        # @机器人 唤醒时机器人自己也在 @ 列表里
        bot_id = str(event.get_self_id() or "")
        targets = [
            uid for uid in extract_targets(event, self._raw_after(event, "drh")) if uid != bot_id
        ]
        if not targets:
            yield event.plain_result("用法: /drh <成员>  @ 成员或直接写 QQ 号，可一次写多个")
            return

        lines = []
        for user_id in targets:
            removed = await self.reports.remove_user(group_id, user_id)
            lines.append(
                f"已删除 QQ:{user_id} 的 {removed} 条报告"
                if removed
                else f"QQ:{user_id} 在本群没有报告记录"
            )
        yield event.plain_result("\n".join(lines))

    @filter.command("rl")
    async def cmd_report_list(self, event: AstrMessageEvent):
        """/rl [页码] - 发送当前的反馈列表"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return
        if not await self._can_handle_reports(event, group_id):
            yield event.plain_result(REPORT_HANDLER_ONLY.format(command="/rl"))
            return

        args = self._args(event, "rl")
        page = coerce_int(args[0], 1) if args else 1
        yield event.plain_result(digest_text(self.reports, group_id, page))

    @filter.command("rclear")
    async def cmd_report_clear(self, event: AstrMessageEvent):
        """/rclear - 清空本群未解决的报告队列，已解决的历史保留"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return
        if not await self._can_handle_reports(event, group_id):
            yield event.plain_result(REPORT_HANDLER_ONLY.format(command="/rclear"))
            return

        removed = await self.reports.clear_open(group_id)
        yield event.plain_result(f"已清空 {removed} 个未解决的报告" if removed else "队列是空的")

    @filter.command("rsw")
    async def cmd_report_switch(self, event: AstrMessageEvent):
        """/rsw on|off - 开启或关闭本群的 /report"""
        async for result in self._report_toggle(event, "rsw", "report_enabled", True, "问题反馈功能"):
            yield result

    @filter.command("rmd")
    async def cmd_report_remind(self, event: AstrMessageEvent):
        """/rmd on|off - 开启或关闭本群的反馈列表提醒"""
        async for result in self._report_toggle(
            event, "rmd", "report_remind", self._remind_default(), "反馈列表提醒"
        ):
            yield result

    async def _report_toggle(
        self, event: AstrMessageEvent, command: str, key: str, default: bool, label: str
    ):
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return
        if not await self._can_handle_reports(event, group_id):
            yield event.plain_result(REPORT_HANDLER_ONLY.format(command=f"/{command}"))
            return

        args = self._args(event, command)
        action = args[0].lower() if args else ""
        if action not in {"on", "off"}:
            state = "开启" if self._group_flag(group_id, key, default) else "关闭"
            yield event.plain_result(f"用法: /{command} on|off\n当前状态: {state}")
            return

        self.settings.group(group_id)[key] = action == "on"
        await self.settings.save()
        yield event.plain_result(f"已{'开启' if action == 'on' else '关闭'}本群的{label}")

    # ------------------------------------------------------------------
    # 抽奖：/draw 发起、/join_draw 参与、/draw_cancel 取消，到点由 _settle_draws 开奖
    # ------------------------------------------------------------------

    @filter.command("draw")
    async def cmd_draw(self, event: AstrMessageEvent):
        """/draw <抽奖名> <中奖人数> <时间> <是否强制群成员抽奖> [最大参与人数] - 发起抽奖"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return
        if not await self._is_group_manager(event, group_id):
            yield event.plain_result("/draw 仅 AstrBot 管理员、群主、群管理员可用")
            return
        # 开奖要查群成员、@ 中奖者，别的平台做不到，别等到点才发现
        if not OneBotApi(event).available:
            yield event.plain_result(QQ_ONLY)
            return

        args = self._args(event, "draw")
        if not args:
            yield event.plain_result(DRAW_USAGE + "\n\n" + draw_list_text(self.draws, group_id))
            return
        fields, error = parse_draw_args(args)
        if fields is None:
            yield event.plain_result(error)
            return

        name = fields["name"]
        if self.draws.total() >= MAX_DRAWS:
            yield event.plain_result(
                f"抽奖已达上限，所有群合计最多同时存在 {MAX_DRAWS} 个抽奖\n"
                f"本群占用 {len(self.draws.draws(group_id))} 个，"
                "其他群的名额可由 AstrBot 管理员私聊发送 /draw_cancel 查看和取消"
            )
            return
        if self.draws.get(group_id, name) is not None:
            yield event.plain_result(f"本群已有名为「{name}」的抽奖，请换个名字")
            return

        draw = await self.draws.add(group_id, fields, str(event.get_self_id() or ""))
        if draw["forced"]:
            how = "全体成员自动参与，无需报名"
        else:
            how = f"发送 /jd {name} 参与" + (f"，限 {draw['limit']} 人" if draw["limit"] else "")
        yield event.plain_result(
            f"抽奖「{name}」已开启\n"
            f"中奖人数: 最多 {draw['winner_count']} 人\n"
            f"开奖时间: {draw_end_text(draw)}\n"
            f"参与方式: {how}"
        )

    @filter.command("join_draw", alias={"jd"})
    async def cmd_join_draw(self, event: AstrMessageEvent):
        """/join_draw <抽奖名> - 参与抽奖（缩写 /jd，全体成员可用）；不带参数列出进行中的抽奖"""
        group_id = self._require_group(event)
        if not group_id:
            yield event.plain_result(ADMIN_ONLY)
            return

        name = self._raw_after(event, "join_draw", "jd")
        if not name:
            yield event.plain_result(
                draw_list_text(self.draws, group_id) + "\n\n用法: /jd <抽奖名>"
            )
            return
        yield self._quote(event, await self.draws.join(group_id, name, str(event.get_sender_id())))

    @filter.command("draw_cancel")
    async def cmd_draw_cancel(self, event: AstrMessageEvent):
        """/draw_cancel <抽奖名> - 取消抽奖；AstrBot 管理员可用 /draw_cancel <群号> <抽奖名> 跨群取消"""
        group_id = self._require_group(event)
        bot_admin = event.is_admin()
        if not group_id and not bot_admin:
            yield event.plain_result(ADMIN_ONLY)
            return
        if not await self._is_group_manager(event, group_id):
            yield event.plain_result("/draw_cancel 仅 AstrBot 管理员、群主、群管理员可用")
            return

        # 抽奖名不含空格，两段就是「群号 抽奖名」。名额所有群共用，别的群占着时只有这条路能释放
        args = self._args(event, "draw_cancel")
        target, name = args if bot_admin and len(args) == 2 else (group_id, " ".join(args))
        # 所有群的列表只在私聊给：发在群里，全群都能看到别的群的群号和抽奖名
        listing = draw_list_text(self.draws, group_id) if group_id else draw_all_text(self.draws)
        if not target or not name:
            usage = "用法: /draw_cancel <抽奖名>"
            if bot_admin:
                usage += "\n跨群或私聊: /draw_cancel <群号> <抽奖名>\n私聊发送 /draw_cancel 可查看所有群的抽奖"
            yield event.plain_result(f"{listing}\n\n{usage}")
            return

        draw = self.draws.get(target, name)
        if draw is None:
            yield event.plain_result(f"没有名为「{name}」的抽奖\n\n{listing}")
            return
        # 已公布一部分的，群管理取消会让剩下的中奖者没有说法；AstrBot 管理员要能释放卡住的名额
        if draw is self._announcing or (draw.get("announced") and not bot_admin):
            yield event.plain_result(f"抽奖「{name}」已开始公布中奖名单，无法取消")
            return

        await self.draws.remove(target, name)
        reply = f"抽奖「{name}」已取消"
        if draw.get("announced"):
            pending = draw.get("winners") or []
            logger.info(f"[ZM-QQGroupmgr] 群 {target} 抽奖「{name}」被管理员取消，未通报的中奖者: {pending}")
            reply += f"\n此前已公布 {draw['announced']} 人，未公布的 {len(pending)} 人不再通报"
        yield event.plain_result(reply)

    # ------------------------------------------------------------------
    # 帮助
    # ------------------------------------------------------------------

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("zmhelp", alias={"群管帮助"})
    async def cmd_help(self, event: AstrMessageEvent):
        """/zmhelp - 查看全部命令"""
        title = f"{PLUGIN_NAME} v{PLUGIN_VERSION}"
        text = self._help_text()

        # 长帮助交给 AstrBot 自动转合并转发时，卡片标题会是协议端默认的
        # 「群聊的聊天记录」；这里自己发合并转发，把标题定成插件名 + 版本号。
        api = OneBotApi(event)
        group_id = event.get_group_id()
        if api.available and group_id:
            bot_id = str(event.get_self_id() or "10000")
            sent = await api.send_forward(
                int(group_id),
                [forward_node(bot_id, title, text)],
                source=title,
                news=[{"text": "命令一览"}],
                summary="查看 1 条转发消息",
                prompt=f"[{title}]",
            )
            if sent is not None:
                return

        yield event.plain_result(text)

    def _help_text(self) -> str:
        """帮助正文。插件配置 help_menu_text 非空时用它，占位符 {name} {version} {cooldown}。"""
        cooldown = self.files.cooldown_seconds()
        cooldown_text = "不限制" if cooldown <= 0 else format_duration(cooldown)

        custom = str(self.config.get("help_menu_text") or "").strip()
        if custom:
            return (
                custom.replace("{name}", PLUGIN_NAME)
                .replace("{version}", PLUGIN_VERSION)
                .replace("{cooldown}", cooldown_text)
            )

        return (
            f"{PLUGIN_NAME} v{PLUGIN_VERSION} 命令一览\n"
            "除标注外均仅 AstrBot 管理员可用；括号内为命令缩写\n\n"
            "【禁言】\n"
            "/mute <成员> [时长] [理由] 禁言成员，默认 10 分钟（缩写 /m）\n"
            "/unmute <成员>          解除禁言（缩写 /um）\n"
            "/mutelist               查看禁言列表、剩余时长与理由\n"
            "/muteall [时长]          全体禁言，默认永久\n"
            "/muteall off            解除全体禁言\n"
            "  单次上限 3650 天；超过 30 天的部分由机器人自动续期\n\n"
            "【进群审批】/join_approval 缩写 /ja\n"
            "/ja set verification_code <number|letter|mix|sha>\n"
            "                        入群后限时回发验证码，超时踢出（缩写 /ja set vc）\n"
            "/ja set static <内容>    把 <内容> 设为「回答正确问题」的答案\n"
            "/ja set dynamic         用 GitHub 最新 commit 的 sha 作答案，定时刷新\n"
            "/ja off | /ja status    关闭 / 查看当前设置\n\n"
            "【敏感词】/sensitive-words 缩写 /sw\n"
            "/sw on [时长]            开启，默认单位分钟\n"
            "/sw off                 关闭（改时长需先 off 再 on）\n"
            "/sw add <文本>           添加敏感词\n"
            "/sw del <文本>           删除敏感词（缩写 delete/remove/rm）\n"
            "/sw list                查看自定义词库\n"
            "/sw mode <custom|library|both>  词库来源\n"
            "/sw reload              刷新远程词库\n\n"
            "【检测】\n"
            "/antiflood on|off       刷屏检测（缩写 /flood、/af）\n"
            "/cardcheck on|off       群名片广告与敏感词检测（缩写 /cc）\n\n"
            "【文件】/file 缩写 /f，以下全体成员可用:\n"
            "/file download <name>       获取临时下载链接（缩写 /f dl，仅私聊）\n"
            "/file log <name> [次数]      查看更新日志（缩写 /f l）\n"
            "/file list                  查看全部文件（缩写 /f ls）\n"
            "【文件】仅管理员:\n"
            "/file upload <name> <时长>   上传文件（缩写 /f up）\n"
            "/file log update <name> <version> <内容>   缩写 /f l up <name> <version> <内容>\n"
            "                            更新已上传目标文件的版本字段，内容为补充解释更新内容\n"
            "/file download cdreset <成员>  重置该成员的下载冷却（缩写 /f dl cdreset <成员>）\n"
            "/file delete <name>         删除文件（缩写 /f del、/f rm）\n"
            f"下载冷却: {cooldown_text}"
            "（可在插件配置 file_download_cooldown 中自定义）\n\n"
            "【成员】\n"
            "/kick <成员>            踢出成员\n"
            "/kick <时间>            清理不活跃成员（例: /kick 20d）\n"
            "/ban <成员>             封禁并踢出\n"
            "/unban <QQ号>           解除封禁\n"
            "/banlist                查看封禁列表\n"
            "/op | /deop <成员>       管理员权限\n"
            "/title @成员 <文本>      设置群头衔\n\n"
            "【群资料】/group 缩写 /g\n"
            "/group newname <文本> [qq群号]   改群名（缩写 /g nn）\n"
            "/group pp [图片] [qq群号]        改群头像（缩写 /g avatar）\n"
            "  群号省略即当前群；用 - 连接批量: /g pp 3366-1009-10032\n"
            "  未附图片时，1 分钟内补发图片即可\n\n"
            "【群公告】/broadcast 缩写 /bc\n"
            "/broadcast <内容> <是否置顶公告>   最后一位只能填 true 或 false\n"
            "  内容里可直接插图；只发文字时机器人会追问要不要配图\n\n"
            "【消息与迎送】\n"
            "/recall                 回复消息后撤回\n"
            "/recall <数量> [是否包含机器人]  批量撤回（例: /recall 5 false）\n"
            "/star                   引用消息后设为群精华\n"
            "/remove_star            引用消息后取消群精华（缩写 /rs）\n"
            "/ad | /ad set <文本> | /ad clear | /ad reset\n"
            "/adban on|off           广告拦截\n"
            "/wel set <文本> | on | off | reset | status    入群欢迎\n"
            "/bye set <文本> | image | image clear | on | off | reset | status\n"
            "                        退群提示，可附图片\n\n"
            "【问题反馈】\n"
            "/report <内容>           提交问题，自动排队编号（全体可用）\n"
            "/check_report           查看自己报告的进度和历史（缩写 /cr，全体可用）\n"
            "/solve <编号> <回复>     标记解决并回复报告人；不带参数列出未解决的\n"
            "/drh <成员>              删除该成员在本群的全部报告记录\n"
            "/rl [页码]               发送当前的反馈列表\n"
            "/rclear                 清空未解决的报告队列，已解决的历史保留\n"
            "/rsw on|off             开启 / 关闭本群的 /report\n"
            "/rmd on|off             开启 / 关闭本群的反馈列表提醒\n"
            "  除 /report、/cr 外，群主、群管理和 report_solve_users 里的成员也可用\n"
            "  成员退群后，其报告记录自动删除\n"
            "  未解决的报告每 report_remind_minutes 分钟在群里提醒一次\n\n"
            "【抽奖】群主、群管理也可用\n"
            "/draw <抽奖名> <中奖人数> <时间> <是否强制群成员抽奖> [最大参与人数]\n"
            "  <时间> 单位小时，最大 99999；不带参数列出进行中的抽奖\n"
            "  true 全体成员自动参与，含后来进群的；false 成员发送 /jd 参与\n"
            "  [最大参与人数] 选填，不填不限人数\n"
            "/draw_cancel <抽奖名>    取消抽奖\n"
            "/draw_cancel <群号> <抽奖名>  跨群取消，私聊可用；私聊不带参数列出所有群（仅 AstrBot 管理员）\n"
            "/join_draw <抽奖名>      参与抽奖（缩写 /jd，全体可用）\n"
            "  所有群合计最多同时 5 个；到点随机 @ 中奖者并通报 QQ，领奖提示见配置 draw_claim_tip\n\n"
            "【其他】\n"
            "/merge <标题> <qq> <内容> [...]  构造合并转发，标题即卡片名（全体可用）\n"
            "/kill <成员> <理由>              赛博击杀播报\n"
            "/slimefinder <version> <seed>   史莱姆区块（缩写 /sf，全体可用）\n"
            "/update on|off                  本群是否接收插件更新提示（默认开）\n"
            "/zmhelp                         本帮助（缩写 /群管帮助）\n\n"
            "时长单位: s 秒 / m 分钟 / h 小时 / d 天"
        )
