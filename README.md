# cskit

Codex / CC Switch 运维工具集。

## 安装

```bash
git clone https://github.com/Weiki886/cskit.git
cd cskit
./install.sh
```

安装后运行 `cskit --help` 查看可用命令。

## 可选：创建兼容命令

```bash
./install.sh --with-shims
```

这会创建 `fixcode`、`exportcode`、`clonecode` 三个兼容命令，指向 `cskit fix`、`cskit export`、`cskit clone`。

## 命令

| 命令 | 作用 |
| --- | --- |
| `cskit fix` | 切换 Provider 后同步 `config.toml` 与 `threads` 表的 provider/model |
| `cskit export` | 将 Codex 可见对话只读导出为 Markdown |
| `cskit clone` | 把旧会话的纯对话上下文克隆到当前 Provider 的新会话 |

## 现有脚本

`fixcode`、`exportcode`、`clonecode` 三个独立脚本仍保留在 `~/.local/bin`，是回滚路径。`cskit` 不会覆盖它们（除非 `--force` 且备份在先）。

## 依赖

纯 Python 标准库，无需第三方包。Python 3.9+。
