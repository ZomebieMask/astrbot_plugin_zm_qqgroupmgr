<div align="center">

<img src="https://raw.githubusercontent.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr/main/logo.png" width="110" alt="ZM-QQGroupmgr" />

# ZM-QQGroupmgr

### 一个插件，顶十个 —— AstrBot 全能 QQ 群管理套件

**33 组指令 · 12 大模块 · 从禁言踢人到进群审批、问题反馈、敏感词、刷屏、广告、文件分发、跨群批量操作，一站装完**

[![version](https://img.shields.io/badge/version-1.0.7-blue?style=flat-square)](https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr/releases)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A53.4.0-7B68EE?style=flat-square)](https://astrbot.app)
[![platform](https://img.shields.io/badge/platform-aiocqhttp%20%7C%20nakuru-32CD32?style=flat-square)](https://docs.astrbot.app)
[![license](https://img.shields.io/badge/license-MIT-green?style=flat-square)](https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr/blob/main/LICENSE)
[![stars](https://img.shields.io/github/stars/ZomebieMask/astrbot_plugin_zm_qqgroupmgr?style=flat-square&color=FFD700)](https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr/stargazers)

<!-- 导航用完整地址：README 会被 AstrBot 插件市场等站点二次渲染，纯 #锚点在那边点不动 -->
[快速开始](https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr#-快速开始) ·
[功能总览](https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr#-一眼看懂它能干什么) ·
[指令手册](https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr#-指令手册) ·
[配置项](https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr#️-配置项) ·
[常见问题](https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr#-常见问题)

</div>

---

## 👀 一眼看懂它能干什么

| 模块 | 能力 | 核心指令 |
| :--- | :--- | :--- |
| 🔨 **成员管理** | 禁言（**最长 3650 天**，自动分段续期）/ 解禁 / 全体禁言 / 禁言列表与剩余时长 / 踢人 / 按不活跃天数清理 / 封禁并自动拒绝加群 / 收放管理员 | `/mute` `/muteall` `/mutelist` `/kick` `/ban` `/op` |
| 💬 **消息管理** | 回复即撤 / 批量撤回最近 N 条 / 从协议端拉群历史（连机器人自己和插件启动前的消息也能撤）/ 引用即设群精华 | `/recall` `/star` `/rs` |
| 📮 **问题反馈** | 成员排队提交问题，自动编号；管理员按编号处理并回复；成员随时查进度和历史；未解决的定时提醒并 @ 群管理 | `/report` `/solve` `/cr` `/drh` |
| 🚫 **敏感词** | 命中即撤回 + 禁言，时长按群独立设置；自定义词 / 远程词库 / 混合三种词源；白名单纠偏 | `/sw` |
| 🌊 **刷屏检测** | 滑动窗口条数 + 连续重复内容双重判定，阈值可调，按群开关 | `/antiflood` |
| 🏷️ **名片检测** | 扫群名片里的广告与敏感内容，处理方式可选 warn / reset / mute / kick | `/cardcheck` |
| 🛡️ **广告拦截** | 评分制多维度判定（广告短语 + 联系方式 + 手机号 + 外链 + 促销词），越过阈值自动撤回禁言 | `/adban` `/ad` |
| 🚪 **进群审批** | 入群限时验证码（数字 / 字母 / 混合 / GitHub commit sha），超时踢出；或直接接管 QQ 的「回答正确问题」，答案可固定也可跟着仓库 commit 动态刷新 | `/ja` |
| 📁 **文件仓库** | 上传入库 → 签发**限时下载链接** → 内置 HTTP 服务分发；带下载冷却和版本更新日志 | `/file` `/f dl` |
| 🎫 **群资料管理** | 改群名、换群头像，**群号用 `-` 连接即可跨群批量**（单次上限 20 群），换完自动撤图 | `/g nn` `/g pp` |
| 📢 **公告与迎送** | 发群公告（可置顶、可配图）、入群欢迎、退群提示（可带图），全部支持占位符 | `/bc` `/wel` `/bye` |
| 🎮 **趣味工具** | 群专属头衔、合并转发伪造聊天记录、赛博击杀跨群播报、Minecraft 史莱姆区块查找 | `/title` `/merge` `/kill` `/sf` |

<div align="center">

**不用装五个插件拼一套群管。** 装一个，`/zmhelp` 一条条开。

</div>

---

## 🎯 为什么选 ZM-QQGroupmgr

<table>
<tr><th width="22%">差异点</th><th width="39%">常见群管插件</th><th width="39%">ZM-QQGroupmgr</th></tr>

<tr>
<td><b>跨群批量</b></td>
<td>一个群一条指令，10 个群刷 10 次</td>
<td>✅ <code>/g nn 统一群名 3366-1009-10032</code> —— 群号 <code>-</code> 连接，改名 / 换头像一次搞定，单次最多 20 群</td>
</tr>

<tr>
<td><b>批量撤回</b></td>
<td>只能撤插件运行期间内存里记的消息，机器人自己发的撤不掉</td>
<td>✅ 优先走协议端 <code>get_group_msg_history</code>，<b>插件启动前的历史消息、机器人自己的消息一样撤</b>；协议端不支持才回落内存记录</td>
</tr>

<tr>
<td><b>文件分发</b></td>
<td>要么没有，要么直接甩群文件，链接永久裸奔</td>
<td>✅ 内置文件仓库 + HTTP 服务：<b>限时令牌链接</b>、按人下载冷却、版本更新日志合并转发展示，上传后自动从群里清掉源文件</td>
</tr>

<tr>
<td><b>敏感词</b></td>
<td>一份写死的词库，全局一个禁言时长</td>
<td>✅ 三种词源自由切换（自定义 / 远程 / 混合）+ <b>白名单纠偏</b> + <b>每群独立禁言时长</b>，远程词库可热更新 <code>/sw reload</code></td>
</tr>

<tr>
<td><b>图片类操作</b></td>
<td>必须一条消息带图，手机端很难操作</td>
<td>✅ 换头像 / 发带图公告 / 设退群图，<b>不带图也行</b> —— 机器人等你 1 分钟内补发，成功后自动撤回那张图不留痕</td>
</tr>

<tr>
<td><b>依赖与体积</b></td>
<td>拉一堆三方库，或者起独立数据库</td>
<td>✅ <b>零额外依赖</b>，全异步实现，配置走 AstrBot 内置 KV，约 1.8k 行核心代码好读好改</td>
</tr>

<tr>
<td><b>指令手感</b></td>
<td>指令又长又要背</td>
<td>✅ 全量缩写：<code>/g</code> <code>/bc</code> <code>/sw</code> <code>/f</code> <code>/af</code> <code>/cc</code> <code>/sf</code>，还有中文别名 <code>/群管帮助</code> <code>/退群提示</code></td>
</tr>

</table>

> 上表对比的是「典型的单一功能群管插件」这一类做法，不针对任何具体项目。各家插件各有所长，按需组合即可。

---

## 🚀 快速开始

<table>
<tr><td width="50%" valign="top">

**① 安装（推荐：插件市场）**

AstrBot WebUI → 插件市场 → 搜 `ZM-QQGroupmgr` → 安装

或用 Git：

```bash
cd /path/to/astrbot/data/plugins
git clone https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr.git
```

</td><td width="50%" valign="top">

**② 给机器人群权限**

把机器人设为**群管理员**（部分功能需**群主**）。

**③ 开你想要的功能**

```
/zmhelp              # 看全部指令
/sw on 10            # 敏感词，命中禁言 10 分钟
/antiflood on        # 刷屏检测
/adban on            # 广告拦截
/wel set 欢迎 {at}！  # 入群欢迎
```

</td></tr>
</table>

> 所有开关**按群独立**，一个群开了不影响别的群。

---

## 📖 指令手册

> 🔒 管理类指令仅 **AstrBot 管理员** 可用。对全体群成员开放的只有 `/file download`、`/file list`、`/file log`（查看）、`/merge`、`/slimefinder`、`/report` 和 `/check_report`；`/solve`、`/drh` 本群群主和管理员也能用。
> ⏱️ 时长单位：`s` 秒 · `m` 分 · `h` 时 · `d` 天 · `w` 周。

<details open>
<summary><b>🔨 成员管理</b></summary>

| 指令 | 说明 |
| :--- | :--- |
| `/mute <成员> [时长] [理由]`（`/m`） | 禁言。`<成员>` 必须写在最前（@ 或 QQ 号，可多个），不填时长默认 10 分钟；理由写在时长后面，最长 100 字，`/mutelist` 里能看到 |
| `/unmute <成员>`（`/um`） | 解除禁言 |
| `/mutelist` | 本群在禁成员 + 各自剩余时长、禁言理由与操作者 |
| `/muteall [时长\|off]` | 全体禁言，**不带参数默认永久**，`off` 解除 |
| `/kick <成员>` | 踢出指定成员 |
| `/kick <时间>` | 踢出该时间内未发言的成员，如 `/kick 20d` |
| `/ban <成员>` | 封禁并踢出，之后**自动拒绝其加群申请** |
| `/unban <QQ号>` / `/banlist` | 解封 / 查看封禁列表 |
| `/op <成员>` / `/deop <成员>` | 设置 / 取消群管理员 |
| `/title @成员 <文本>` / `/title unset @成员` | 群专属头衔（QQ 通常只允许群主操作） |

```
/m @张三 30d             禁言 30 天
/m @张三 1h 发广告       禁言 1 小时并记下理由
/m @张三 3650d           禁言 10 年（上限）
/muteall 2h              全群禁言 2 小时
/kick 1m                 清理 1 个月没发言的人
```

> **超长禁言**：QQ 的 `set_group_ban` 单次最多 30 天，传更长的值协议端会直接报错（`retcode 1200`）。
> 插件把 30 天以上的时长切成 30 天一段下发，并在到期前自动续期，直到总时长走完，上限 **3650 天**。
> 续期靠插件后台任务完成，**插件长时间停用期间不会续期**；`/unmute` 会同时终止续期。

</details>

<details>
<summary><b>💬 消息撤回 · 群精华</b></summary>

| 指令 | 说明 |
| :--- | :--- |
| `/recall` | 回复某条消息后使用，撤回被回复的那条 |
| `/recall <数量> [是否含机器人]` | 撤回最近 N 条，第二参数填 `false` 则跳过机器人自己的消息 |
| `/star` | 引用（回复）某条消息后使用，把它设为群精华 |
| `/remove_star`（`/rs`） | 引用某条消息后使用，取消它的群精华 |

```
/recall 20               撤回最近 20 条
/recall 20 false         撤回最近 20 条，不含机器人自己的
```

执行后逐条撤回并汇报：`撤回完成：成功 18 条，失败 2 条（共 20 条）`。失败条目会附消息 ID、发送者和协议端返回的原因，详情同时写日志。

> 优先向协议端拉取群历史记录，所以机器人自己发的、插件启动前的消息同样能撤；协议端不支持 `get_group_msg_history` 时退回插件内存记录（每群 100 条）。
> 机器人需**群管理员或群主**。管理员撤他人消息**没有时限**，2 分钟时限只作用于普通成员撤自己的消息。

</details>

<details>
<summary><b>🚫 敏感词 · 刷屏 · 名片检测</b></summary>

**敏感词**（全称 `/sensitive-words`，缩写 `/sw`）

| 指令 | 说明 |
| :--- | :--- |
| `/sw on [时长]` / `/sw off` | 开关本群拦截。时长**默认单位为分钟**；改时长需先 `off` 再 `on` |
| `/sw add <词>` / `/sw del <词>` | 增删自定义词 |
| `/sw mode <custom\|library\|both>` | 词源：仅自定义 / 仅远程词库 / 混合（默认） |
| `/sw list` / `/sw reload` | 查看词库状态 / 重新拉取远程词库 |

```
/sw on 10                开启，命中撤回并禁言 10 分钟
/sw mode custom          只用管理员添加的词
```

**刷屏 / 名片**

| 指令 | 说明 |
| :--- | :--- |
| `/antiflood on\|off`（`/af`） | 刷屏检测。窗口秒数、条数、重复次数、禁言时长在后台配置 |
| `/cardcheck on\|off`（`/cc`） | 群名片检测。违规处理 `warn` / `reset` / `mute` / `kick` 在后台配置 |

</details>

<details>
<summary><b>🛡️ 广告拦截与群广告</b></summary>

| 指令 | 说明 |
| :--- | :--- |
| `/adban` / `/adban on` / `/adban off` | 切换 / 开启 / 关闭广告拦截 |
| `/ad` | 发布本群已保存的广告 |
| `/ad set <文本>` | 保存广告内容 |
| `/ad clear` / `/ad reset` | 清空 / 恢复默认 |

**评分机制**（阈值 `ad_threshold` 可调，默认 6 分）

| 特征 | 分值 |
| :--- | :--- |
| 广告短语（"加微信""代理"…） | 3 |
| 联系方式（微信号 / QQ 号） | 4 |
| 手机号 | 3 |
| 促销词汇 | 2 |
| 外链 | 2 |

总分 ≥ 阈值 → 自动撤回并禁言（默认 10 分钟）。

</details>

<details>
<summary><b>📁 文件仓库与限时下载</b></summary>

| 指令 | 说明 |
| :--- | :--- |
| `/file upload <name> <时长>` | 上传。执行后**紧接着发送文件**即入库，`<时长>` 为链接有效期 |
| `/file download <name>`（`/f dl`） | 取限时下载链接。**全体成员可用，但只能私聊机器人** |
| `/file download cdreset <成员>` | 重置该成员的下载冷却 |
| `/file log <name> [次数]` | 以合并转发查看最近若干条更新记录 |
| `/file log update <name> <版本> <说明>` | 记一次版本更新 |
| `/file list` / `/file delete <name>` | 查看全部 / 删除 |

```
/file upload guoclient 3m
/f dl guoclient
/file log update guoclient 1.2.0 修复登录闪退
```

**群内上传后的清理逻辑**：机器人是**群主** → 撤回文件消息并尝试删群文件；是**群管理员** → 直接删群文件；**两者都不是** → 提示失败，文件不入库。

在群里发下载指令时机器人只回提示语（默认「需要私聊才可以下载」，可用 `file_private_only_tip` 改）。链接过期后网页显示「链接已失效」（`file_link_expired_tip` 可改）。

</details>

<details>
<summary><b>🎫 群资料管理（跨群批量）</b></summary>

> `/group` 缩写 `/g`。需 AstrBot 管理员，且机器人为目标群群主或管理员。

| 指令 | 说明 |
| :--- | :--- |
| `/group newname <文本> [群号]`（`/g nn`） | 改群名 |
| `/group pp [图片] [群号]`（`/g avatar`） | 改群头像 |

```
/g nn 摸鱼交流群                  改当前群
/g nn 摸鱼交流群 12345678         改指定群
/g nn 统一群名 3366-1009-10032    一次改三个群
/g nn "老年活动中心 2025"          群名以数字结尾时用引号包住
/g pp                            带图 → 立即生效
/g pp 3366-1009-10032            不带图 → 1 分钟内补发图片
```

> 末尾若是纯数字（≥5 位）或 `-` 连接的数字串，会被当成目标群号；群名本身要以数字结尾就加引号。批量单次上限 20 群。
> 上传成功后若机器人是群主/管理员会自动撤回那张图（`avatar_recall` 可关）。

</details>

<details>
<summary><b>📢 群公告 · 入群欢迎 · 退群提示</b></summary>

**群公告** `/broadcast <内容> <true|false>`（`/bc`），第二参数为是否置顶。

```
/bc 本周六 20:00 停服维护 true
/bc 群规已更新，请看精华消息 false
```

- 电脑端可直接把图片插进内容里，一次执行完成
- 只发文字时机器人会追问「是否需要上传图片？」，答 `是` 则等你 1 分钟内发图，答 `否` 直接发纯文本
- 带图公告发布后自动撤回该图（`broadcast_recall` 可关）
- 置顶依赖协议端支持 `pinned`（NapCat 等支持），不支持时公告照发并明确提示

**入群欢迎** `/wel`

| 指令 | 说明 |
| :--- | :--- |
| `/wel` | 手动执行一次 |
| `/wel set <文本>` | 保存内容并开启自动欢迎 |
| `/wel on` / `/wel off` / `/wel reset` / `/wel status` | 开 / 关 / 恢复默认 / 查看 |

**退群提示** `/bye`（别名 `/farewell`、`/退群提示`）

| 指令 | 说明 |
| :--- | :--- |
| `/bye` | 预览当前设置 |
| `/bye set <文本>` | 设置内容并自动开启 |
| `/bye image` / `/bye image clear` | 设置 / 清除附带图片（可随命令带图，或 1 分钟内补发） |
| `/bye on` / `/bye off` / `/bye reset` / `/bye status` | 开 / 关 / 恢复默认 / 查看 |

```
/wel set 欢迎 {at} 加入本群！请阅读群公告
/bye set {name}（{user_id}）{reason}，本群还剩下我们这些人。
```

</details>

<details>
<summary><b>🚪 进群审批</b></summary>

> `/join_approval` 缩写 `/ja`。三种玩法可选，按群独立。

| 指令 | 说明 |
| :--- | :--- |
| `/ja set verification_code <number\|letter\|mix\|sha>`（`/ja set vc`） | 入群后二次验证：机器人发验证码，成员限时回发，超时踢出 |
| `/ja set static <内容>` | 把 `<内容>` 设为本群「需要正确回答问题」的答案 |
| `/ja set dynamic` | 用 GitHub 仓库最新 commit 的 sha 作答案，定时刷新 |
| `/ja off` / `/ja status` | 关闭 / 查看当前设置 |

**① 入群验证码** —— 人已经进群了，验证不过就踢出去

| 类型 | 验证码形式 |
| :--- | :--- |
| `number` | 纯数字，位数由 `join_code_digits` 决定（4 或 6，默认 6） |
| `letter` | 固定 6 位大写英文字母 |
| `mix` | `join_code_digits` 位数字 + 6 个字母，打乱后混排 |
| `sha` | 指定 GitHub 仓库最新 commit 的 sha（**不公布**，成员自己去仓库查，发前 7 位即可） |

```
/ja set vc mix           启用「4/6 位数字 + 6 字母」验证码
/ja set vc sha           机器人接着问你要哪个仓库，发链接给它
```

- 限时由 `join_verify_minutes` 决定（默认 **1** 分钟，最大 **30**），超时**直接踢出**
- 选 `sha` 时机器人回复 `指令执行成功 目前sha值为 <sha>`，之后每 `join_sha_poll_minutes` 分钟刷新一次（默认 **30** 分钟）
- 成员发来的 sha 与缓存对不上时会**当场再查一次 GitHub**（最多每分钟一次），仓库在轮询间隔里又推了新 commit 也照样放行
- 取不到 sha 也照常挂验证，**到点仍然踢出**（只有像 sha 的消息才会触发复核，闲聊不会浪费 API 配额）
- 同一个人连错 **5** 次 sha 直接踢，不等超时（防止拿复核请求刷 GitHub 配额；闲聊不计数）
- 待验证状态只在内存里，**插件重载后未完成的验证会作废**（不会踢人）

**② / ③ 回答正确问题（static / dynamic）** —— 走 QQ 自带的加群审批，人根本进不来

```
/ja set static 你好      本群答案改成「你好」
/ja set dynamic          机器人问你仓库链接，之后答案跟着最新 commit 走
```

- 两者都会先检查本群加群方式是否为「需要正确回答问题」；不是则回复询问，答 `是` 立刻改过去，答 `否` 结束并回复 `收到 :)`（`join_decline_tip` 可改）
- 问题文本在 `join_question_text` 配置，指令里给的是**答案**
- `dynamic` 每次执行都回复 `已将群正确密码更换为动态值 当前sha值为 <sha>`，之后按 `join_sha_poll_minutes` 自动跟新 sha
- 改加群方式用的是 NapCat 扩展接口 `set_group_add_option`，**其他协议端可能不支持**，且机器人需为群主 / 管理员

</details>

<details>
<summary><b>📮 问题反馈</b></summary>

| 指令 | 说明 |
| :--- | :--- |
| `/report <内容>` | 提交问题，自动给编号。**全体成员可用** |
| `/check_report`（`/cr`） | 查看自己最近一次报告的进度和历史报告。**全体成员可用** |
| `/solve <编号> <回复>` | 把该编号标记为已解决，并 @ 报告人附上回复；不带参数时列出全部未解决问题 |
| `/drh <成员>` | 删除该成员在本群的全部报告记录（含未解决的），@ 成员或直接写 QQ 号，可一次写多个 |

```
/report 下载链接打不开          → 报告已收到，报告编号为 3，前方还有 2 个问题等待解决
/solve 3 已经修好了，重新下载即可  → @报告人 您的报告（编号 3）已解决
/cr                             → 查进度和历史
```

`/cr` 的回复（引用你的那条消息）：

```
您最近的报告信息为下载链接打不开 报告编号为3
您的问题尚未得到解决 前方还有 2 个问题等待解决 请您耐心等待 感谢配合！
您的历史报告内容为：
1  |  群文件里的整合包缺 mod  |  已解决  |  回复的内容↓
已经补上了
3  |  下载链接打不开  |  未解决
```

**编号规则**：编号 = 提交时前方未解决的问题数 + 1，前方没有就是 1 号。管理员没按顺序处理时这个号可能还被别的未解决问题占着，那就往后顺延到空号——**未解决的问题之间编号绝不重复**，`/solve` 不会认错人。问题全部处理完以后，编号重新从 1 开始。

- 内容和 `/solve` 的回复都最长 200 字；同一个人最多同时挂 3 个未解决的报告，防止刷队列
- 一条消息装不下太多：定时提醒最多列 10 条，`/cr` 显示最近 5 条历史
- 报告按群分开排队，存在 `reports.json`，重启不丢
- **谁能处理**：`/solve`、`/drh` 除 AstrBot 管理员外，本群群主、群管理员也能用；还要让别人处理，把 QQ 号填进 `report_solve_users`
- 成员退群或被踢后，其报告记录自动删除
- **定时提醒**：每 `report_remind_minutes` 分钟（默认 60）在还有未解决问题的群里列一遍，每条带编号、报告人 QQ、提交时间和内容。没有未解决问题的群不提醒
  - `report_remind_enabled` 开关提醒，默认开
  - `report_remind_at` 提醒时是否 @ 群管理，默认开
  - `report_remind_users` 填了 QQ 号就只 @ 这些人（不在本群的自动跳过）；留空则 @ 本群群主和全部管理员

</details>

<details>
<summary><b>🎮 趣味工具</b></summary>

| 指令 | 说明 |
| :--- | :--- |
| `/merge <标题> <QQ> <内容> [<QQ> <内容> …]` | 构造合并聊天记录，可多组发送者 |
| `/kill <成员> <理由>` | 赛博击杀：在与该成员的共同群同步播报，提醒管理处理 |
| `/slimefinder <版本> <种子>`（`/sf`） | Minecraft 史莱姆区块查找 |
| `/update on\|off` | 本群是否接收插件更新提示，**默认开** |
| `/zmhelp`（`/群管帮助`） | 全部指令总览。群内以合并转发发送，卡片标题即 `ZM-QQGroupmgr v<版本号>`；菜单内容可在后台 `help_menu_text` 自定义 |

```
/merge 对话记录 10001 在吗 10002 不在
/kill @张三 发布广告
/sf 1.20.1 12345678
```

> `/kill` 播报文案在后台 `kill_template` 配置，占位符 `{at}` `{target}` `{name}` `{reason}` `{operator}` `{group_id}`。
> `/update`：插件每 `update_check_days` 天（默认 5，最大 30）查一次 GitHub 最新 release，发现新版本就在开着的群里发一张合并转发卡片（标题 `ZM_QQGroupmgr New-Update-Available!!!`）。同一个版本只提示一次。

</details>

---

## 🔤 占位符

广告、欢迎、退群提示、头衔、击杀模板等文本里通用：

| 占位符 | 含义 |
| :--- | :--- |
| `{at}` | @该用户（退群场景 at 不到时退化为昵称） |
| `{name}` | 用户昵称 |
| `{user_id}` | 用户 QQ 号 |
| `{group_id}` | 群号 |
| `{reason}` | 「退出了本群」/「被移出群聊」（退群提示专用） |
| `{operator}` | 执行操作的管理员（退群提示 / 击杀播报专用） |

---

## ⚙️ 配置项

运行数据**按群独立**保存在插件数据目录（封禁列表、广告与欢迎文本、各功能开关、自定义敏感词、文件仓库与更新日志），用指令设置即可。后台插件配置面板可调：

| 分组 | 配置键 |
| :--- | :--- |
| 🌊 刷屏判定 | `flood_threshold` `flood_window` `flood_repeat_limit` `flood_mute_duration` `flood_recall` `flood_tip` |
| 🚫 敏感词 | `sensitive_default_duration` `sensitive_library_urls` `sensitive_whitelist` `sensitive_tip` |
| 🏷️ 名片检测 | `card_check_enabled` `card_ad_threshold` `card_action` `card_mute_duration` `card_tip` |
| 🛡️ 广告拦截 | `ad_threshold` `ad_mute_duration` `ad_tip` |
| 📁 文件服务 | `file_server_enabled` `file_host` `file_port` `file_base_url` `file_default_ttl` `file_download_cooldown` `file_cooldown_tip` `file_private_only_tip` `file_link_expired_tip` |
| ☠️ 赛博击杀 | `kill_template` `kill_notify_all_groups` |
| 🖼️ 图片交互 | `media_wait_timeout`（等待补发图片/答复秒数，默认 60）`avatar_recall` `broadcast_recall` `farewell_recall`（均默认开启） |
| 🚪 进群审批 | `join_verify_minutes` `join_code_digits` `join_sha_poll_minutes`(默认 30 分钟) `join_question_text` `join_verify_tip` `join_sha_tip` `join_pass_tip` `join_timeout_tip` `join_decline_tip` |
| 📮 问题反馈 | `report_remind_enabled`（默认开）`report_remind_minutes`（默认 60）`report_remind_at`（默认开）`report_remind_users`（留空 = 全体群管理）`report_solve_users`（额外可用 `/solve` `/drh` 的 QQ） |
| 🔔 更新通知 | `update_check_days` `update_tip` |
| 📜 帮助菜单 | `help_menu_text` —— 留空用内置完整菜单；填写后 `/zmhelp` 只显示你写的内容，支持 `{name}` `{version}` `{cooldown}` 三个占位符 |

### 🔐 下载服务安全提醒

内置下载服务**不做身份校验**，仅凭一次签发的限时令牌访问，且不提供目录浏览。`file_host` 默认 `0.0.0.0`（监听所有网卡）——**若不需要公网访问，请改为 `127.0.0.1`**，或用防火墙 / 反向代理限制来源。

---

## 🔑 权限要求

| 权限 | 用途 |
| :--- | :--- |
| ✅ 群管理员 / 群主 | 禁言、踢人、撤回他人消息、改群资料、设置 / 取消群精华 |
| ✅ 群主 | 设置管理员、设置群头衔 |

---

## ❓ 常见问题

<details>
<summary><b>指令没反应？</b></summary>

先确认三点：① 你是 AstrBot 管理员（管理类指令有权限门槛）；② 机器人在该群是管理员或群主；③ 协议端是 `aiocqhttp` / `nakuru`（其他平台没有 QQ 群管 API）。

</details>

<details>
<summary><b>批量撤回有几条失败？</b></summary>

失败条目会附协议端返回的原因，最常见是超出协议端可拉取的历史范围，或该消息已被撤回。看插件日志有完整详情。

</details>

<details>
<summary><b>设头衔失败？</b></summary>

QQ 侧限制：群专属头衔通常**只有群主**能设置，机器人只是管理员会被拒。

</details>

<details>
<summary><b>敏感词误伤了正常发言？</b></summary>

用后台 `sensitive_whitelist` 加白名单，或 `/sw mode custom` 关掉远程词库只用自己维护的词。广告拦截同理，调高 `ad_threshold` 即可放宽。

</details>

<details>
<summary><b>数据会丢吗？升级插件要重新配一遍吗？</b></summary>

**不用。** 所有运行数据都存在插件目录之外的 `data/plugin_data/ZM-QQGroupmgr/`（封禁列表、各类文本、开关、自定义敏感词、文件仓库、更新日志、问题报告），后台面板里的配置项由 AstrBot 存在 `data/config/` 下。覆盖安装、插件市场更新、`git pull` 都不会碰这两处，升级后原样继续用。

额外保险：插件检测到版本号变化时，会先把数据目录里的 `*.json` 快照到 `data/plugin_data/ZM-QQGroupmgr/backups/<旧版本>-<时间戳>/`。真遇到新版本写坏老数据，把这个目录里的文件拷回上一层即可。

只有两处是内存态、重启会清空：批量撤回用的消息历史（每群 100 条）、进群验证的待验证名单（重载后作废，不会误踢人）。

</details>

<details>
<summary><b>禁言 9999 天报 `retcode 1200`？</b></summary>

那是旧版本的问题：QQ 的 `set_group_ban` 单次上限 30 天，插件把超长时长原样传给了协议端。1.0.6 起改为分段下发 + 自动续期，上限 3650 天。注意续期依赖插件运行，长时间停用期间不会续。

</details>

<details>
<summary><b>批量操作会被风控吗？</b></summary>

频繁操作可能触发 QQ 风控，建议适度使用批量（群资料批量单次上限 20 群就是为此设的）。

</details>

---

## 🙏 致谢

- 广告检测词库参考 [houbb/sensitive-word-data](https://github.com/houbb/sensitive-word-data)，本插件在其基础上收窄为常见商业垃圾信息模式
- 感谢 [AstrBot](https://astrbot.app) 及其社区

## 🔗 相关链接

[AstrBot 官网](https://astrbot.app) · [开发文档](https://docs.astrbot.app) · [插件市场](https://cloud.astrbot.app/market) · [更新日志](https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr/blob/main/CHANGELOG.md) · [提交 Issue](https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr/issues)

## 📄 开源协议

[MIT](LICENSE) © ZM

> 本插件按「原样」提供，用于群组自治与学习研究。敏感词、广告、刷屏判定均基于规则匹配，**可能存在误判或漏判**，请结合本群实际情况调整阈值后使用。因使用本插件导致的账号风控、封号、数据丢失或误操作，作者不承担责任。

---

<div align="center">

**觉得好用的话，点个 ⭐ Star 让更多人看到**

[![Star History Chart](https://api.star-history.com/svg?repos=ZomebieMask/astrbot_plugin_zm_qqgroupmgr&type=Date)](https://star-history.com/#ZomebieMask/astrbot_plugin_zm_qqgroupmgr&Date)

</div>
