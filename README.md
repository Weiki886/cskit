# cskit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

**处理 Codex Provider 切换后的会话同步、导出与安全克隆。**

```console
$ cskit --help
cskit 0.1.0 — Codex / CC Switch 运维工具集

用法：
  cskit <命令> [选项]

命令：
  fix       切换 Provider 后同步 config.toml 与 threads 表的 provider/model
  export    将 Codex 可见对话只读导出为 Markdown
  clone     把旧会话的纯对话上下文克隆到当前 Provider 的新会话

其他：
  cskit --version        显示版本
  cskit <命令> --help    显示该命令的详细选项

示例：
  cskit export --list
  cskit clone --source 2BLOG --dry-run
```

`fix` 让切换 Provider 后消失的历史会话重新出现在列表中；`export` 把可见对话保存为 Markdown；`clone` 从混入跨 Provider 状态的旧会话创建一个干净的新会话。

[安装](#安装) · [快速开始](#快速开始) · [常见任务](#常见任务) · [工作原理](#工作原理) · [安全边界](#安全边界) · [已知限制](#已知限制) · [开发](#开发)

## 安装

要求：

- Python 3.9 或更高版本；
- 本机已有可读取的 Codex 配置与会话；
- 使用 `clone` 时，Codex CLI 可执行文件需要在 `PATH` 中，或通过 `--codex-bin` 指定。

```bash
git clone https://github.com/Weiki886/cskit.git
cd cskit
./install.sh
```

安装脚本会把启动器写到 `~/.local/bin/cskit`，并让它指向当前 checkout。以后在仓库中执行 `git pull` 即可更新代码，无需重新安装。若 `~/.local/bin` 不在 `PATH` 中，安装脚本会输出配置提示。

已有 `cskit` 启动器时，安装脚本默认拒绝覆盖；确认要替换时使用：

```bash
./install.sh --force
```

## 快速开始

确认安装结果：

```console
$ cskit --version
cskit 0.1.0
```

然后只读列出 Codex 侧边栏当前可见的会话：

```bash
cskit export --list
```

命令会输出 `Codex 侧边栏当前显示的对话：` 和编号列表。能看到列表，说明 cskit 已找到本机 Codex 数据；这条命令不会修改数据库或 rollout。

## 常见任务

### 切换 Provider 后找回历史会话

先预览当前 Provider、模型和将被更新的线程数量：

```bash
cskit fix --dry-run
```

确认结果后执行同步；写入前会再次询问：

```bash
cskit fix
```

`fix` 会把 `threads` 表中所有行的 `model_provider` 和 `model` 更新为 `config.toml` 当前选中的值。这是有意的全表更新，不带 `WHERE` 条件。

默认流程会在写数据库前备份 `config.toml`。cskit 不修改该文件，这份副本只用于留档，而且可能包含有效凭据；不需要留档时可以避免创建副本：

```bash
cskit fix --no-backup
```

### 把对话导出为 Markdown

交互选择会话：

```bash
cskit export
```

按精确标题、唯一 ID 前缀或完整 Thread ID 直接导出：

```bash
cskit export 2BLOG
```

指定输出目录：

```bash
cskit export 2BLOG --output ~/Desktop/CodexExports
```

导出内容只包含用户和助手在 UI 中可见的消息，不包含 reasoning、工具调用或工具输出。

### 从跨 Provider 旧会话创建干净克隆

先选择源会话并预览名称、目标模型和迁移量，不创建新会话：

```bash
cskit clone --dry-run
```

确认后按标题或 Thread ID 克隆：

```bash
cskit clone --source 2BLOG
```

默认迁移全部可见对话。只想检查将要注入的上下文时运行：

```bash
cskit clone --source 2BLOG --show-context
```

目标 Provider 上下文窗口较小时，可以限制迁移字符数：

```bash
cskit clone --source 2BLOG --max-chars 60000
```

### 继续使用旧命令名

默认安装不会触碰已有的 `fixcode`、`exportcode` 或 `clonecode`。需要把这些名字改为 cskit 兼容入口时运行：

```bash
./install.sh --with-shims
```

这个选项会先把已有的同名普通文件备份到 `~/.cskit-backups`，再创建兼容启动器。完整参数以 `cskit <命令> --help` 和 `./install.sh --help` 为准。

## 工作原理

### 为什么历史会话会消失

Codex 的 `threads` 表会为每个会话保存 `model_provider` 和 `model`。切换 Provider 后，旧行仍可能保留之前的值，导致桌面端不再展示这些会话。`fix` 从 `config.toml` 顶层读取当前选择，再用参数化 SQL 同步这两列。

如果当前 Provider 对应的 `[model_providers.<name>]` 配置段不存在，`fix` 会报错退出，而不是猜测 `base_url` 或凭据。此时应先通过 CC Switch 或自己的配置流程重新写入完整 Provider 配置。

### 为什么需要克隆而不是修改旧会话

同一会话跨 Provider 使用后，Responses API 历史中可能混入来源不同的 item ID，例如：

```text
Invalid 'input[53].id': 'item_628ec60bce6b401377441429'.
Expected an ID that begins with 'rs'.
```

直接改 rollout JSONL 会破坏 `history_base.end_byte_offset` 与源文件字节位置的一致性。`clone` 因此只读源会话，提取用户与助手的可见文本，并过滤 reasoning、加密 reasoning、工具状态和 Provider item ID。

新会话由 Codex app-server 通过 `thread/start`、`turn/start` 和 `thread/name/set` 创建。迁移内容放进 developer instructions，不作为一大段恢复消息显示在 transcript 中；SQLite 行、rollout 与索引仍由 Codex 自己生成。

## 安全边界

| 子命令 | 读取 | 写入 |
| --- | --- | --- |
| `export` | Codex SQLite、rollout JSONL、侧边栏索引 | 指定目录中的 Markdown 文件 |
| `clone` | 同上，以及当前 Provider 配置 | cskit 不直接修改源数据；Codex app-server 创建新会话 |
| `fix` | `config.toml`、Codex SQLite | `threads.model_provider` 与 `threads.model` |

通用 SQLite 读取使用只读 URI 和 `PRAGMA query_only = ON`。`fix` 是唯一直接修改 Codex 数据的子命令：它使用参数化查询，并以 `BEGIN IMMEDIATE` 在修改前获取写锁。

`clone` 不编辑源会话的 SQLite 行或 rollout 文件。它仍会发起一次固定的初始化 turn，因此会调用当前 Provider，并在新会话中留下简短的初始化对话。

## 已知限制

- 当前只在 macOS 上做过实际验证。安装脚本与默认路径遵循 Unix 约定；Linux 与 Windows 尚未验证。
- cskit 依赖 Codex 本地 SQLite、rollout 和 app-server 协议；Codex 内部格式变化后可能需要同步更新。
- 克隆不会自动继承源会话在 Codex 侧边栏中的项目分组；创建后需要手工移动。
- `clone` 默认迁移全部可见消息，但目标模型的上下文窗口仍有限。超长会话可使用 `--max-chars` 缩小上下文。
- `--max-chars` 会从最旧消息开始丢弃；如果最新一条消息本身就超过上限，迁移上下文可能为空。
- `fix` 默认备份的是不会被修改的 `config.toml`，不是 SQLite 数据库。该副本可能包含有效凭据；不需要留档时使用 `--no-backup`。
- cskit 读取 CC Switch 已写入的 Codex 配置，但不会调用或配置 CC Switch 本身。

## 开发

运行完整测试：

```bash
python3 -m unittest discover -s tests
```

项目以 Python 3.9 为最低版本。macOS 上可额外用系统 Python 验证兼容性：

```bash
/usr/bin/python3 -m unittest discover -s tests
```

测试包含 Python 3.9 语法兼容、仓库凭据与个人绝对路径扫描，以及 `fix` 测试沙箱化守卫。

## License

[MIT](LICENSE)
