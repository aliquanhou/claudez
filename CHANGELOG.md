# Changelog

## [forgex-v0.5.0] - 2026-07-22

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

