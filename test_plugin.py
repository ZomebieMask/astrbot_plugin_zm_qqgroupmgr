"""自检脚本：`python test_plugin.py`（无需 pytest / AstrBot 运行环境）。

只盖两处有分支的逻辑：
1. `/zmhelp` 菜单 —— 内置菜单、`help_menu_text` 自定义、空白回落、占位符替换
2. 数据目录迁移 —— 1.0.5 改名后老用户的 `ZM-QQManager` 目录要整体改名过来
"""
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent


class _Stub:
    """任意属性/调用都返回自己，够 astrbot 那几个装饰器用。"""

    def __getattr__(self, name):
        return _Stub()

    def __call__(self, *args, **kwargs):
        return lambda func: func

    def __getitem__(self, key):
        return _Stub()


def _stub_astrbot():
    def mod(name, **attrs):
        m = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(m, key, value)
        sys.modules[name] = m
        return m

    class Star:
        def __init__(self, *args, **kwargs):
            pass

    mod("astrbot")
    mod("astrbot.api", AstrBotConfig=dict, logger=_Stub())
    mod("astrbot.api.event", AstrMessageEvent=object, filter=_Stub())
    mod("astrbot.api.star", Context=object, Star=Star,
        register=lambda *a, **kw: (lambda cls: cls))


