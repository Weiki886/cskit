# cskit fix 实现计划

**目标**：将 `fixcode`（49 行 zsh）重写为 Python 子命令 `cskit fix`，增加事务保护、TOML 作用域解析、参数化查询与脱敏输出。

**架构**：FixState 数据类承载当前与目标 provider/model 信息，读走 `toml_util.read_top_level_keys`，写走独立的 `open_database_write`（不共享 `threads.open_database` 的只读模式）。备份走 `shutil.copy2` + `os.chmod`。

**技术栈**：纯标准库（sqlite3, pathlib, shutil, argparse, re, secrets）。

**需求依据**：Issue #2（含审查反馈 18/20/21/B3/A2）。

## 全局约束

- 所有 Python 文件含 `from __future__ import annotations`（3.9 兼容）。
- 无 `match` 语句、无 `typing.get_type_hints()`。
- 无 `tomllib`（3.11+，项目需兼容 3.9）。
- 输出路径不含 token 明文。
- 备份目录在仓库外，权限 0600。

---

### Task 1: FixState 数据类 + 验证函数

**文件**
- 新增：`cskit/fix.py`
- 测试：`tests/test_fix.py`

**接口**
- 产出：`FixState(provider, model, provider_section_present, config_path, db_path)` 与 `verify_state(state) -> None`

**爬梯子**：
- Step 3: `dataclasses.dataclass` 标准库
- Step 3: `pathlib.Path` 标准库

- [ ] **步骤 1：写失败测试**（test_fix_state_creation, test_verify_missing_provider_raises, test_verify_missing_section_raises）
- [ ] **步骤 2：运行并确认失败**
- [ ] **步骤 3：写最小实现**
- [ ] **步骤 4：运行并确认通过**
- [ ] **步骤 5：提交**

### Task 2: load_fix_state 从 config.toml 读取并验证

**文件**
- 修改：`cskit/fix.py`
- 测试：`tests/test_fix.py`

**接口**
- 消费：`toml_util.read_top_level_keys`, `FixState`
- 产出：`load_fix_state(config_path) -> FixState`

- [ ] **步骤 1：写失败测试**（test_load_fix_state_reads_toplevel, test_load_fix_state_missing_provider, test_load_fix_state_missing_section）
- [ ] **步骤 2：运行并确认失败**
- [ ] **步骤 3：写最小实现**
- [ ] **步骤 4：运行并确认通过**
- [ ] **步骤 5：提交**

### Task 3: backup_config 写入前备份

**文件**
- 修改：`cskit/fix.py`
- 测试：`tests/test_fix.py`

**接口**
- 产出：`backup_config(config_path, backup_dir) -> Path`

- [ ] **步骤 1：写失败测试**（test_backup_creates_file, test_backup_permissions_0600, test_backup_outside_repo）
- [ ] **步骤 2：运行并确认失败**
- [ ] **步骤 3：写最小实现**
- [ ] **步骤 4：运行并确认通过**
- [ ] **步骤 5：提交**

### Task 4: sync_threads 写入 SQLite

**文件**
- 修改：`cskit/fix.py`
- 测试：`tests/test_fix.py`

**接口**
- 消费：`FixState`
- 产出：`sync_threads(db_path, provider, model) -> int`（返回更新的行数）

- [ ] **步骤 1：写失败测试**（test_sync_threads_updates_rows, test_sync_threads_parameterized_query, test_sync_threads_transaction_rollback, test_sync_threads_empty_db）
- [ ] **步骤 2：运行并确认失败**
- [ ] **步骤 3：写最小实现**
- [ ] **步骤 4：运行并确认通过**
- [ ] **步骤 5：提交**

### Task 5: format_preview 脱敏格式输出

**文件**
- 修改：`cskit/fix.py`
- 测试：`tests/test_fix.py`

**接口**
- 产出：`format_preview(state, count, *, dry_run=False) -> str`

- [ ] **步骤 1：写失败测试**（test_preview_no_token_leak, test_preview_shows_counts, test_preview_dry_run_banner）
- [ ] **步骤 2：运行并确认失败**
- [ ] **步骤 3：写最小实现**
- [ ] **步骤 4：运行并确认通过**
- [ ] **步骤 5：提交**

### Task 6: run 入口函数与 argparse

**文件**
- 修改：`cskit/fix.py`
- 测试：`tests/test_fix.py`

**接口**
- 产出：`build_parser() -> ArgumentParser`, `run(argv) -> int`

- [ ] **步骤 1：写失败测试**（test_run_dry_run, test_run_yes, test_run_missing_config, test_run_success）
- [ ] **步骤 2：运行并确认失败**
- [ ] **步骤 3：写最小实现**
- [ ] **步骤 4：运行并确认通过**
- [ ] **步骤 5：提交**

### Task 7: 验证全量测试

**文件**
- 全部

**验证**
- [ ] `python3 -m unittest discover -s tests` 在 3.14.7 通过
- [ ] `/usr/bin/python3 -m unittest discover -s tests` 在 3.9.6 通过
- [ ] 密钥扫描：仓库无 token 明文
- [ ] 逐条核对验收标准
