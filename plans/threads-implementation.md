# threads.py 实现计划

**目标**：实现 `threads.py` 共享库，统一 SQLite 只读查询、侧边栏项目名解析、会话列表渲染与交互选择。

**架构**：ThreadRecord 数据类作为统一输出类型，`list_threads` 接受 `required_columns` 由调用方控制校验严格度，`open_database` 抽象连接管理。列表渲染与选择函数参数化，消除两份完全相同但写死文案的副本。

**技术栈**：纯标准库（sqlite3, pathlib, json, dataclasses, re, sys）。

**需求依据**：Issue #1 设计规格 + 决策定稿（B8 列校验策略、Q1 错误层次）。

---

### Task 1: open_database + ThreadRecord 数据类

**文件**
- 新增：`cskit/threads.py`
- 测试：`tests/test_threads.py`

**接口**
- 消费：`CskitDataError`（来自 `errors.py`）
- 产出：`open_database(path) -> sqlite3.Connection`、`ThreadRecord` 数据类

**爬梯子**：
- 第 3 层：`sqlite3` 标准库 + `pathlib.Path.as_uri()` 已支持 `?mode=ro`
- 第 3 层：`dataclasses.dataclass` 标准库

**步骤**：
- [ ] 写失败测试：`test_open_database_missing_file_raises`、`test_open_database_opens_actual_db`
- [ ] 确认失败
- [ ] 最小实现
- [ ] 确认通过
- [ ] 提交

---

### Task 2: load_session_titles + load_sidebar_project_names

**文件**
- 修改：`cskit/threads.py`
- 测试：`tests/test_threads.py`

**接口**
- 产出：`load_session_titles(path) -> dict[str, str]`、`load_sidebar_project_names(path) -> dict[str, str]`

**爬梯子**：
- 第 3 层：`json.loads` 标准库
- 第 6 层：`load_session_titles` 核心逻辑是 `latest[thread_id] = max(latest.get(thread_id), candidate, key=lambda x: x[:2])` —— 一行替代 4 行 if 链

**步骤**：
- [ ] 写失败测试：`test_load_session_titles_returns_latest_name`、`test_load_sidebar_project_names_maps_thread_to_project`
- [ ] 确认失败
- [ ] 最小实现
- [ ] 确认通过
- [ ] 提交

---

### Task 3: list_threads 查询函数

**文件**
- 修改：`cskit/threads.py`
- 测试：`tests/test_threads.py`

**接口**
- 消费：`open_database`、`ThreadRecord`、`CskitDataError`
- 产出：`list_threads(db_path, *, session_titles=None, project_names=None, sidebar_only=False, max_per_project=None, required_columns=None) -> list[ThreadRecord]`

**关键决策**：
- `required_columns` 默认 = 并集（10 列），缺省行为与 clonecode 一致
- `required_columns` 传入较小集合 → 校验更宽松，与 exportcode 一致
- 返回 `ThreadRecord` 统一类型，`display_name` 和 `full_name` 的 fallback 链与 clonecode 一致
- `preview` 列可选（if exists），不纳入 required_columns

**爬梯子**：
- 第 3 层：`sqlite3.PRAGMA table_info` 标准库
- 第 6 层：`display_name` 的 fallback 链是 `ui_titles.get(thread_id) or db_name or db_title or db_preview or "未命名对话"` —— 纯表达式，不拆 if 链

**步骤**：
- [ ] 写失败测试：`test_list_threads_requires_columns`、`test_list_threads_returns_thread_records`、`test_list_threads_sidebar_only_filters`
- [ ] 确认失败
- [ ] 最小实现
- [ ] 确认通过
- [ ] 提交

---

### Task 4: 列表渲染与选择函数

**文件**
- 修改：`cskit/threads.py`
- 测试：`tests/test_threads.py`

**接口**
- 消费：`ThreadRecord`、`CskitDataError`
- 产出：`format_timestamp(ms: int) -> str`、`selection_label(thread, duplicate_count) -> str`、`print_thread_list(threads)`、`choose_thread(threads, prompt_label="导出") -> ThreadRecord`

**参数化**：`choose_thread` 的 prompt 文案由调用方传入，消除两份硬编码副本。

**爬梯子**：
- 第 3 层：`datetime.fromtimestamp` 标准库
- 第 6 层：`selection_label` 核心逻辑是一行 f-string

**步骤**：
- [ ] 写失败测试：`test_format_timestamp_returns_expected`、`test_selection_label_truncates_long_titles`、`test_choose_thread_selects_by_index`
- [ ] 确认失败
- [ ] 最小实现
- [ ] 确认通过
- [ ] 提交