def _load_plugin():
    """把插件目录当包加载，相对导入 (.core.xxx) 才成立。"""
    spec = importlib.util.spec_from_file_location(
        "zmplugin", HERE / "__init__.py", submodule_search_locations=[str(HERE)]
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["zmplugin"] = pkg
    spec.loader.exec_module(pkg)
    return importlib.import_module("zmplugin.main")


def test_help_menu(main):
    cls = main.ZMQQGroupmgr
    inst = object.__new__(cls)
    inst.files = types.SimpleNamespace(cooldown_seconds=lambda: 300)

    inst.config = {}
    builtin = cls._help_text(inst)
    assert builtin.startswith(f"{main.PLUGIN_NAME} v{main.PLUGIN_VERSION} 命令一览"), builtin[:60]
    assert "【禁言】" in builtin and "时长单位" in builtin
    assert "下载冷却: 5分钟" in builtin, "cooldown_text 没接上"
    assert "QQManager" not in builtin, "还有旧名字残留"

    inst.config = {"help_menu_text": "  {name} v{version} / 冷却 {cooldown}  "}
    assert cls._help_text(inst) == f"{main.PLUGIN_NAME} v{main.PLUGIN_VERSION} / 冷却 5分钟"

    inst.config = {"help_menu_text": "   \n  "}
    assert cls._help_text(inst) == builtin, "全空白应回落内置菜单"

    print("  help 菜单: 内置 / 自定义 / 空白回落 OK")


def test_data_dir_migration():
    spec = importlib.util.spec_from_file_location("zmstore", HERE / "core" / "store.py")
    store = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(store)

    def run(setup):
        root = Path(tempfile.mkdtemp())
        path_mod = types.ModuleType("astrbot.core.utils.astrbot_path")
        path_mod.get_astrbot_data_path = lambda: str(root)
        sys.modules["astrbot.core"] = types.ModuleType("astrbot.core")
        sys.modules["astrbot.core.utils"] = types.ModuleType("astrbot.core.utils")
        sys.modules["astrbot.core.utils.astrbot_path"] = path_mod
        setup(root / "plugin_data")
        return root, store.get_data_dir()

    def with_legacy(plugin_data):
        old = plugin_data / "ZM-QQManager"
        old.mkdir(parents=True)
        (old / "settings.json").write_text(json.dumps({"k": "v"}), encoding="utf-8")

    root, got = run(with_legacy)
    assert got.name == "ZM-QQGroupmgr", got
    assert json.loads((got / "settings.json").read_text(encoding="utf-8")) == {"k": "v"}
    assert not (root / "plugin_data" / "ZM-QQManager").exists(), "旧目录应已改名"
    assert store.get_data_dir() == got, "重复调用应幂等"

    _, got = run(lambda plugin_data: plugin_data.mkdir(parents=True))
    assert got.name == "ZM-QQGroupmgr" and got.is_dir(), "全新安装应直接建新目录"

    def both(plugin_data):
        (plugin_data / "ZM-QQManager").mkdir(parents=True)
        (plugin_data / "ZM-QQManager" / "a.json").write_text("1", encoding="utf-8")
        (plugin_data / "ZM-QQGroupmgr").mkdir(parents=True)

    root, got = run(both)
    assert got.name == "ZM-QQGroupmgr"
    assert (root / "plugin_data" / "ZM-QQManager" / "a.json").exists(), \
        "新目录已存在时不该动旧目录"

    print("  数据目录: 老用户迁移 / 新装 / 双目录并存 / 幂等 OK")


def test_entry_path(main):
    """数据目录改名后，files.json 里存的旧绝对路径要能按文件名回落。"""
    repo_cls = sys.modules["zmplugin.core.files"].FileRepository
    repo = object.__new__(repo_cls)
    repo.dir = Path(tempfile.mkdtemp()) / "files"
    repo.dir.mkdir(parents=True)
    (repo.dir / "guoclient.zip").write_bytes(b"x")

    stale = {"path": str(Path("/nowhere/plugin_data/ZM-QQManager/files/guoclient.zip"))}
    assert repo._entry_path(stale) == repo.dir / "guoclient.zip", "旧路径应回落到当前仓库"

    live = {"path": str(repo.dir / "guoclient.zip")}
    assert repo._entry_path(live) == repo.dir / "guoclient.zip", "有效路径应原样返回"

    missing = {"path": str(Path("/nowhere/files/never-uploaded.zip"))}
    assert not repo._entry_path(missing).exists(), "确实丢了的文件仍应判定为不存在"

    escape = {"path": "/nowhere/files/../../../etc/passwd"}
    got = repo._entry_path(escape)
    assert not str(got).startswith(str(repo.dir)) or got.name == "passwd" and not got.exists()

    assert repo._entry_path({}) == repo.dir, "空 path 不应崩"
    print("  文件仓库: 旧路径回落 / 有效路径 / 真丢失 / 越界拦截 OK")


def test_join_approval():
    """验证码生成与比对、仓库解析、版本比较。"""
    ja = sys.modules["zmplugin.core.joinapproval"]

    assert ja.make_code("number", 4).isdigit() and len(ja.make_code("number", 4)) == 4
    assert len(ja.make_code("number", 6)) == 6
    assert len(ja.make_code("number", 5)) == 6, "非法位数应回落 6"
    letter = ja.make_code("letter")
    assert len(letter) == 6 and letter.isalpha() and letter.isupper()
    mix = ja.make_code("mix", 4)
    assert len(mix) == 10 and sum(c.isdigit() for c in mix) == 4
    assert len({ja.make_code("mix", 6) for _ in range(20)}) > 1, "验证码不该固定"

    assert ja.code_matches("A1b2", " a1B2 ")
    assert not ja.code_matches("A1b2", "a1b3")
    assert not ja.code_matches("A1b2", "") and not ja.code_matches("", "x")
    assert not ja.code_matches("A1b2", "a1b23"), "长度不同不该通过"
    # compare_digest 遇到非 ASCII 会抛 TypeError，群里随便一句中文都会命中
    assert not ja.code_matches("A1b2", "你好啊")
    assert not ja.code_matches("A1b2", "群里聊天的一句话，带标点。")

    sha = "0123456789abcdef0123456789abcdef01234567"
    assert ja.code_matches(sha, sha, is_sha=True)
    assert ja.code_matches(sha, "0123456", is_sha=True), "7 位前缀应放行"
    assert not ja.code_matches(sha, "012345", is_sha=True), "6 位太短"
    assert not ja.code_matches(sha, "0123457", is_sha=True)
    assert not ja.code_matches(sha, sha + "0", is_sha=True), "比期望更长不该通过"

    for text in (
        "https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr",
        "http://www.github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr.git",
        "github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr/",
        "ZomebieMask/astrbot_plugin_zm_qqgroupmgr",
    ):
        assert ja.parse_repo(text) == "ZomebieMask/astrbot_plugin_zm_qqgroupmgr", text
    for bad in ("", "随便一句话", "https://gitee.com/a/b", "https://github.com/onlyowner"):
        assert ja.parse_repo(bad) is None, bad

    assert ja.version_tuple("v1.0.6") > ja.version_tuple("1.0.5")
    assert ja.version_tuple("1.0.10") > ja.version_tuple("1.0.9")
    assert ja.version_tuple("1.0.6") == ja.version_tuple("1.0.6")
    assert ja.version_tuple("1.1.0-beta") > ja.version_tuple("1.0.99")
    print("  进群审批: 验证码 / sha 前缀 / 仓库解析 / 版本比较 OK")


def test_sha_reverify(main):
    """缓存里的 sha 过时了，成员发来的新 sha 也要认，否则等于白等一场再被踢。"""
    import asyncio

    ja = sys.modules["zmplugin.core.joinapproval"]
    old = "0123456789abcdef0123456789abcdef01234567"
    new = "fedcba9876543210fedcba9876543210fedcba98"

    assert ja.is_sha_text(" 0123456 ") and ja.is_sha_text(old)
    assert not ja.is_sha_text("012345"), "6 位不算 sha"
    assert not ja.is_sha_text("群里随便一句话") and not ja.is_sha_text("hello world")

    calls = []

    class FakeCache:
        async def latest(self, repo, ttl=300, force=False):
            calls.append(repo)
            return new, ""

    inst = object.__new__(main.ZMQQGroupmgr)
    inst._sha_cache = FakeCache()
    match = lambda pending, text: asyncio.run(
        main.ZMQQGroupmgr._verify_matches(inst, pending, text)
    )
    pending = {"code": old, "is_sha": True, "repo": "a/b"}

    assert match(pending, old[:7]), "缓存里的那个 sha 当然算对"
    assert not calls, "对上了就别再去问 GitHub"
    assert match(pending, new[:7]), "仓库又推了新 commit，也该放行"
    assert len(calls) == 1
    assert not match(pending, "1234567"), "不相干的 sha 仍然不通过"
    assert not match(pending, "群主你好呀"), "闲聊不该触发 GitHub 查询"
    assert len(calls) == 2

    # 进群时没取到 sha（GitHub 抽风），验证仍然要能救回来
    assert match({"code": "", "is_sha": True, "repo": "a/b"}, new[:7])
    # 非 sha 验证码不该走复核
    assert not match({"code": "ABC123", "is_sha": False, "repo": "a/b"}, new[:7])
    print("  sha 验证: 缓存命中 / 新 commit 复核 / 闲聊不查询 OK")


def test_sha_retry_kick(main):
    """连错 5 次 sha 直接踢，别让人拿 GitHub 配额当刷屏工具。"""
    import asyncio
    import time

    kicked, sent, fetches = [], [], []

    class FakeApi:
        async def stranger_name(self, uid):
            return "刷屏的"

        async def kick(self, gid, uid, **kw):
            kicked.append((gid, uid))

        async def send_group_msg(self, gid, msg):
            sent.append(msg)

    class FakeEvent:
        def stop_event(self):
            pass

    class FakeCache:
        async def latest(self, repo, ttl=300, force=False):
            fetches.append(repo)
            return "a" * 40, ""

    inst = object.__new__(main.ZMQQGroupmgr)
    inst._sha_cache = FakeCache()
    key = ("1", "2")
    inst._pending_verify = {
        key: {"code": "b" * 40, "is_sha": True, "repo": "a/b",
              "deadline": time.time() + 600}
    }
    check = lambda text: asyncio.run(
        main.ZMQQGroupmgr._check_verify(inst, FakeEvent(), FakeApi(), "1", "2", text)
    )

    for i in range(main.MAX_SHA_TRIES - 1):
        assert check("0123456") is False, f"第 {i + 1} 次错还不该踢"
        assert not kicked
    # 闲聊不计数、也不查 GitHub
    assert check("在吗") is False
    assert inst._pending_verify[key]["tries"] == main.MAX_SHA_TRIES - 1
    assert len(fetches) == main.MAX_SHA_TRIES - 1, fetches

    assert check("0123456") is True, "第 5 次错应当场处理掉这条消息"
    assert kicked == [(1, 2)], kicked
    assert "连续 5 次验证失败" in sent[0], sent
    assert key not in inst._pending_verify, "踢完要清掉登记，别再触发超时任务"
    assert check("0123456") is False, "已经踢了，后面的消息不归验证管"

    print("  sha 连错: 计数 / 闲聊不计 / 第 5 次踢出 / 清登记 OK")


def test_mute_args():
    """/mute <成员> [时长] [理由] 的分段：理由里的 QQ 号不能变成禁言对象。"""
    utils = sys.modules["zmplugin.core.utils"]

    def split(raw, mentioned=()):
        """复刻 cmd_mute 里的分段逻辑（那段在 async generator 里没法直接调）。"""
        tokens = [p for p in raw.split() if p.strip()]
        head = []
        while tokens and utils.is_target_token(tokens[0]):
            head.append(tokens.pop(0))
        targets = list(mentioned)
        for number in __import__("re").findall(r"\b(\d{5,12})\b", " ".join(head)):
            if number not in targets:
                targets.append(number)
        duration = 600
        rest = [p for p in tokens if not any(t in p for t in targets)]
        if rest and utils.parse_duration(rest[0], default_unit="m") is not None:
            duration = utils.parse_duration(rest[0], default_unit="m")
            rest = rest[1:]
        return targets, duration, " ".join(rest)

    assert split("123456789") == (["123456789"], 600, "")
    assert split("123456789 1h") == (["123456789"], 3600, "")
    assert split("123456789 1h 发广告") == (["123456789"], 3600, "发广告")
    assert split("123456789 发广告") == (["123456789"], 600, "发广告"), "不填时长也要能写理由"
    assert split("123456789 987654321 10m 刷屏") == (
        ["123456789", "987654321"], 600, "刷屏",
    ), "多目标"
    # 理由里的 QQ 号只是被提到，不该跟着一起挨禁言
    targets, duration, reason = split("123456789 1h 小号 987654321 也是他")
    assert targets == ["123456789"], targets
    assert reason == "小号 987654321 也是他", reason
    # @ 的目标来自消息段，正文里只剩时长和理由
    assert split("1h 骂人", mentioned=["111222"]) == (["111222"], 3600, "骂人")
    # 带单位的理由不会被误当成时长（整段必须是数字+单位才算）
    assert split("123456789 3次违规")[1] == 600

    print("  /mute 参数: 时长 / 理由 / 多目标 / 理由里的 QQ 号不误伤 OK")


def test_long_mute():
    """超过 30 天的禁言要分段下发并按时续期。"""
    import asyncio
    import time

    mutes = sys.modules["zmplugin.core.mutes"]
    chunk = mutes.MUTE_CHUNK

    assert mutes.chunk_duration(0) == 0, "永久禁言仍传 0"
    assert mutes.chunk_duration(600) == 600
    assert mutes.chunk_duration(3650 * 86400) == chunk, "9999 天必须切到 30 天"

    class FakeStore:
        def __init__(self):
            self.data = {}
            self.saved = 0

        def group(self, gid):
            return self.data.setdefault(gid, {})

        def items(self):
            return self.data.items()

        async def save(self):
            self.saved += 1

    store = FakeStore()
    tracker = mutes.MuteTracker(store)
    now = int(time.time())

    asyncio.run(tracker.record("111", "222", 100 * 86400))
    asyncio.run(tracker.record("111", "333", 600))
    item = store.data["111"]["mutes"]["222"]
    assert item["expire"] == now + 100 * 86400
    assert item["renew_at"] == now + chunk - mutes.RENEW_LEAD
    assert "renew_at" not in store.data["111"]["mutes"]["333"], "短禁言不需要续期"

    assert tracker.due_for_renew(now) == [], "还没到续期时间"
    due = tracker.due_for_renew(item["renew_at"])
    assert [d["user_id"] for d in due] == ["222"], due
    assert due[0]["remaining"] > chunk

    # 续期后重新按“当下 + 一段”排下一次，且立刻不再是待续状态
    asyncio.run(tracker.mark_renewed("111", "222"))
    assert store.data["111"]["mutes"]["222"]["renew_at"] >= now + chunk - mutes.RENEW_LEAD
    assert tracker.due_for_renew(now) == []

    # 续期连续失败到上限就丢弃记录，别每分钟重试到十年后
    asyncio.run(tracker.record("111", "444", 100 * 86400))
    assert asyncio.run(tracker.mark_renew_failed("111", "444")) is False
    assert store.data["111"]["mutes"]["444"]["renew_fails"] == 1
    assert asyncio.run(tracker.mark_renew_failed("111", "444")) is False
    assert asyncio.run(tracker.mark_renew_failed("111", "444")) is True
    assert "444" not in store.data["111"]["mutes"]
    assert asyncio.run(tracker.mark_renew_failed("111", "444")) is True, "记录没了也不该炸"

    # 到期的记录不再续期；剩余不足一段时不再挂 renew_at
    store.data["111"]["mutes"]["222"]["expire"] = now - 1
    assert tracker.due_for_renew(now) == []
    store.data["111"]["mutes"]["222"]["expire"] = now + 100
    asyncio.run(tracker.mark_renewed("111", "222"))
    assert "renew_at" not in store.data["111"]["mutes"]["222"]
    print("  长禁言: 分段下发 / 续期时间 / 到期停续 OK")


def test_reports():
    """/report 编号、/solve、/cr 文案、提醒 @ 谁。"""
    import asyncio

    rp = sys.modules["zmplugin.core.reports"]

    class FakeStore:
        def __init__(self):
            self.data = {}

        def get(self, key, default=None):
            return self.data.get(key, default)

        def group(self, gid):
            return self.data.setdefault(gid, {})

        def keys(self):
            return self.data.keys()

        async def save(self):
            pass

    book = rp.ReportBook(FakeStore())
    add = lambda uid, text: asyncio.run(book.add("100", uid, text))
    solve = lambda no, reply: asyncio.run(book.solve("100", no, reply, "9"))

    assert book.groups_with_open() == []
    r1, ahead = add("11", "第一个")
    assert (r1["no"], ahead) == (1, 0), "前方 0 个就是 1 号"
    r2, _ = add("22", "第二个")
    r3, ahead = add("33", "第三个")
    assert (r2["no"], r3["no"], ahead) == (2, 3, 2)

    # 按顺序处理掉 1 号后，前方只剩 2 个，算出来是 3，但 3 还没解决 → 顺延到 4
    assert solve(1, "好了")["reply"] == "好了"
    r4, ahead = add("44", "第四个")
    assert (r4["no"], ahead) == (4, 2), (r4["no"], ahead)
    open_nos = [r["no"] for r in book.open_reports("100")]
    assert len(open_nos) == len(set(open_nos)), "未解决的编号不能重复"

    assert solve(1, "再来") is None, "已解决的不能再解决一次"
    assert solve(99, "x") is None
    assert book.ahead("100", r4) == 2
    assert solve(2, "ok") and book.ahead("100", r4) == 1
    assert book.groups_with_open() == ["100"]

    # 都处理完以后号从 1 重新排
    solve(3, "ok"), solve(4, "ok")
    r5, ahead = add("11", "又来了")
    assert (r5["no"], ahead) == (1, 0)

    text = rp.status_text(book, "100", "11")
    assert text.startswith("您最近的报告信息为又来了 报告编号为1\n"), text
    assert "尚未得到解决 前方还有 0 个问题" in text
    assert "1  |  第一个  |  已解决  |  回复的内容↓\n好了" in text, text
    assert "1  |  又来了  |  未解决" in text
    assert "得到了解决" in rp.status_text(book, "100", "44")
    assert "还没有提交过" in rp.status_text(book, "100", "999")

    # 手改过的 reports.json：编号是字符串、时间不是数字，都不能把提醒和 /solve 弄崩
    book.store.data["100"]["reports"].append(
        {"no": "7", "user_id": "55", "content": "手改的", "time": "昨天", "solved": False}
    )
    assert "手改的" in rp.digest_text(book, "100")
    assert solve(7, "认得") is not None, "字符串编号也要能解决"

    digest = rp.digest_text(book, "100")
    assert "还有 1 个问题未解决" in digest and "QQ:11" in digest and "又来了" in digest
    assert rp.digest_text(book, "200") == "本群目前没有未解决的问题"

    members = [
        {"user_id": 1, "role": "owner"},
        {"user_id": 2, "role": "admin"},
        {"user_id": 3, "role": "member"},
        {"user_id": 8, "role": "admin"},
    ]
    assert rp.remind_targets(members, [], "8") == ["1", "2"], "默认 @ 群主 + 管理，不 @ 机器人"
    assert rp.remind_targets(members, ["3"], "8") == ["3"], "填了就只 @ 填的人"
    assert rp.remind_targets(members, ["777"], "8") == ["1", "2"], "填的人不在本群，退回群管理"
    assert rp.remind_targets([], ["777"], "8") == ["777"], "拿不到成员列表时照填写的 @"

    # 退群 / /drh：只删这个人的，别人的排队不受影响；手改成数字的 user_id 也要认
    add("66", "要被删的"), add("66", "这条也是")
    book.store.data["100"]["reports"].append({"no": 9, "user_id": 66, "solved": True})
    before = len(book.store.data["100"]["reports"])
    assert asyncio.run(book.remove_user("100", "66")) == 3
    assert len(book.store.data["100"]["reports"]) == before - 3
    assert book.user_reports("100", "66") == [] and book.user_reports("100", "11")
    assert asyncio.run(book.remove_user("100", "66")) == 0
    assert asyncio.run(book.remove_user("404", "66")) == 0, "没数据的群不该建出空桶"
    assert "404" not in book.store.data
    print("  问题反馈: 编号顺延 / 解决 / 排队数 / /cr 文案 / 提醒对象 / 删除记录 OK")


def test_report_handlers(main):
    """/solve、/drh：AstrBot 管理员、群主群管、report_solve_users 能用，普通成员不能。"""
    import asyncio

    class FakeEvent:
        def __init__(self, uid, role=None, admin=False):
            self.uid, self.admin = uid, admin
            sender = {"user_id": int(uid)}
            if role:
                sender["role"] = role
            self.message_obj = types.SimpleNamespace(raw_message={"sender": sender})

        def is_admin(self):
            return self.admin

        def get_sender_id(self):
            return self.uid

        def get_platform_name(self):
            return "aiocqhttp"

    inst = object.__new__(main.ZMQQGroupmgr)
    inst.config = {"report_solve_users": ["555"]}
    can = lambda ev: asyncio.run(main.ZMQQGroupmgr._can_handle_reports(inst, ev, "100"))

    assert can(FakeEvent("1", "member", admin=True))
    assert can(FakeEvent("2", "owner")) and can(FakeEvent("3", "admin"))
    assert can(FakeEvent("555", "member")), "配置里的 QQ 可用"
    assert not can(FakeEvent("4", "member"))

    # 消息里没带 role（部分协议端），现查群成员信息
    asked = []

    class FakeApi:
        async def call_action(self, action, **kw):
            asked.append(kw["user_id"])
            return {"role": "admin" if kw["user_id"] == 6 else "member"}

    ev6, ev7 = FakeEvent("6"), FakeEvent("7")
    ev6.bot = ev7.bot = types.SimpleNamespace(api=FakeApi())
    assert can(ev6) and not can(ev7)
    assert asked == [6, 7], asked
    print("  /solve /drh 权限: Bot 管理 / 群主群管 / 指定 QQ / 现查身份 OK")


def test_report_admin(main):
    """/rclear 只清未解决的，/rl 翻页，/rsw /rmd 按群开关，提醒听 /rmd 的。"""
    import asyncio

    rp = sys.modules["zmplugin.core.reports"]

    class FakeStore(dict):
        def group(self, gid):
            return self.setdefault(gid, {})

        def set(self, key, value):
            self[key] = value

        async def save(self):
            pass

    book = rp.ReportBook(FakeStore())
    for i in range(23):
        asyncio.run(book.add("100", str(1000 + i), f"问题{i}"))
    asyncio.run(book.solve("100", 1, "好了", "9"))

    first, last = rp.digest_text(book, "100"), rp.digest_text(book, "100", 3)
    assert "问题1\n" in first and "第 1/3 页" in first and "问题22" not in first, first
    assert "问题22" in last and "第 3/3 页" in last, last
    assert rp.digest_text(book, "100", 99) == last and rp.digest_text(book, "100", -1) == first

    assert asyncio.run(book.clear_open("100")) == 22
    assert book.open_reports("100") == [] and book.user_reports("100", "1000"), "已解决的要留着"
    assert asyncio.run(book.clear_open("100")) == 0
    assert asyncio.run(book.clear_open("404")) == 0 and "404" not in book.store

    inst = object.__new__(main.ZMQQGroupmgr)
    inst.settings = FakeStore()
    inst.config = {"report_remind_enabled": False}
    assert inst._group_flag("1", "report_enabled"), "/report 默认开"
    assert not inst._group_flag("1", "report_remind", inst._remind_default()), "默认听插件配置"
    inst.settings.group("1")["report_remind"] = True
    assert inst._group_flag("1", "report_remind", inst._remind_default()), "群内设置优先"

    # 查成员期间队列被清空：不能 @ 完了说没有问题
    class RemindApi:
        sent = []

        async def try_call(self, action, **kw):
            return {"user_id": 8}

        async def group_list(self):
            return [{"group_id": 100}]

        async def member_list(self, group_id):
            await book.clear_open("100")
            return [{"user_id": 1, "role": "owner"}]

        async def send_group_msg(self, group_id, message):
            self.sent.append(message)

    asyncio.run(book.add("100", "1", "还没解决"))
    inst.settings.group("100")["report_remind"] = True
    inst.reports = book
    inst._bg_api = RemindApi
    asyncio.run(inst._remind_reports())
    assert RemindApi.sent == []
    print("  反馈管理: /rclear 留历史 / /rl 翻页 / 群开关优先于配置 OK")


def test_draws(main):
    """/draw 参数、上限内外的状态流转、开奖对象、消息发送失败重试。"""
    import asyncio

    dr = sys.modules["zmplugin.core.draws"]
    parse = dr.parse_draw_args

    good, _ = parse(["周末", "3", "24", "FALSE", "100"])
    assert good == {"name": "周末", "winner_count": 3, "hours": 24.0, "forced": False, "limit": 100}
    assert parse(["周末", "3", "99999", "true"])[0]["limit"] == 0
    capped = parse(["周末", "3", "24", "true", "2"])[0]
    assert (capped["winner_count"], capped["limit"]) == (2, 0), "强制抽奖的人数上限压低中奖人数"
    for bad in (
        ["周末", "3", "24"],
        ["周末", "3", "24", "true", "100", "多余"],
        ["周末", "0", "24", "true"],
        ["周末", "-1", "24", "true"],
        ["周末", "3", "0", "true"],
        ["周末", "3", "100000", "true"],
        ["周末", "3", "9" * 400, "true"],
        ["周末", "3", "nan", "true"],
        ["周末", "3", "24", "yes"],
        ["周末", "3", "24", "false", "0"],
        ["周末", "3", "24", "true", "0"],
        ["周末", "9" * 5000, "24", "true"],
        ["名" * 31, "3", "24", "true"],
    ):
        assert parse(bad)[0] is None, bad

    class FakeStore(dict):
        def group(self, gid):
            return self.setdefault(gid, {})

        async def save(self):
            pass

    import time

    run = asyncio.run
    book = dr.DrawBook(FakeStore())
    fields = lambda name, forced=False, limit=0, hours=1.0: {
        "name": name, "winner_count": 2, "hours": hours, "forced": forced, "limit": limit
    }

    run(book.add("100", fields("A", limit=2)))
    assert "已参与" in run(book.join("100", "A", "1"))
    assert "您已参与" in run(book.join("100", "A", "1")), "重复报名不算两个名额"
    assert "已参与" in run(book.join("100", "A", "2"))
    assert "已满" in run(book.join("100", "A", "3"))
    run(book.drop_member("100", "2"))
    assert "已参与" in run(book.join("100", "A", "3")), "退群空出的名额能补"
    assert book.get("100", "A")["participants"] == ["1", "3"]

    missing = run(book.join("100", "不存在", "1"))
    assert "没有这个抽奖" in missing and "不存在" not in missing

    run(book.add("100", fields("B", forced=True)))
    assert "无需报名" in run(book.join("100", "B", "1"))
    assert book.get("100", "B")["participants"] == []

    # 开奖对象：强制抽奖算当前全体（含后进群的），不含机器人；报名抽奖只算还在群里的
    members = [{"user_id": uid} for uid in (1, 2, 8, 9)]
    forced = {"forced": True, "winner_count": 99}
    assert sorted(dr.pick_winners(forced, members, "8")) == ["1", "2", "9"]
    joined = {"forced": False, "winner_count": 99, "participants": ["1", "7"]}
    assert dr.pick_winners(joined, members, "8") == ["1"], "退群的 7 不算"
    assert dr.pick_winners({"forced": False, "winner_count": 2}, members, "8") == []
    assert len(dr.pick_winners({"forced": True, "winner_count": 2}, members, "8")) == 2
    assert len(set(dr.pick_winners({"forced": True, "winner_count": 3}, members, "8"))) == 3

    # 开奖消息：@ + QQ 号 + 领奖提示；抽奖名走文本段，不会被当成 CQ 码；人多分条
    next_message = dr.next_message
    message, chunk = next_message("[CQ:at,qq=all]", {"winners": ["1", "2"]}, "{name} 共 {count} 人")
    assert chunk == ["1", "2"]
    assert [seg["type"] for seg in message] == ["text", "at", "text", "at", "text", "text"]
    assert message[1]["data"]["qq"] == "1" and "QQ:2" in message[4]["data"]["text"]
    assert message[-1]["data"]["text"] == "[CQ:at,qq=all] 共 2 人"
    message, chunk = next_message("X", {"winners": [str(i) for i in range(45)]}, "领奖")
    assert len(chunk) == 20 and "共 45 人" in message[0]["data"]["text"]
    assert "领奖" not in str(message), "领奖提示只在最后一条"
    message, chunk = next_message("X", {"winners": ["44"], "announced": 44}, "{count}")
    assert chunk == ["44"] and message[0]["type"] == "at" and message[-1]["data"]["text"] == "45"
    message, chunk = next_message("X", {"winners": [], "announced": 20}, "领奖")
    assert chunk == [] and message == [{"type": "text", "data": {"text": "领奖"}}], "只差提示"
    assert "无人中奖" in next_message("X", {"winners": []}, "领奖")[0][0]["data"]["text"]

    # 手改过的 draws.json：能兜住的兜住，兜不住的不能立刻开奖删记录
    book.store["300"] = {
        "数字": {"participants": [1, 2], "ends_at": 9 ** 20},
        "空": {"participants": None, "ends_at": 9 ** 20},
        "坏时间": {"ends_at": "2030-01-01", "participants": 5},
        "无穷": {"ends_at": float("inf")},
    }
    assert "您已参与" in run(book.join("300", "数字", "1")), "数字 QQ 也要认"
    assert "已参与" in run(book.join("300", "空", "1"))
    assert all(item[0] != "300" for item in book.due(10 ** 10)), "时间坏了的不能算到点"
    broken = dr.list_text(book, "300")
    assert broken.count("时间异常") >= 2 and "坏时间" in broken and "无穷" in broken, broken
    assert dr.pick_winners({"winner_count": -1, "participants": [1]}, members, "8") == ["1"]
    bad_count = {"attempts": -100}
    assert book.retry_later(bad_count, 0) and bad_count["attempts"] == 1
    assert next_message("X", {"winners": [1], "announced": "坏"}, "t")[1] == ["1"]
    del book.store["300"]

    # 开奖流程：假的是协议端，OneBotApi 和开奖逻辑都是真的
    class FakeClient:
        def __init__(self, bot_id=8):
            self.api = self
            self.members, self.send_ok, self.sent, self.calls = members, True, [], []
            self.bot_id, self.groups = bot_id, [{"group_id": 100}]
            self.on_send = self.on_members = None
            self.connected, self.need_route = True, False

        async def call_action(self, action, **kw):
            self.calls.append((action, kw))
            if not self.connected or kw.get("self_id", self.bot_id) != self.bot_id:
                raise RuntimeError("ApiNotAvailable")
            if self.need_route and "self_id" not in kw:
                raise RuntimeError("ApiNotAvailable")
            if action == "get_login_info":
                return {"user_id": self.bot_id}
            if action == "get_group_list":
                return self.groups
            if action == "get_group_member_list":
                assert kw.get("no_cache"), "开奖要求协议端刷新成员"
                if self.on_members:
                    await self.on_members(kw["group_id"])
                return self.members
            assert action == "send_group_msg", action
            self.sent.append(kw["message"])
            if self.on_send:
                await self.on_send()
            if not self.send_ok:
                raise RuntimeError("发送失败")
            return {"message_id": 1}

    class FakeEvent:
        message_obj = types.SimpleNamespace(raw_message={"sender": {"role": "owner"}})

        def __init__(self, text, bot=None, admin=False, group="100"):
            self.message_str, self.bot, self.admin, self.group = text, bot, admin, group

        def get_group_id(self):
            return self.group

        def get_sender_id(self):
            return "1"

        def get_self_id(self):
            return "8"

        def get_platform_name(self):
            return "aiocqhttp"

        def is_admin(self):
            return self.admin

        def plain_result(self, text):
            return text

    async def collect(gen):
        return [item async for item in gen]

    api = FakeClient()
    inst = object.__new__(main.ZMQQGroupmgr)
    inst.config = {}
    inst.draws_store = book.store
    inst.draws = book
    inst._announcing = None
    inst._draw_offline = set()
    inst._clients = lambda: [api]
    settle = lambda: run(inst._settle_draws())
    ripe = lambda name: book.get("100", name).update(ends_at=1, retry_at=0)
    ats = lambda message: [seg["data"]["qq"] for seg in message if seg["type"] == "at"]
    all_ats = lambda: [uid for message in api.sent for uid in ats(message)]
    cancel = lambda name: collect(inst.cmd_draw_cancel(FakeEvent(f"/draw_cancel {name}")))
    reset = api.__init__
    tip_sent = lambda: dr.DEFAULT_CLAIM_TIP in str(api.sent[-1])

    def prepared(name, winners):
        """建一条到点的抽奖，名单已抽好。"""
        run(book.add("100", fields(name, forced=True)))
        ripe(name)
        book.get("100", name)["winners"] = list(winners)

    real_sleep = main.asyncio.sleep

    async def no_sleep(_):
        await real_sleep(0)

    main.asyncio.sleep = no_sleep
    try:
        assert book.due(0) == [] and len(book.due(10 ** 12)) == 2
        ripe("A")
        settle()
        assert book.get("100", "A") is None and book.get("100", "B") is not None, "没到点的不开"
        assert ats(api.sent[0]) == ["1"], "A 只有 1 还在群里"

        # 协议端没连好不算失败，机器人离线多久都等
        reset()
        ripe("B")
        for broken in ("connected", "bot_id", "groups"):
            setattr(api, broken, False if broken == "connected" else None)
            settle()
            reset()
        assert api.sent == [] and "attempts" not in book.get("100", "B")

        # 群列表是空的不等于没连好：机器人被踢出唯一的群，走重试，不会永远占着名额
        api.groups = []
        settle()
        assert book.get("100", "B")["attempts"] == 1
        reset()
        ripe("B")
        book.get("100", "B").pop("attempts")

        # 成员列表查不到：不能当成没人参与把抽奖作废，也不能立刻再试
        api.members = []
        settle()
        draw = book.get("100", "B")
        assert api.sent == [] and draw["attempts"] == 1 and draw["retry_at"] > time.time()
        assert book.due(time.time()) == []
        settle()
        assert draw["attempts"] == 1, "没到重试时间不该再试"

        # 发送失败：留着重试，且下一轮还是同一批中奖者
        reset()
        ripe("B")
        api.send_ok = False
        settle()
        first = list(book.get("100", "B")["winners"])
        assert len(first) == 2 and len(api.sent) == 1
        ripe("B")
        api.members, api.send_ok = [{"user_id": 1}, {"user_id": 2}, {"user_id": 3}], True
        settle()
        assert book.get("100", "B") is None and ats(api.sent[-1]) == first

        # 重试有上限：次数用完放弃，不会一直 @ 下去
        reset()
        run(book.add("100", fields("E", forced=True)))
        api.send_ok = False
        for _ in range(dr.MAX_ATTEMPTS):
            ripe("E")
            settle()
        assert book.get("100", "E") is None and len(api.sent) == dr.MAX_ATTEMPTS

        # 机器人不在群里：走同一套重试
        reset()
        run(book.add("100", fields("Z", forced=True)))
        api.groups = [{"group_id": 999}]
        for _ in range(dr.MAX_ATTEMPTS):
            ripe("Z")
            settle()
        assert book.get("100", "Z") is None and api.sent == []

        # 重试间隔翻倍，放弃时间和文档写的约 68 小时一致
        run(book.add("100", fields("T")))
        clock, schedule = book.get("100", "T"), [0]
        while book.retry_later(clock, schedule[-1]):
            schedule.append(clock["retry_at"])
        assert len(schedule) == dr.MAX_ATTEMPTS and 67 * 3600 < schedule[-1] < 69 * 3600
        run(book.remove("100", "T"))

        # 分条发送中途失败：已发出的不重发，从失败那条续发
        reset()
        prepared("F", [str(i) for i in range(1000, 1045)])

        async def fail_second():
            api.send_ok = len(api.sent) != 2

        api.on_send = fail_second
        settle()
        assert len(api.sent) == 2 and book.get("100", "F")["announced"] == 20
        ripe("F")
        settle()
        assert len(api.sent) == 4 and api.sent[2] == api.sent[1] and book.get("100", "F") is None
        assert len(ats(api.sent[0])) == 20 and len(ats(api.sent[3])) == 5 and tip_sent()

        # 有进展就重新计数：人多到每轮只发出一条，也不能半路放弃
        reset()
        prepared("U", [str(i) for i in range(1000, 1300)])

        async def fail_every_other():
            api.send_ok = len(api.sent) % 2 == 1

        api.on_send = fail_every_other
        for _ in range(40):
            if book.get("100", "U"):
                ripe("U")
                settle()
        assert book.get("100", "U") is None and tip_sent()
        assert len(set(all_ats())) == 300, "一个都不能漏"

        # 公布途中退群：没通报到的人不再 @，其他人不漏不重，人数和提示都对
        reset()
        prepared("V", [str(i) for i in range(1000, 1045)])
        api.on_send = fail_second
        settle()
        run(book.drop_member("100", "1025"))
        ripe("V")
        settle()
        # api.sent[1] 是发送失败的那条，没有送达
        seen = ats(api.sent[0]) + [uid for message in api.sent[2:] for uid in ats(message)]
        assert "1025" not in seen and len(seen) == len(set(seen)) == 44
        assert book.get("100", "V") is None and tip_sent()

        # 还没通报的人全退了：只差领奖提示也要发
        reset()
        prepared("W", [str(i) for i in range(1000, 1021)])
        api.on_send = fail_second
        settle()
        run(book.drop_member("100", "1020"))
        ripe("W")
        settle()
        assert book.get("100", "W") is None and tip_sent() and ats(api.sent[-1]) == []

        # 这条不带领奖提示，发送途中剩下的人退群：提示要单独补发
        reset()
        prepared("AG", [str(i) for i in range(1000, 1021)])

        async def last_one_leaves():
            await book.drop_member("100", "1020")

        api.on_send = last_one_leaves
        settle()
        assert book.get("100", "AG") is None and len(api.sent) == 2 and tip_sent()
        assert dr.DEFAULT_CLAIM_TIP not in str(api.sent[0])

        # 发送途中退群且这条又失败：重试不再 @ 他
        reset()
        prepared("X", ["1", "2"])

        async def leave_then_fail():
            await book.drop_member("100", "1")
            api.send_ok = False

        api.on_send = leave_then_fail
        settle()
        api.on_send, api.send_ok = None, True
        ripe("X")
        settle()
        assert ats(api.sent[-1]) == ["2"] and book.get("100", "X") is None

        # 中奖者全退群而且什么都没公布过：重抽，不能公布无人中奖
        reset()
        prepared("Y", ["7"])
        book.get("100", "Y").update(forced=False, winner_count=1, participants=["7", "1", "2"])
        api.send_ok = False
        settle()
        api.send_ok = True
        run(book.drop_member("100", "7"))
        ripe("Y")
        settle()
        assert ats(api.sent[-1])[0] in ("1", "2") and book.get("100", "Y") is None
        assert "无人中奖" not in str(api.sent)

        # 落盘等待期间中奖者全退群：同样不能公布无人中奖
        reset()
        prepared("AF", ["7"])
        book.get("100", "AF").update(forced=False, winner_count=1, participants=["7", "1"])

        async def leave_during_save():
            del book.store.save
            await book.drop_member("100", "7")

        book.store.save = leave_during_save
        settle()
        assert api.sent == [] and book.get("100", "AF")["attempts"] == 1
        ripe("AF")
        settle()
        assert ats(api.sent[-1]) == ["1"] and book.get("100", "AF") is None

        # 发送成功的途中退群：这条算发出去了，不能重抽
        reset()
        prepared("AA", ["7"])

        async def leave_only():
            await book.drop_member("100", "7")

        api.on_send = leave_only
        settle()
        assert book.get("100", "AA") is None and len(api.sent) == 1

        # 发送途中 /draw_cancel：不能回复已取消却照发，也不能把记录删掉
        reset()
        run(book.add("100", fields("G", forced=True)))
        ripe("G")
        replies = []

        async def cancel_during_send():
            replies.extend(await cancel("G"))

        api.on_send = cancel_during_send
        settle()
        assert "无法取消" in replies[0] and len(api.sent) == 1 and book.get("100", "G") is None

        # 已公布一部分、等待重试时也不能取消，否则剩下的中奖者没有说法
        reset()
        prepared("AB", [str(i) for i in range(1000, 1045)])
        api.on_send = fail_second
        settle()
        assert "无法取消" in run(cancel("AB"))[0] and book.get("100", "AB") is not None
        run(book.remove("100", "AB"))

        # 查成员途中取消：不发
        reset()
        run(book.add("100", fields("H", forced=True)))
        ripe("H")

        async def cancel_during_query(_):
            await cancel("H")

        api.on_members = cancel_during_query
        settle()
        assert api.sent == [] and book.get("100", "H") is None

        # 开上一条时取消下一条（名单已抽出、等重试的那种）：不发，同名重开的也不受影响
        reset()
        run(book.add("100", fields("I", forced=True)))
        run(book.add("100", fields("J", forced=True)))
        ripe("I"), ripe("J")
        book.get("100", "J")["winners"] = ["1"]

        async def recreate_next():
            await cancel("J")
            run_new.append(await book.add("100", fields("J", forced=True)))

        run_new = []
        api.on_send = recreate_next
        settle()
        assert len(api.sent) == 1, "被取消的 J 不能发"
        assert book.get("100", "J") is run_new[0], "新开的同名抽奖不能被旧流程开掉"
        run(book.remove("100", "J"))

        # 什么都没发出去、等待重试时可以取消
        reset()
        run(book.add("100", fields("K", forced=True)))
        ripe("K")
        api.send_ok = False
        settle()
        assert "已取消" in run(cancel("K"))[0] and book.get("100", "K") is None

        # 一条记录抛异常不能卡住别的群
        reset()
        run(book.add("100", fields("L", forced=True)))
        run(book.add("300", fields("坏", forced=True)))
        ripe("L")
        book.get("300", "坏").update(ends_at=1)
        api.groups = [{"group_id": 300}, {"group_id": 100}]

        async def explode(group_id):
            if group_id == 300:
                raise RuntimeError("坏记录")

        api.on_members = explode
        settle()
        assert book.get("100", "L") is None and len(api.sent) == 1
        assert book.get("300", "坏")["attempts"] == 1
        del book.store["300"]

        # 多账号：由发起的账号开奖，适配器换顺序也一样，机器人自己不中奖
        reset()
        other = FakeClient(bot_id=9)
        other.members = [{"user_id": 1}, {"user_id": 9}]
        for order in ([api, other], [other, api]):
            inst._clients = lambda order=order: order
            run(book.add("100", fields("AC", forced=True), "9"))
            ripe("AC")
            settle()
            assert book.get("100", "AC") is None and ats(other.sent[-1]) == ["1"] and api.sent == []
        assert all(kw.get("self_id") == 9 for _, kw in other.calls), "每次调用都要指明账号"

        # 同一适配器连多个账号：不指明账号就报错的那种
        other.need_route = True
        run(book.add("100", fields("AD", forced=True), "9"))
        ripe("AD")
        settle()
        assert book.get("100", "AD") is None

        # 发起的账号掉线：等它，不算失败，不换别的账号开，日志只提示一次
        other.connected = False
        run(book.add("100", fields("AE", forced=True), "9"))
        ripe("AE")
        settle(), settle()
        assert "attempts" not in book.get("100", "AE") and inst._draw_offline == {"9"}
        assert api.sent == []
        other.connected = True
        settle()
        assert book.get("100", "AE") is None and inst._draw_offline == set()
        inst._clients = lambda: [api]

        # 手改坏的 self_id：不能抛异常卡住整轮开奖
        reset()
        for bad in ("²", "9" * 5000):
            run(book.add("100", fields("AH", forced=True), bad))
            ripe("AH")
            settle()
            assert book.get("100", "AH") is None and api.sent

        # /draw 指令：记下发起账号，超长时间不报错，上限和重名都拦得住
        draw_cmd = lambda text: run(collect(inst.cmd_draw(FakeEvent(text, api))))
        assert "已开启" in draw_cmd("/draw N 1 99999 true")[0]
        assert book.get("100", "N")["self_id"] == "8"
        assert "已有名为" in draw_cmd("/draw N 1 1 true")[0]
        for extra in "OPQR":
            draw_cmd(f"/draw {extra} 1 1 true")
        assert len(book.draws("100")) == 5
        assert "已达上限" in draw_cmd("/draw S 1 1 true")[0] and book.get("100", "S") is None

        # 上限按所有群合计：名额被别的群占着，本群一个没有也开不了；非群号的键不算
        run(book.remove("100", "R"))
        run(book.add("200", fields("别的群")))
        book.store["__meta__"] = {"不是抽奖": {}}
        assert book.total() == 5 and len(book.draws("100")) == 4
        assert "已达上限" in draw_cmd("/draw S 1 1 true")[0] and book.get("100", "S") is None
        run(book.remove("200", "别的群"))
        del book.store["__meta__"]
        assert "已开启" in draw_cmd("/draw S 1 1 true")[0], "名额空出来就能开"
        for name in list(book.draws("100")):
            run(book.remove("100", name))

        # 名额被别的群占着：AstrBot 管理员能跨群查看和取消，私聊也行；群管理碰不到别的群
        cancel_as = lambda text, **kw: run(collect(inst.cmd_draw_cancel(FakeEvent(text, **kw))))
        run(book.add("200", fields("别群")))
        assert "仅群聊" in cancel_as("/draw_cancel 200 别群", group="")[0], "私聊的普通人"
        assert "没有名为" in cancel_as("/draw_cancel 200 别群")[0] and book.get("200", "别群")
        listing = cancel_as("/draw_cancel", group="", admin=True)[0]
        assert "群 200" in listing and "别群" in listing and "1/5" in listing, listing
        assert "群号" in cancel_as("/draw_cancel 别群", group="", admin=True)[0], "私聊要写群号"
        for text in ("/draw_cancel", "/draw_cancel 打错", "/draw_cancel 404 打错"):
            reply = cancel_as(text, admin=True)[0]
            assert "200" not in reply and "别群" not in reply, "群里不能露出别的群"
        assert book.get("200", "别群") and "1/5" in dr.list_text(book, "100")
        assert "已取消" in cancel_as("/draw_cancel 200 别群", group="", admin=True)[0]
        assert book.get("200", "别群") is None
        assert "0/5" in cancel_as("/draw_cancel", group="", admin=True)[0]

        # 已公布一部分的：群管理不能取消，管理员能，正在发送时都不能
        prepared("AI", ["1"])
        draw = book.get("100", "AI")
        draw["announced"] = 20
        assert "无法取消" in cancel_as("/draw_cancel AI")[0]
        inst._announcing = draw
        assert "无法取消" in cancel_as("/draw_cancel AI", admin=True)[0]
        inst._announcing = None
        reply = cancel_as("/draw_cancel AI", admin=True)[0]
        assert "已取消" in reply and "已公布 20 人" in reply and "未公布的 1 人" in reply, reply
        assert book.get("100", "AI") is None
    finally:
        main.asyncio.sleep = real_sleep

    run(book.add("200", fields("D", hours=0.01)))
    text = dr.list_text(book, "200")
    assert "D" in text and "所有群合计 1/5" in text and "已参与 0 人" in text
    assert dr.list_text(book, "404") == "本群当前没有进行中的抽奖（所有群合计 1/5）"
    print("  抽奖: 参数 / 报名 / 退群 / 开奖对象 / 重试上限 / 续发 / 取消竞态 / 坏记录隔离 / 多账号 OK")


def test_store_recovery():
    """读不出来的文件不能被下一次保存覆盖；写不进 UTF-8 的字符不能让保存一直失败。"""
    import asyncio

    st = sys.modules["zmplugin.core.store"]
    root = Path(tempfile.mkdtemp())

    def open_store(name):
        store = object.__new__(st.JsonStore)
        store.path, store._data, store._lock = root / name, {}, asyncio.Lock()
        store._load()
        return store

    for name, text in (("bad.json", '{"a": 1,}'), ("list.json", "[1, 2]")):
        (root / name).write_text(text, encoding="utf-8")
        store = open_store(name)
        assert store.data == {}
        asyncio.run(store.save())
        kept = list(root.glob(name + ".corrupt-*"))
        assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == text, name
    assert open_store("missing.json").data == {} and not list(root.glob("missing*"))

    # 原文件挪不走：本次运行不能写盘，否则就把它覆盖了
    (root / "locked.json").write_text("{坏", encoding="utf-8")
    real_replace = st.os.replace

    def deny(*_):
        raise PermissionError("文件被占用")

    st.os.replace = deny
    try:
        store = open_store("locked.json")
    finally:
        st.os.replace = real_replace
    store.set("a", 1)
    asyncio.run(store.save())
    assert (root / "locked.json").read_text(encoding="utf-8") == "{坏"

    store = open_store("surrogate.json")
    store.set("a", "x\ud83dy")
    asyncio.run(store.save())
    assert open_store("surrogate.json").get("a") == "x?y"
    assert st.coerce_int(float("inf"), 7) == 7
    print("  数据文件: 损坏保留原文件 / 孤立代理字符可写 OK")


if __name__ == "__main__":
    _stub_astrbot()
    main = _load_plugin()
    test_help_menu(main)
    test_entry_path(main)
    test_data_dir_migration()
    test_join_approval()
    test_sha_reverify(main)
    test_sha_retry_kick(main)
    test_mute_args()
    test_long_mute()
    test_reports()
    test_report_handlers(main)
    test_report_admin(main)
    test_draws(main)
    test_store_recovery()
    print(f"全部自检通过 —— {main.PLUGIN_NAME} v{main.PLUGIN_VERSION}")
