# ClaudeZ 2.0 — AGI Engineering Agent

> **超越 Devin · 超越 Hermes** · 行业首个 0-LLM 确定性认知铁三角 + 多 Agent 流水线 + 自进化闭环 + 生产级安全底座

---

## 📋 项目概览

| 维度 | 详情 |
|------|------|
| **版本** | v2.0-release-full |
| **架构** | 四层架构：认知核心层 → 多Agent流水线层 → 自进化闭环层 → 底层安全底座 |
| **核心差异** | 独有 **0-LLM 确定性认知铁三角** — Devin/Hermes 均无该底层校验架构 |
| **语言** | Python 3.10+ |
| **UI** | 暗色 AGI Cockpit — 粒子背景 · 环境辉光 · 毛玻璃 · 实时监控面板 |
| **测试** | 41 单元测试 + 49 项人工验收测试 |
| **代码** | ~4000 行新增，零破坏 1.x 基线 |

---

## 🏗️ 架构全景

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 4: SDLC + 沙箱 + 测试 (Phase 4)                      │
│  Code Review · 三层沙箱 · pytest 41 · 统一 WebUI            │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: 自进化闭环 (Phase 3)                               │
│  Nudge Engine · Skill Manager · 4 阶段压缩 · 后台审查        │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: 多 Agent 流水线 (Phase 2)                          │
│  Planner→Executor→Verifier · 自动修复 · 角色隔离             │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: 认知核心 + 执行底座 (Phase 1)                      │
│  IntentResonator · PlanVerifier · ExecutionVerifier          │
│  并行执行 · Prompt Cache · Token 窗口 · EventBus · 多租户    │
└─────────────────────────────────────────────────────────────┘
```

---

## 🥇 竞品代差矩阵

| 能力维度 | Devin | Hermes | **ClaudeZ 2.0** |
|----------|-------|--------|----------------|
| **0-LLM 确定性认知铁三角** | ❌ | ❌ | ✅ **独家** |
| 多 Agent 流水线 + 自动修复 | ✅ | ❌ | ✅ |
| 自进化闭环 (Nudge+Skill+压缩+审查) | ❌ | ✅ | ✅ |
| 文件读写锁 + 并行执行 | ❌ | ❌ | ✅ **独家** |
| EventBus + TraceID 全链路 | ❌ | ❌ | ✅ **独家** |
| Token 窗口 + 消息保护 | ❌ | ❌ | ✅ **独家** |
| 三层沙箱 + DangerScore | ❌ | ✅ | ✅ |
| Code Review 工作流 | ✅ | ❌ | ✅ |
| 生产级 WebUI 驾驶舱 | ❌ | ❌ | ✅ **独家** |

---

## 🧠 核心模块详解

### Phase 1 — 认知核心与执行底座

#### IntentResonator（意图共鸣器）
- **7 条规则引擎**，0 LLM 依赖
- 从行为信号（光标速度、删除率、撤销次数、文件切换）推断用户意图
- 信号：EXPLORING / DEBUGGING / REFACTORING / IMPLEMENTING / REVIEWING / STUCK / CONFIDENT
- 滑动窗口（默认 20）+ TTL-LRU 过期淘汰 + SQLite 持久化

#### PlanVerifier（方案验证器）
- **6 维度确定性验证**：完整性、文件冲突、存在性、复杂度、范围、工作量
- 输出 PASS / WARN / FAIL + 0-100 评分
- 可对多个方案排序比较

#### ExecutionVerifier（执行验证器）
- **6 阶段验证**：文件变更检测 → 步骤匹配 → 目标文件覆盖 → 错误检测 → 偏差分析 → 综合评分
- PASS / PARTIAL / FAIL 三级判定

#### ToolOrchestrator（工具编排器）
- `from_llm_tool_calls()` 直接从 LLM 输出生成执行步骤
- 只读工具 ThreadPoolExecutor 并行（max_workers=8）
- 文件读写锁（ResourceLockManager）保障并发安全
- 单任务异常熔断不阻塞整批

#### 三层 Prompt Cache
- Hermes 风格三层分离：stable（角色/工具 → 缓存）/ context（任务/工作区 → 每轮重算）/ volatile（自适应/示例 → 不缓存）
- 缓存命中/未命中统计埋点

#### Token 感知上下文窗口
- 中英混合 token 估算（ASCII 4字/token，中文 1.5字/token）
- 核心消息白名单保护（`_PROTECTED_ROLES`）
- 从后往前保留，优先丢弃旧的非保护消息

#### EventBus + TraceID
- 基于 asyncio.Queue 的发布-订阅事件系统
- 全局 TraceID 全链路透传
- 队列满时自动丢弃最旧事件

---

### Phase 2 — 多 Agent 流水线

#### Agent 角色系统
- **PLANNER**：只读 + 搜索工具，禁止 write/edit/bash
- **EXECUTOR**：所有工具，禁止 web_search
- **VERIFIER**：只读 + bash，禁止写操作
- 通过提示词塑造实现，非独立类

#### Pipeline Orchestrator
- Planner → Executor → Verifier 三段串行编排
- 子 Agent 隔离会话，独立配置
- JSON 检查点：`save_checkpoint()` / `load_checkpoint()`
- 自动修复重试：Verdict FAIL → 带错误上下文回退到 Planner（最多 3 次）

---

### Phase 3 — 自进化闭环

#### Nudge Engine
- 0-LLM 确定性规则：重复错误检测、Token 过载、工具循环、长时间运行、无文件修改
- 每次只注入 Top-2 优先级最高的 Nudge

#### Skill Manager
- SQLite 持久化存储工具调用序列模板
- 自动创建触发器：5+ 工具调用 + 错误 ≤ 1 → 自动生成 Skill
- Hermes 风格渐进加载：系统提示中仅索引，按需加载完整内容

#### 四阶段上下文压缩
1. **Purge**：移除长工具结果
2. **Protect**：标记高价值消息
3. **Summarize**：LLM 摘要旧轮次（可选）
4. **Sanitize**：清理格式 + handoff prefix

#### 后台会话审查
- 每 N 轮（默认 10）触发一次确定性分析
- 检查：文件范围偏差、错误率、会话轮次、目标聚焦度

---

### Phase 4 — SDLC + 安全 + 测试

#### Code Review 工作流
- 支持 git diff 引用或单文件路径
- 0-LLM 确定性检查：硬编码密钥、TODO/FIXME、空 except、超长行、print debug

#### 三层沙箱 + DangerScore
- **disabled** / **temp_dir** / **docker** 三种模式
- 90+ 威胁模式：文件破坏、权限提升、数据泄露、资源耗尽
- 评分 0-100，≥80 CRITICAL 直接拦截

---

## 🚀 快速启动

```bash
# 启动 WebUI 驾驶舱
cd D:\claude\claudez
python -m agent.web.run

