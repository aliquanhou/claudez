# Changelog

## [forgex-v1.0.0] - 2026-07-22

### 四层架构完整发布

ForgeX v1.0.0 合并了 v0.3.4 → v0.5.2 全部里程碑，标志着四层 AI Agent 架构正式定稿。

| 层级 | 版本 | 模块 |
|------|------|------|
| 🧠 **认知层** | v0.3.4 | 意图识别 / 任务管理 / 方案验证 / 执行验证 / 上下文编译 / 工作区扫描 |
| ⚡ **执行层** | v0.4.0 | PlanExecutor / ToolOrchestrator / PathValidator / FeedbackLoop |
| 🔧 **工具层** | v0.5.0+ | 14 内置工具 + web_fetch + web_search + 主机工具链探测 |
| 🖥️ **Web 驾驶舱** | v0.4.0+ | 3 栏布局 / 文件树 / 状态面板 / LLM 配置 / 停止执行 |

### 认知层 (v0.3.4)
- TaskManager 多任务管理，6 个数据类
- WorkspaceScanner 惰性扫描，项目类型推断，文件树构建（深度 4）
- IntentResonator 7 条规则引擎，从行为快照蒸馏意图
- PlanVerifier 7 条验证规则，多候选评估
- ExecutionVerifier 6 阶段验证，偏差分析
- ContextCompiler 编译为结构化 Prompt，桥接现有系统

### 执行层 (v0.4.0)
- PlanExecutor：方案→原子执行步骤，1:N 映射，文件冲突检测
- ToolOrchestrator：并行执行无依赖步骤，超时控制 + 自动重试
- PathValidator：白名单 + 黑名单 + 敏感文件类型拦截
- FeedbackLoop：验证→回写→自动阶段推进（PASS/DONE, PARTIAL/ANALYSIS, FAIL/PLANNING）

### 工具层 (v0.5.0+)
- **web_fetch**：requests + BeautifulSoup 网页纯文本提取，自动去噪，10000 字符截断
- **web_search**：DuckDuckGo 搜索，返回标题+URL+摘要
- **EnvProbe**：20 种开发工具一键探测，60s 缓存，prompt 自动注入
- 14 个内置工具覆盖文件操作 / 命令执行 / 网络 / 系统监控 / 子 Agent

### Web 驾驶舱
- 3 栏布局（左：文件树+工具+配置 / 中：对话流 / 右：状态+日志）
- 交互式文件树：展开/折叠、点击 `@file:path` 引用
- LLM 配置面板：模型/温度/MaxTokens 实时生效
- 停止执行：前端→`POST /api/stop`→`Provider.cancel()` 中断流式连接
- 阶段轨可视化：6 阶段彩色进度条
- SSE 连接状态监控 + 自动重连
- 全局 JS 错误捕获（`window.onerror` + `unhandledrejection`）

### 修复
- `_read_agent_status` 插入 `class Agent` 中间导致 12 个方法成为死代码
- SSE error 事件 `JSON.parse(e.data)` 崩溃（断开时 data 为空）
- 工具成功状态检测：`[完成]` 误判为 `[错误]`
- 文件树/工具列表加载卡"扫描中"（新增 3 次重试）

## [forgex-v0.5.2] - 2026-07-22

### Added
- **LLM 配置实时生效**
  - `POST /api/config/llm`：动态修改模型/温度/Max Tokens/Provider
  - `GET /api/config`：获取当前配置快照
  - 前端交互面板（模型下拉 / 温度滑块 / Max Tokens 输入）
  - 配置变更后无需重启，下次 LLM 调用即用新参数
- **停止执行**
  - `POST /api/stop`：中断正在执行的 Agent
  - `Provider.cancel()`：关闭流式 HTTP 连接，终止 LLM 请求
  - `Agent.stop()` → `provider.cancel()` 级联中断
  - 前端停止按钮真实调用后端，代替仅前端状态重置
- **全局错误捕获**
  - `window.onerror` + `unhandledrejection` 捕获 JS 异常
  - 错误信息写入右侧日志面板

