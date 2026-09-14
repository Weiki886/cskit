<div align="center">

# cskit

**Codex / CC Switch 运维工具集。** 在 CC Switch 切换 Provider 后，用三个子命令完成会话同步、
对话导出与会话安全克隆——默认只读，唯一的写路径带确认、预览与备份。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

**目录：** [快速开始](#快速开始) · [特性](#特性) · [安装](#安装) · [常见任务](#常见任务) ·
[工作原理](#工作原理) · [安全边界](#安全边界) · [排错](#排错) · [已知限制](#已知限制) ·
[开发](#开发) · [设计文档](#设计文档) · [贡献](#贡献)

</div>

---

cskit 包含三个子命令：`fix` 从 `config.toml` 读取当前 Provider 与模型并同步到 Codex SQLite，让
切换 Provider 后消失的历史会话重新出现；`export` 把侧边栏可见对话只读导出为 Markdown；`clone`
从混入跨 Provider Responses item 的旧会话创建一个当前 Provider 能正常续聊的干净新会话。

## 快速开始

```sh
# 1. 克隆并安装（启动器写入 ~/.local/bin/cskit，指向当前 checkout）
git clone https://github.com/Weiki886/cskit.git && cd cskit
./install.sh

# 2. 确认安装，并只读列出侧边栏当前可见的会话
cskit --version
cskit export --list

# 3. 写操作先预览：查看将同步的 Provider、模型与影响行数
cskit fix --dry-run
```

若安装器提示 `~/.local/bin` 不在 `PATH` 中，把 `export PATH="$HOME/.local/bin:$PATH"`
加入 shell 配置后重开终端。`cskit export --list` 能看到会话列表，即说明已正确找到本机
Codex 数据。

## 特性

- **纯标准库、零第三方依赖** —— 只使用 Python 标准库（`sqlite3`、`json`、`argparse`、
  `subprocess` 等），Python 3.9 或更高版本即可运行，无需安装任何包。
- **只读优先** —— `export` 与 `clone` 对源数据的读取全部走 `mode=ro` 只读 URI 与
  `PRAGMA query_only = ON`；三个子命令中只有 `fix` 会写数据。
- **写操作可预览、可拒绝** —— `fix` 支持 `--dry-run` 预览、写入前确认与 `--yes`
  跳过确认；数据库写入使用参数化查询，并以 `BEGIN IMMEDIATE` 在修改前取得写锁。
- **按作用域解析配置，缺失即失败** —— 用最小 TOML 顶层解析器读取 `config.toml`，
  section 内同名键不会干扰；当前 Provider 对应的 `[model_providers.<name>]`
  段缺失时直接报错退出，不猜测 `base_url` 或凭据。
- **凭据不进终端、不进仓库** —— `--dry-run` 输出不包含 token；配置备份为仓库外的
  owner-only（`0600`）文件；测试套件内置凭据与个人绝对路径扫描门禁。
- **语义克隆而非修复旧会话** —— `clone` 只读源会话，经 Codex app-server 原生
  `thread/start` 创建新会话，可见对话上下文通过 developer instructions 注入，不搬运
  reasoning、工具状态或任何 Responses item ID。
- **旧命令保留为回滚路径** —— 默认安装不触碰已有的 `fixcode`、`exportcode`、
  `clonecode`；需要兼容命令名时用 `--with-shims`，安装器先备份再创建启动器。
- **双 Python 版本验证** —— 测试套件在系统 Python 3.9.6 与 Homebrew Python 3.14.7
  上均完整通过。

## 安装

要求：

- Python 3.9 或更高版本；
- 本机已有可读取的 Codex 配置与会话；
- 使用 `clone` 时，Codex CLI 可执行文件需要在 `PATH` 中，或通过 `--codex-bin` 指定。

```sh
git clone https://github.com/Weiki886/cskit.git
cd cskit
./install.sh
```

安装脚本把启动器写到 `~/.local/bin/cskit`，指向当前 checkout；以后在仓库里 `git pull`
即可更新代码，无需重新安装。安装目录可用 `CSKIT_BIN_DIR` 覆盖。

已有 `cskit` 启动器时，脚本默认拒绝覆盖；确认要替换时使用：

```sh
./install.sh --force
```

### 兼容旧命令名

默认安装不会触碰已有的 `fixcode`、`exportcode`、`clonecode`。需要让旧名字转到
cskit 时运行：

```sh
./install.sh --with-shims
```

已存在的同名普通文件会先备份到 `~/.cskit-backups`（可用 `CSKIT_BACKUP_DIR`
覆盖），再创建转发到对应子命令的启动器。完整参数以 `cskit <命令> --help` 和
`./install.sh --help` 为准。

## 常见任务

### 切换 Provider 后找回历史会话

先预览当前 Provider、模型和将被更新的线程数量：

```sh
cskit fix --dry-run
```

确认后执行同步；写入前会再次询问：

```sh
cskit fix
```

`fix` 会把 `threads` 表中所有行的 `model_provider` 和 `model` 更新为 `config.toml`
当前选中的值。这是有意的全表更新，不带 `WHERE` 条件。

默认流程会在写数据库前备份 `config.toml`。cskit 不修改该文件，这份副本只用于留档，
而且可能包含有效凭据；不需要留档时可以避免创建副本：

```sh
cskit fix --no-backup
```

### 把对话导出为 Markdown

交互选择会话：

```sh
cskit export
```

按精确标题、唯一 ID 前缀或完整 Thread ID 直接导出：

```sh
cskit export 2BLOG
```

指定输出目录（默认 `~/Desktop/CodexExports`）：

```sh
cskit export 2BLOG --output ~/Desktop/CodexExports
```

导出内容只包含用户和助手在 UI 中可见的消息，不包含 reasoning、工具调用或工具输出。

### 从跨 Provider 旧会话创建干净克隆

先选择源会话并预览名称、目标模型和迁移量，不创建新会话：

```sh
cskit clone --dry-run
```

确认后按标题或 Thread ID 克隆：

```sh
cskit clone --source 2BLOG
```

默认迁移全部可见对话。只想检查将要注入的上下文时运行：

```sh
cskit clone --source 2BLOG --show-context
```

目标 Provider 上下文窗口较小时，可以限制迁移字符数：

```sh
cskit clone --source 2BLOG --max-chars 60000
```

## 工作原理

### 为什么历史会话会消失

Codex 的 `threads` 表会为每个会话保存 `model_provider` 和 `model`。切换 Provider 后，
旧行仍可能保留之前的值，导致桌面端不再展示这些会话。`fix` 从 `config.toml`
顶层读取当前选择，再用参数化 SQL 同步这两列。

如果当前 Provider 对应的 `[model_providers.<name>]` 配置段不存在，`fix`
会报错退出，而不是猜测 `base_url` 或凭据。此时应先通过 CC Switch
或自己的配置流程重新写入完整 Provider 配置。

### 为什么需要克隆而不是修改旧会话

同一会话跨 Provider 使用后，Responses API 历史中可能混入来源不同的 item ID，例如：

```text
Invalid 'input[53].id': 'item_628ec60bce6b401377441429'.
Expected an ID that begins with 'rs'.
```

直接改 rollout JSONL 会破坏 `history_base.end_byte_offset` 与源文件字节位置的一致性。
`clone` 因此只读源会话，提取用户与助手的可见文本，并过滤 reasoning、加密 reasoning、
工具状态和 Provider item ID。

新会话由 Codex app-server 通过 `thread/start`、`turn/start` 和 `thread/name/set`
创建。迁移内容放进 developer instructions，不作为一大段恢复消息显示在 transcript
中；SQLite 行、rollout 与索引仍由 Codex 自己生成。

## 安全边界

| 子命令 | 读取 | 写入 |
| --- | --- | --- |
| `export` | Codex SQLite、rollout JSONL、侧边栏索引 | 指定目录中的 Markdown 文件 |
| `clone` | 同上，以及当前 Provider 配置 | cskit 不直接修改源数据；Codex app-server 创建新会话 |
| `fix` | `config.toml`、Codex SQLite | `threads.model_provider` 与 `threads.model` |

通用 SQLite 读取使用只读 URI 和 `PRAGMA query_only = ON`。`fix`
是唯一直接修改 Codex 数据的子命令：它使用参数化查询，并以 `BEGIN IMMEDIATE`
在修改前获取写锁。

`clone` 不编辑源会话的 SQLite 行或 rollout 文件。它仍会发起一次固定的初始化
turn，因此会调用当前 Provider，并在新会话中留下简短的初始化对话。

## 排错

- **`command not found: cskit`：** 确认 `~/.local/bin` 在 `PATH`
  中（安装器会检测并提示）。也可用 `CSKIT_BIN_DIR` 指定其他安装目录。
- **`fix` 报 Provider 配置段缺失：** 当前 `config.toml`
  中没有该 Provider 的完整配置。用 CC Switch 重新切换一次，或手工补齐
  `[model_providers.<name>]` 段后再运行；cskit 不会替你猜 `base_url` 或凭据。
- **克隆出现在「独立任务」而不是原项目分组：** 项目分组由 Codex
  桌面端在自己的全局状态中维护，`thread/start` 无法设置；创建后手工把会话拖进目标项目即可。
- **`clone` 找不到 Codex 可执行文件：** 用 `--codex-bin /path/to/codex`
  指定，或确保 `codex` 在 `PATH` 中。
- **列表里看不到某个会话：** `export --list` 与 `clone --list`
  只显示侧边栏当前可见的未归档用户会话，与桌面端的过滤规则一致；已归档或非 `user`
  来源的线程不会出现。
- **克隆后仍想限制上下文体积：** 先用 `--show-context`
  查看迁移内容，再用 `--max-chars` 收窄。

## 已知限制

- 当前只在 macOS 上做过实际验证。安装脚本与默认路径遵循 Unix 约定；Linux
  与 Windows 尚未验证。
- cskit 依赖 Codex 本地 SQLite、rollout 和 app-server 协议；Codex
  内部格式变化后可能需要同步更新。
- 克隆不会自动继承源会话在 Codex 侧边栏中的项目分组；创建后需要手工移动。
- `clone` 默认迁移全部可见消息，但目标模型的上下文窗口仍有限。超长会话可使用
  `--max-chars` 缩小上下文。
- `--max-chars` 会从最旧消息开始丢弃；如果最新一条消息本身就超过上限，迁移上下文可能为空。
- `fix` 默认备份的是不会被修改的 `config.toml`，不是 SQLite 数据库。该副本可能包含有效凭据；
  不需要留档时使用 `--no-backup`。
- cskit 读取 CC Switch 已写入的 Codex 配置，但不会调用或配置 CC Switch 本身。

## 开发

运行完整测试：

```sh
python3 -m unittest discover -s tests
```

项目以 Python 3.9 为最低版本。macOS 上可额外用系统 Python 验证兼容性：

```sh
/usr/bin/python3 -m unittest discover -s tests
```

测试包含 Python 3.9 语法兼容、仓库凭据与个人绝对路径扫描，以及 `fix` 测试沙箱化守卫。

## 设计文档

- [`fix` 实现计划](plans/fix-implementation.md) —— FixState、TOML 作用域解析、
  事务写入与备份设计。
- [`threads` 实现计划](plans/threads-implementation.md) —— 共享只读查询、
  侧边栏项目名解析、列表渲染与交互选择。

## 贡献

欢迎 Issue 与 Pull Request；除很小的修复外，请先开 Issue 对齐范围与设计。
提交信息与 PR 标题使用英文。

## 许可证

[MIT](LICENSE)