# 浏览器打开 http://localhost:8080
```

---

## 🧪 测试

```bash
# 全量 41 单元测试
python -m pytest tests/ -v

# 指定模块
python -m pytest tests/test_cognition/ -v
python -m pytest tests/test_sandbox/ -v
```

---

## 🌐 WebUI 驾驶舱

| 区域 | 内容 |
|------|------|
| **左侧导航** | 紧凑图标导航（hover 展开），8 模块入口 |
| **中央对话** | 粒子背景 · 毛玻璃气泡 · 用户右对齐/AI左对齐 |
| **右侧面板** | 5 组折叠面板：Status / Cognition / Load / Alerts / Trace |
| **配置台** | LLM 配置 · 缓存 · Token 窗口 · 沙箱 · 流水线 · 权限 |

---

## 📁 项目结构

```
D:\claude\claudez/
├── agent/
│   ├── core.py                    # Agent 核心循环（v2.0 重构）
│   ├── prompt.py                  # 动态提示词引擎 + 三层缓存
│   ├── session.py                 # 会话管理 + 多租户
│   ├── cognition/                 # 认知层
│   │   ├── intent_resonator.py    # 意图共鸣器（TTL-LRU + SQLite）
│   │   ├── plan_verifier.py       # 方案验证器（6 维度）
│   │   ├── execution_verifier.py  # 执行验证器（6 阶段）
│   │   └── context_compiler.py    # 上下文编译器
│   ├── execution/                 # 执行层
│   │   ├── plan_executor.py       # 方案拆解器
│   │   ├── tool_orchestrator.py   # 工具编排器（并行 + 读写锁）
│   │   └── path_validator.py      # 路径安全校验
│   ├── pipeline/                  # 多 Agent 流水线
│   │   ├── orchestrator.py        # PipelineOrchestrator
│   │   ├── types.py               # PipelineTask
│   │   └── checkpoint.py          # JSON 检查点
│   ├── roles/                     # 角色系统
│   ├── self_evol/                 # 自进化系统
│   │   ├── nudge.py               # Nudge Engine
│   │   ├── skills.py              # Skill Manager (SQLite)
│   │   ├── compressor.py          # 4 阶段上下文压缩
│   │   └── review.py              # 后台会话审查
│   ├── sandbox/                   # 沙箱系统
│   │   ├── danger_score.py        # DangerScore 威胁评分
│   │   └── temp_dir.py            # 临时目录沙箱
│   ├── workflows/                 # 工作流
│   │   └── code_review.py         # Code Review 工作流
│   ├── events/                    # 事件系统
│   │   ├── bus.py                 # EventBus
│   │   └── protocol.py            # ForgeXEvent + TraceID
│   ├── web/                       # WebUI 驾驶舱
│   │   ├── server.py              # FastAPI 服务器（31 路由）
│   │   └── static/index.html      # AGI Cockpit UI
│   └── tools/                     # 工具体系
├── tests/                         # 测试套件（7 文件，41 用例）
└── pyproject.toml
```

---

## 📊 关键指标

| 指标 | 数值 |
|------|------|
| 核心模块 | 21 |
| 测试用例 | 41 单元 + 49 人工 = 90 |
| API 路由 | 31 |
| 新增代码 | ~4000 行 |
| 架构层 | 4 层 |

---

## 🔗 链接

- **GitHub**: https://github.com/aliquanhou/claudez

---

*ClaudeZ 2.0 — 超越 Devin · 超越 Hermes · 行业首个全栈确定性 AGI 工程引擎*