### Fixed
- SSE `error` 事件 `JSON.parse(e.data)` 崩溃（断开时 data 为空）
- 文件树/工具列表加载卡"扫描中"（新增 3 次重试，间隔递增）
- `DOMContentLoaded` 时序问题 → IIFE 立即执行
- `pollStatic()` 重复 `try` 块导致工具加载逻辑失效

## [forgex-v0.4.1] - 2026-07-22

### Added
- **动态端口**：`_find_available_port()` 从 8080 开始扫描可用端口
- **自动打开浏览器**：`webbrowser.open(url)`
- 版本统一更新至 0.4.1

## [forgex-v0.4.0] - 2026-07-22

### Added
- **执行层第一批**：PlanExecutor + ToolOrchestrator
  - `plan_executor`：将 PlanVerifier 输出的方案拆解为原子执行步骤
    - 1:N 映射（一个 PlanStep → 多个 ExecutionStep）
    - 文件冲突检测（同文件修改自动串行化）
  - `tool_orchestrator`：执行步骤编排
    - 并行执行无依赖步骤（ThreadPoolExecutor）
    - 复用已有 `execute_tool()` 函数
    - 超时控制（30s）+ 自动重试（1次）
    - 依赖跳过（前一步失败，子步跳过）

### Tested
- 8/8 验收场景全部通过
- 端到端流水线验证通过

### Added (第二批)
- `path_validator`：文件路径安全校验
  - 白名单校验（必须在工作区内）
  - 黑名单目录拦截（.git, node_modules, 系统路径等）
  - 敏感文件类型拦截（.key, .pem, .crt）
  - `filter_safe()` / `validate_all()` 批量接口
- `feedback_loop`：执行结果反馈闭环
  - ExecutionVerifier 执行验证 → 结果回写 TaskContext
  - PASS → phase=DONE, PARTIAL → ANALYSIS, FAIL → PLANNING
  - 自动阶段回退与推进
- `core.py` 集成：4 个执行模块接入 Agent 主循环
  - 修复 `_log` 定义在 cognition import 之前的顺序问题
- 所有验收测试通过（PathValidator: 5/5, FeedbackLoop: 1/1, 全链路: 1/1, Agent Init: 1/1）

## [forgex-v0.3.4] - 2026-07-22

### Added
- **cognition/ 完整认知层**：6 个模块全部交付
  - `task_context`：TaskManager 多任务管理，6 个数据类
  - `workspace_scanner`：惰性扫描，项目类型推断，文件树构建
  - `intent_resonator`：7 条规则引擎，从行为快照蒸馏意图
  - `plan_verifier`：7 条验证规则，多候选评估比较
  - `execution_verifier`：6 阶段验证，偏差分析
  - `context_compiler`：编译为结构化 Prompt，桥接现有系统

### Fixed
- WorkspaceScanner 惰性初始化（避免启动 IO 阻塞）
- IntentResonator 通过滑动平均消除单点误报
- 统一 `__init__.py` 导出，添加命名冲突注释说明

### Validated
- 端到端仿真全链路通过（用户输入 → 意图识别 → 上下文编译 → 方案验证 → 执行验证）
- 7/7 task_context 断言通过
- 5/5 intent_resonator 场景通过
- 7/7 plan_verifier 场景通过
- 5/5 execution_verifier 场景通过
- 9/9 context_compiler 场景通过

### Notes
- 这是 ForgeX 认知层的第一个完整发布版本
- 铁三角架构（TaskContext + IntentResonator + ContextCompiler）已就位
- 与现有 prompt.py 采用桥接策略，零破坏性接入

## [forgex-v0.5.1] - 2026-07-22

### Added
- **web_fetch 工具**：抓取网页纯文本内容
  - 使用 requests + BeautifulSoup，去除脚本/样式/导航噪音
  - 自动截断 10000 字符，防止 token 溢出
  - 友好错误信息（404/403/超时/连接失败）
  - 兼容 Agent 工具系统（@tool 装饰器注册）

