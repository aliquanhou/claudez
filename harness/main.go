// ClaudeZ Harness — 原生壳层
//
// 文档对齐：Claude Code Harness 核心工作原理
// 架构：Go Harness ↔ stdin/stdout JSON-RPC ↔ Python Core
//
// 职责：
//   1. 进程生命周期管理（看门狗 + 自动重启）
//   2. 终端 TUI 渲染（bubbletea 分屏）
//   3. IPC 通信（stdin/stdout JSON-RPC + 流式事件）
//   4. 自动更新检查
//   5. 平台分发入口

package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/mattn/go-isatty"

	"github.com/claudez/harness/lifecycle"
	"github.com/claudez/harness/tui"
	"github.com/claudez/harness/updater"
)

// ── 版本信息 ──

const (
	Version    = "2.1.0"
	Codename   = "ClaudeZ"
	BuildDate  = "2026-07-17"
)

// ── 全局状态 ──

var (
	logFile    *os.File
	logger     *logWriter
	uiModel    *tui.Model
	watchdog   *lifecycle.Watchdog
	updChecker *updater.Checker
	program    *tea.Program
)

// ── 日志 ──

type logWriter struct {
	mu     sync.Mutex
	file   *os.File
	prefix string
}

func newLogWriter(path string) (*logWriter, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return nil, err
	}
	return &logWriter{file: f, prefix: time.Now().Format("2006-01-02")}, nil
}

func (l *logWriter) write(level, msg string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	t := time.Now().Format("15:04:05.000")
	fmt.Fprintf(l.file, "[%s] [%s] %s\n", t, level, msg)
}

func (l *logWriter) Info(msg string)  { l.write("INFO", msg) }
func (l *logWriter) Warn(msg string)  { l.write("WARN", msg) }
func (l *logWriter) Error(msg string) { l.write("ERROR", msg) }

func (l *logWriter) Close() { l.file.Close() }

// ── 入口 ──

func main() {
	// ── 解析参数 ──
	args := os.Args[1:]

	if len(args) > 0 {
		switch args[0] {
		case "--version", "-v":
			fmt.Printf("%s Harness v%s (%s) %s/%s\n",
				Codename, Version, BuildDate, runtime.GOOS, runtime.GOARCH)
			return
		case "--help", "-h":
			printHelp()
			return
		case "--standalone":
			runStandalone(args[1:])
			return
		}
	}

	// ── 初始化日志 ──
	logDir := filepath.Join(homeDir(), ".claudez", "logs")
	os.MkdirAll(logDir, 0755)
	logPath := filepath.Join(logDir, fmt.Sprintf("harness-%s.log",
		time.Now().Format("20060102")))
	lw, err := newLogWriter(logPath)
	if err == nil {
		logger = lw
		defer logger.Close()
		logInfo("Harness v%s starting", Version)
	}
	logInfo("Platform: %s/%s", runtime.GOOS, runtime.GOARCH)
	logInfo("Args: %v", args)

	// ── 更新检查（后台） ──
	go checkUpdate()

	// ── 初始化 TUI ──
	uiModel = tui.NewModel()
	uiModel.SetModelName(getDefaultModel())

	// ── 绑定信号 ──
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM, syscall.SIGHUP)

	// ── 是否交互式终端 ──
	if isatty.IsTerminal(os.Stdout.Fd()) {
		// TUI 模式
		program = tea.NewProgram(uiModel, tea.WithAltScreen())
		go func() {
			<-sigCh
			logInfo("收到终止信号，正在关闭...")
			shutdown()
			program.Quit()
		}()
		go runCore(args)
		if _, err := program.Run(); err != nil {
			fmt.Fprintf(os.Stderr, "TUI 错误: %v\n", err)
			os.Exit(1)
		}
	} else {
		// 非 TTY 模式（管道输出）
		go func() {
			<-sigCh
			shutdown()
			os.Exit(0)
		}()
		runCore(args)
	}
}

// ── 运行 Python 核心 ──

