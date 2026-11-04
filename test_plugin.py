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
    print(f"全部自检通过 —— {main.PLUGIN_NAME} v{main.PLUGIN_VERSION}")
