# Changelog

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