func runCore(args []string) {
	logInfo("启动 Python 核心...")

	// 定位核心路径
	corePath := findCorePath()
	logInfo("Core path: %s", corePath)

	// 构建命令行参数（过滤掉已处理的标志）
	coreArgs := []string{}
	for _, a := range args {
		if a == "--standalone" || a == "-v" || a == "--version" || a == "-h" || a == "--help" {
			continue
		}
		coreArgs = append(coreArgs, a)
	}

	// 创建看门狗
	watchdog = lifecycle.NewWatchdog(
		"python",
		corePath,
		coreArgs,
		lifecycle.WithMaxRestarts(3),
		lifecycle.WithRestartDelay(2*time.Second),
		lifecycle.WithShutdownTimeout(5*time.Second),
		lifecycle.WithEventHandler(&watchdogHandler{}),
	)

	// 启动
	if err := watchdog.Start(); err != nil {
		errMsg := fmt.Sprintf("启动 Python 核心失败: %v", err)
		logError(errMsg)
		if uiModel != nil {
			uiModel.PushError(errMsg)
		} else {
			fmt.Fprintf(os.Stderr, "[Harness] %s\n", errMsg)
		}
		os.Exit(1)
	}

	// 等待看门狗退出
	// 看门狗运行在后台，main 不等待——TUI 事件循环会保持进程存活
}

// ── 看门狗事件处理器 ──

type watchdogHandler struct{}

func (h *watchdogHandler) OnStdout(line string) {
	if uiModel != nil {
		handleIPCLine(line)
	}
}

func (h *watchdogHandler) OnStderr(line string) {
	logInfo("[py-stderr] %s", line)
	if uiModel != nil {
		// stderr 通常是日志，不渲染到 TUI 主界面
		// 但错误级别需要显示
		if strings.Contains(line, "ERROR") || strings.Contains(line, "Traceback") {
			uiModel.PushError(line)
		}
	}
}

func (h *watchdogHandler) OnStateChange(old, new lifecycle.ProcessState) {
	logInfo("Python 核心状态: %s → %s", old, new)
	if uiModel != nil {
		uiModel.SetStatus(fmt.Sprintf("core:%s", new))
	}
}

func (h *watchdogHandler) OnCrash(err error, restartCount int) {
	errMsg := fmt.Sprintf("Python 核心崩溃 (restart %d/3): %v", restartCount, err)
	logError(errMsg)
	if uiModel != nil {
		uiModel.PushError(errMsg)
	}
}

func (h *watchdogHandler) OnHeartbeatTimeout() {
	errMsg := "Python 核心心跳超时，将强制重启"
	logError(errMsg)
	if uiModel != nil {
		uiModel.PushError(errMsg)
	}
}

// ── IPC 消息处理 ──

type IPCMessage struct {
	ID     *int64          `json:"id,omitempty"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params,omitempty"`
	Result json.RawMessage `json:"result,omitempty"`
	Error  *string         `json:"error,omitempty"`
}

type IPCResponse struct {
	ID     int64           `json:"id"`
	Result json.RawMessage `json:"result,omitempty"`
	Error  *string         `json:"error,omitempty"`
}

func handleIPCLine(line string) {
	line = strings.TrimSpace(line)
	if line == "" {
		return
	}

	var msg IPCMessage
	if err := json.Unmarshal([]byte(line), &msg); err != nil {
		return
	}

	switch msg.Method {
	case "event":
		handleEvent(msg.Params)
	case "ping":
		handlePing(msg.ID)
	case "stream":
		handleStream(msg.Params)
	default:
		// 可能是响应（带 id 但没有 method）
		if msg.ID != nil && msg.Result != nil {
			// 响应——忽略，由 Watchdog 透传
		}
	}
}

