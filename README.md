# cskit

在 CC Switch 与 Codex 之间来回切换 Provider 时，会遇到三类反复出现的麻烦。cskit 把它们收成三个子命令。

```
cskit fix       切完 Provider，历史会话从列表里消失了
cskit export    想把某个对话存成 Markdown
cskit clone     旧会话报 400，需要一个当前 Provider 能接着聊的新会话
```

纯 Python 标准库，无第三方依赖，Python 3.9+。

## 安装

```bash
git clone https://github.com/Weiki886/cskit.git
cd cskit
./install.sh
```

装完 `cskit --help` 应该能跑。若 `~/.local/bin` 不在 `PATH` 里，`install.sh` 会提示你加。

已经在用 `fixcode` / `exportcode` / `clonecode` 的话，它们不会被动到——那是回滚路径。想让旧命令名指向新实现：

```bash
./install.sh --with-shims
```

同名文件存在时 `install.sh` 拒绝覆盖，除非显式 `--force`；`--force` 也会先把原文件备份到仓库外再动手。

## cskit fix

切换 Provider 后，Codex 侧边栏里的历史会话可能整批消失。原因是 `threads` 表里每行都记着当初用的 `model_provider` 和 `model`，和 `config.toml` 现在选中的对不上，桌面端就不显示了。

`fix` 把表里所有行同步成当前配置的值。

```bash
cskit fix --dry-run    # 先看会改什么
cskit fix              # 写入前会问一次
cskit fix --yes        # 跳过确认
```

`--dry-run` 只打印 Provider 名、模型名和受影响行数，不碰数据。

两点值得知道：

**这是全表更新，没有 WHERE。** 切 Provider 时所有会话都需要新值，所以这是有意的，和原来的 shell 脚本一致。

**`[model_providers.<name>]` 段缺失时它会报错退出，不会替你补。** 那个段里有 `base_url` 和凭据，cskit 猜不出来；补一个不完整的段只会得到一份看着修好了、实际连不上的配置。遇到这个提示，去 CC Switch 里把该 Provider 重新切一次就行。

## cskit export

把对话导成 Markdown，只读，不改 Codex 任何数据。

```bash
cskit export --list           # 列出当前可见对话
cskit export                  # 交互选一个
cskit export 2BLOG            # 按标题前缀或会话 ID
cskit export -o ~/Desktop     # 默认 ~/Desktop/CodexExports
```

导出的是 UI 里真正看得见的用户与助手消息。reasoning、工具调用、工具输出都不包含。

## cskit clone

同一个 Codex 会话如果跨 Provider 用过，`/responses` 可能开始返回 400：

```
Invalid 'input[53].id': 'item_628ec60bce6b401377441429'.
Expected an ID that begins with 'rs'.
```

因为会话里混进了不同 Provider 生成的 Responses API item ID。这种会话没法原地修——改 rollout JSONL 会让 `history_base.end_byte_offset` 和实际文件对不上，换来一个 `cutoff byte offset is past the source rollout`。

`clone` 换个思路：原会话完全不动，只把纯对话内容提出来，让 Codex 自己创建一个新会话装进去。

```bash
cskit clone --list
cskit clone --dry-run              # 看看会迁什么
cskit clone --source 2BLOG
cskit clone --show-context         # 只打印将要迁移的上下文
cskit clone --no-context           # 只要个同名空会话
```

新会话由 Codex 的 app-server 原生创建（`thread/start` → `turn/start` → `thread/name/set`），rollout、SQLite 行、索引条目都是 Codex 自己写的，cskit 不伪造内部结构。

迁移的只有用户和助手的可见消息。`rs_` / `item_` / `msg_` 这些 ID、reasoning、加密 reasoning、工具状态一律丢弃——它们正是 400 的来源。

上下文作为 developer instructions 注入，所以新会话的 transcript 里看不到它，但模型能读到。

## 已知边界

**克隆会落在「独立任务」分组，不在源会话的项目下。** 桌面端的项目分组存在 `.codex-global-state.json`（当前 70 条 assignment），而 `threads.project_id` 列 168 行全空——说明桌面端不读那一列。那个文件由桌面端 UI 持有且无文件锁，并发写有损坏整个分组状态的风险，所以 cskit 不碰它。手工拖一下即可。

**`--max-chars` 从最旧一端开始丢消息。** 默认 `0`（全量迁移）。若显式设了上限而最新那条消息本身就超限，结果会是空上下文而非部分内容。

**`fix` 的 `--backup-dir` 名不副实。** 采用「缺段报错」后 `fix` 已经完全不写 `config.toml`，这个备份只是留档。备份文件含活跃 token，虽然强制了 0600、目录 0700、必须是仓库外绝对路径（在 git 工作树内会直接拒绝），但如果你不需要留档，`--no-backup` 更干净。

## 安全边界

| 子命令 | 读 | 写 |
| --- | --- | --- |
| `export` | rollout JSONL、SQLite（只读连接） | 只写导出的 Markdown |
| `clone` | 同上 | 不直接写；由 Codex app-server 创建新会话 |
| `fix` | `config.toml` | `threads` 表的 `model_provider` / `model` 两列 |

SQLite 的读取一律走 `?mode=ro` 加 `PRAGMA query_only=ON`。`fix` 是唯一会写的子命令，写入用参数化查询，并包在 `BEGIN IMMEDIATE` 里——桌面端在持续写这个库，IMMEDIATE 会在动任何一行之前就失败，而不是写到一半才发现冲突。

原会话在任何情况下都不被修改，这是 `clone` 存在的全部理由。

## 开发

```bash
python3 -m unittest discover -s tests
```

181 个测试。3.9 是支持下限，所以改动后最好两个版本都跑一遍：

```bash
/usr/bin/python3 -m unittest discover -s tests   # macOS 自带 3.9
```

测试里有几条守卫是硬约束而非行为测试：3.9 语法兼容、仓库无密钥与个人绝对路径、以及 `fix` 的测试必须全部沙箱化（防止跑测试写到你自己的 `~/.codex`）。
