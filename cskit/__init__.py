"""cskit — Codex/CC Switch 运维工具集。

三个子命令共享同一套底层实现：

- ``cskit fix``：切换 Provider 后同步 ``config.toml`` 与 ``threads`` 表
- ``cskit export``：将 Codex 可见对话只读导出为 Markdown
- ``cskit clone``：把旧会话的纯对话上下文克隆到当前 Provider 的新会话
"""

__version__ = "0.1.0"