func handleEvent(raw json.RawMessage) {
	var evt struct {
		Type string          `json:"type"`
		Data json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(raw, &evt); err != nil {
		return
	}

	switch evt.Type {
	case "text":
		var text string
		json.Unmarshal(evt.Data, &text)
		uiModel.PushText(text)

	case "tool_start":
		var tool struct {
			Name string `json:"name"`
			Args string `json:"args"`
		}
		json.Unmarshal(evt.Data, &tool)
		uiModel.PushToolStart(tool.Name, tool.Args)

	case "tool_result":
		var result struct {
			Success bool   `json:"success"`
			Data    string `json:"data"`
		}
		json.Unmarshal(evt.Data, &result)
		uiModel.PushToolResult(result.Data, result.Success)

	case "error":
		var errMsg string
		json.Unmarshal(evt.Data, &errMsg)
		uiModel.PushError(errMsg)

	case "thinking":
		var thought string
		json.Unmarshal(evt.Data, &thought)
		uiModel.PushThinking(thought)

	case "complete":
		uiModel.PushComplete()

	case "status":
		var status string
		json.Unmarshal(evt.Data, &status)
		uiModel.SetStatus(status)
	}
}

func handleStream(raw json.RawMessage) {
	var chunk string
	if err := json.Unmarshal(raw, &chunk); err != nil {
		return
	}
	// 流式字符推送（用于打字机效果）
	if uiModel != nil {
		// 批量推送，每块作为一个事件
		uiModel.PushStream(chunk)
	}
}

func handlePing(id *int64) {
	if id == nil || watchdog == nil {
		return
	}
	resp, _ := json.Marshal(IPCResponse{
		ID:     *id,
		Result: json.RawMessage(`"pong"`),
	})
	watchdog.Send(append(resp, '\n'))
}

// ── 关闭 ──

func shutdown() {
	logInfo("开始关闭...")
	if watchdog != nil {
		watchdog.Stop()
	}
	logInfo("关闭完成")
}

// ── Standalone 模式 ──

func runStandalone(args []string) {
	fmt.Fprintf(os.Stderr, "[Harness] 纯 Python 模式\n")
	corePath := findCorePath()
	cmdArgs := append([]string{corePath}, args...)

	cmd := execCommand("python", cmdArgs...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Run()
}

// ── 辅助函数 ──

func findCorePath() string {
	// 环境变量优先
	if v := os.Getenv("CLAUDEZ_CORE"); v != "" {
		if _, err := os.Stat(v); err == nil {
			return v
		}
	}

	// 相对 Harness 二进制的位置
	exePath, err := os.Executable()
	if err == nil {
		exeDir := filepath.Dir(exePath)
		candidates := []string{
			filepath.Join(exeDir, "..", "..", "..", "main.py"),
			filepath.Join(exeDir, "..", "..", "main.py"),
			filepath.Join(exeDir, "..", "main.py"),
		}
		for _, p := range candidates {
			abs, _ := filepath.Abs(p)
			if _, err := os.Stat(abs); err == nil {
				return abs
			}
		}
	}

	// fallback
	return "main.py"
}

func getDefaultModel() string {
	if v := os.Getenv("CLAUDEZ_MODEL"); v != "" {
		return v
	}
	return "claude-sonnet-4-20250514"
}

func homeDir() string {
	if v := os.Getenv("HOME"); v != "" {
		return v
	}
	if v := os.Getenv("USERPROFILE"); v != "" {
		return v
	}
	return "."
}

func printHelp() {
	fmt.Printf(`%s Harness v%s — 原生 AI 智能体壳层

用法:
  %s [选项] [消息...]

选项:
  -h, --help       显示帮助
  -v, --version    显示版本
  --standalone     纯 Python 模式（不使用原生壳层）
  -m, --model      指定模型（如 claude-sonnet-4-20250514）
  -p, --provider   指定提供商（anthropic | openai | deepseek）
  -w, --workflow   指定工作流模式
  --interactive    交互模式

示例:
  %s "帮我写一个 Python 函数"
  %s --interactive
  %s -w coding "写一个 Web 服务器"

环境变量:
  CLAUDEZ_CORE      Python 核心路径
  CLAUDEZ_MODEL     默认模型
  CLAUDEZ_LOG_LEVEL 日志级别
`,
		Codename, Version,
		os.Args[0],
		os.Args[0], os.Args[0], os.Args[0],
	)
}

func checkUpdate() {
	updChecker = updater.NewChecker()
	result := updChecker.Check()
	if result.Status == updater.StatusAvailable {
		msg := fmt.Sprintf("发现新版本: %s → %s (运行 --version 查看详情)", result.Current, result.Latest)
		if uiModel != nil {
			uiModel.PushText(fmt.Sprintf("\n  📦 %s\n", msg))
		}
		logInfo("更新可用: %s → %s", result.Current, result.Latest)
	} else if result.Status == updater.StatusCheckFailed {
		logInfo("更新检查失败: %v", result.Error)
	}
}

// ── exec 包装 ──

func execCommand(name string, arg ...string) *exec.Cmd {
	return exec.Command(name, arg...)
}

// ── 日志辅助 ──

func logInfo(format string, args ...interface{}) {
	if logger != nil {
		logger.Info(fmt.Sprintf(format, args...))
	}
}

func logError(format string, args ...interface{}) {
	if logger != nil {
		logger.Error(fmt.Sprintf(format, args...))
	}
}
