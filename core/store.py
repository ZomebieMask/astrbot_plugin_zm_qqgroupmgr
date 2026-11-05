"""基于 JSON 文件的插件数据存储。"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from astrbot.api import logger

PLUGIN_DIR_NAME = "ZM-QQGroupmgr"
# 1.0.5 之前叫 ZM-QQManager，老用户的数据目录还是旧名字，首次运行时整目录改名过来
LEGACY_DIR_NAMES = ("ZM-QQManager",)


def get_data_dir() -> Path:
    """返回本插件的数据目录，必要时创建；老版本的目录会先迁移过来。"""
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        base = Path(get_astrbot_data_path())
    except Exception:  # 兜底：AstrBot 版本较旧时退回相对路径
        base = Path("data")

    root = base / "plugin_data"
    path = root / PLUGIN_DIR_NAME

    if not path.exists():
        for legacy in LEGACY_DIR_NAMES:
            old = root / legacy
            if not old.is_dir():
                continue
            try:
                old.rename(path)
                logger.info(f"[ZM-QQGroupmgr] 已把数据目录 {legacy} 迁移为 {PLUGIN_DIR_NAME}")
            except OSError as exc:
                # 迁移失败不能让插件起不来，退回继续用旧目录，数据照样在
                logger.warning(
                    f"[ZM-QQGroupmgr] 数据目录 {legacy} 迁移失败（{exc}），继续使用旧目录"
                )
                old.mkdir(parents=True, exist_ok=True)
                return old
            break

    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_on_upgrade(version: str) -> Optional[str]:
    """版本号变化时把当前数据快照到 ``backups/<旧版本>/``。

    数据本来就存在 ``data/plugin_data/`` 下，覆盖安装插件不会碰它；这份快照
    只是为了防「新版本写坏了老数据」——真出事时把目录拷回来即可。
    """
    import shutil

    root = get_data_dir()
    marker = root / "VERSION"
    try:
        previous = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    except OSError:
        previous = ""

    if previous == version:
        return None

    made = None
    if previous:
        target = root / "backups" / f"{previous}-{time.strftime('%Y%m%d%H%M%S')}"
        try:
            target.mkdir(parents=True, exist_ok=True)
            for item in root.glob("*.json"):
                shutil.copy2(item, target / item.name)
            made = str(target)
        except OSError as exc:
            logger.warning(f"[ZM-QQGroupmgr] 升级前备份失败: {exc}")

    try:
        marker.write_text(version, encoding="utf-8")
    except OSError as exc:
        logger.warning(f"[ZM-QQGroupmgr] 写入版本标记失败: {exc}")
    return made


class JsonStore:
    """一个 JSON 文件对应一类数据，写入走临时文件 + 原子替换。"""

    # 读取失败又没法把原文件挪开时置位：本次运行不再写盘，否则会把它覆盖掉
    _frozen = False

    def __init__(self, filename: str):
        self.path = get_data_dir() / filename
        self._data: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                raise ValueError("顶层不是 JSON 对象")
            self._data = loaded
        except Exception as exc:
            logger.error(f"[ZM-QQGroupmgr] 读取 {self.path.name} 失败: {exc}")
            # 改名留着，否则下一次保存会用空数据覆盖它，手改多打个逗号数据就全没了
            kept = self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}")
            try:
                os.replace(self.path, kept)
                # 必须先停用：插件运行中放回去，会被内存里的空数据覆盖
                logger.error(
                    f"[ZM-QQGroupmgr] 原文件已保留为 {kept.name}。恢复方法：先停用插件或关闭 AstrBot，"
                    f"修好后改回 {self.path.name}（覆盖同名文件），再启用"
                )
            except OSError as move_exc:
                self._frozen = True
                logger.error(
                    f"[ZM-QQGroupmgr] 保留 {self.path.name} 失败: {move_exc}。"
                    "本次运行不写入该文件，修好后重载插件"
                )

    def _write(self, payload: str) -> None:
        tmp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            # errors=replace：成员发来的孤立代理字符写不进 UTF-8，不替换的话这份数据以后每次保存都失败
            with os.fdopen(fd, "w", encoding="utf-8", errors="replace") as handle:
                handle.write(payload)
            os.replace(tmp, self.path)
            tmp = None
        except Exception as exc:
            logger.error(f"[ZM-QQGroupmgr] 写入 {self.path.name} 失败: {exc}")
        finally:
            # 写失败时别把 .tmp 残留在数据目录里
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    async def save(self) -> None:
        """把当前内容落盘。

        序列化必须留在事件循环里同步完成：若丢进线程里 dump，别的协程正好
        在改同一个 dict 就会抛 "dictionary changed size during iteration"，
        整次保存直接丢失。
        """
        if self._frozen:
            return
        try:
            payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error(f"[ZM-QQGroupmgr] 序列化 {self.path.name} 失败: {exc}")
            return
        async with self._lock:
            await asyncio.to_thread(self._write, payload)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def pop(self, key: str, default: Any = None) -> Any:
        return self._data.pop(key, default)

    def group(self, group_id: str) -> Dict[str, Any]:
        """取某个群的配置字典，不存在则创建。"""
        bucket = self._data.get(group_id)
        if not isinstance(bucket, dict):
            bucket = {}
            self._data[group_id] = bucket
        return bucket

    @property
    def data(self) -> Dict[str, Any]:
        return self._data

    def keys(self):
        return self._data.keys()

    def items(self):
        return self._data.items()

    def __contains__(self, key: str) -> bool:
        return key in self._data


class GroupToggle:
    """按群保存"开关 + 时长"这类小状态。"""

    def __init__(self, store: JsonStore, name: str):
        self.store = store
        self.name = name

    def state(self, group_id: str) -> Dict[str, Any]:
        bucket = self.store.group(str(group_id))
        state = bucket.get(self.name)
        if not isinstance(state, dict):
            state = {"enabled": False}
            bucket[self.name] = state
        return state

    def is_enabled(self, group_id: str) -> bool:
        return bool(self.state(group_id).get("enabled"))

    async def enable(self, group_id: str, **extra: Any) -> None:
        state = self.state(group_id)
        state["enabled"] = True
        state.update(extra)
        await self.store.save()

    async def disable(self, group_id: str) -> None:
        state = self.state(group_id)
        state["enabled"] = False
        await self.store.save()

    def value(self, group_id: str, key: str, default: Any = None) -> Any:
        return self.state(group_id).get(key, default)


def coerce_int(value: Any, default: int) -> int:
    """把配置项转成 int，非法值回退默认。"""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):  # JSON 里的 Infinity 转 int 是 OverflowError
        return default


def coerce_str_list(value: Any) -> list:
    """把配置项转成字符串列表，兼容换行分隔的文本。"""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip() for line in value.replace(",", "\n").splitlines() if line.strip()]
    return []


def optional_str(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None
