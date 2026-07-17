// lifecycle/watchdog.go — 进程看门狗
//
// 文档对齐：原生 Harness 进程生命周期管理
// 功能：启动 Python 核心、崩溃检测、自动重启（限次）、优雅关闭

package lifecycle

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sync"
	"time"
)

// ── 常量 ──

const (
	DefaultMaxRestarts     = 3
	DefaultRestartDelay    = 2 * time.Second
	DefaultShutdownTimeout = 5 * time.Second
	HeartbeatInterval      = 5 * time.Second
)

// ── 进程状态 ──

type ProcessState int

const (
	StateStopped ProcessState = iota
	StateStarting
	StateRunning
	StateRestarting
	StateStopping
	StateFailed
)

func (s ProcessState) String() string {
	switch s {
	case StateStopped:
		return "stopped"
	case StateStarting:
		return "starting"
	case StateRunning:
		return "running"
	case StateRestarting:
		return "restarting"
	case StateStopping:
		return "stopping"
	case StateFailed:
		return "failed"
	default:
		return "unknown"
	}
}

// ── 事件回调 ──

type EventHandler interface {
	OnStdout(line string)
	OnStderr(line string)
	OnStateChange(old, new ProcessState)
	OnCrash(err error, restartCount int)
	OnHeartbeatTimeout()
}

// ── 看门狗 ──

type Watchdog struct {
	mu sync.RWMutex

	pythonPath string
	corePath   string
	args       []string

	cmd          *exec.Cmd
	stdin        io.WriteCloser
	stdoutReader *bufio.Scanner
	stderrReader *bufio.Scanner
	state        ProcessState
	restartCount int
	maxRestarts  int
	restartDelay time.Duration
	shutdownTO   time.Duration

	handler     EventHandler
	quit        chan struct{}
	done        chan struct{}
	pid         int
	lastHeartbe time.Time
}

type WatchdogOption func(*Watchdog)

func WithMaxRestarts(n int) WatchdogOption {
	return func(w *Watchdog) { w.maxRestarts = n }
}

func WithRestartDelay(d time.Duration) WatchdogOption {
	return func(w *Watchdog) { w.restartDelay = d }
}

func WithShutdownTimeout(d time.Duration) WatchdogOption {
	return func(w *Watchdog) { w.shutdownTO = d }
}

func WithEventHandler(h EventHandler) WatchdogOption {
	return func(w *Watchdog) { w.handler = h }
}

func NewWatchdog(pythonPath, corePath string, args []string, opts ...WatchdogOption) *Watchdog {
	w := &Watchdog{
		pythonPath:   pythonPath,
		corePath:     corePath,
		args:         args,
		maxRestarts:  DefaultMaxRestarts,
		restartDelay: DefaultRestartDelay,
		shutdownTO:   DefaultShutdownTimeout,
		state:        StateStopped,
		quit:         make(chan struct{}),
		done:         make(chan struct{}),
	}
	for _, opt := range opts {
		opt(w)
	}
	return w
}

// ── 启动 ──

func (w *Watchdog) Start() error {
	w.mu.Lock()
	if w.state != StateStopped {
		w.mu.Unlock()
		return fmt.Errorf("看门狗已在运行: %s", w.state)
	}
	w.state = StateStarting
	w.restartCount = 0
	w.mu.Unlock()

	go w.runLoop()
	return nil
}

func (w *Watchdog) runLoop() {
	defer close(w.done)

	for {
		select {
		case <-w.quit:
			w.shutdown()
			return
		default:
		}

		err := w.startProcess()
		if err != nil {
			w.setState(StateFailed)
			if w.handler != nil {
				w.handler.OnCrash(err, w.restartCount)
			}
			return
		}

		w.setState(StateRunning)
		err = w.waitProcess()

		select {
		case <-w.quit:
			w.shutdown()
			return
		default:
		}

		if err != nil {
			w.restartCount++
			if w.handler != nil {
				w.handler.OnCrash(err, w.restartCount)
			}

			if w.restartCount >= w.maxRestarts {
				fmt.Fprintf(os.Stderr, "[看门狗] 达到最大重启次数 %d，停止\n", w.maxRestarts)
				w.setState(StateFailed)
				return
			}

			w.setState(StateRestarting)
			fmt.Fprintf(os.Stderr, "[看门狗] 进程崩溃 (restart %d/%d)，%v 后重启...\n",
				w.restartCount, w.maxRestarts, w.restartDelay)

			select {
			case <-time.After(w.restartDelay):
			case <-w.quit:
				return
			}
		}
	}
}

func (w *Watchdog) startProcess() error {
	cmdArgs := []string{w.corePath, "--harness-mode"}
	cmdArgs = append(cmdArgs, w.args...)

	cmd := exec.Command(w.pythonPath, cmdArgs...)

	stdin, err := cmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("创建 stdin 管道失败: %w", err)
	}

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("创建 stdout 管道失败: %w", err)
	}

	stderr, err := cmd.StderrPipe()
	if err != nil {
		return fmt.Errorf("创建 stderr 管道失败: %w", err)
	}

	cmd.Env = append(os.Environ(),
		"CLAUDEZ_MODE=harness",
		fmt.Sprintf("CLAUDEZ_HARNESS_PID=%d", os.Getpid()),
	)

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("启动 Python 核心失败: %w", err)
	}

	w.mu.Lock()
	w.cmd = cmd
	w.stdin = stdin
	w.stdoutReader = bufio.NewScanner(stdout)
	w.stderrReader = bufio.NewScanner(stderr)
	w.pid = cmd.Process.Pid
	w.lastHeartbeat = time.Now()
	w.mu.Unlock()

	return nil
}

func (w *Watchdog) waitProcess() error {
	// stdout 读取
	stdoutDone := make(chan error, 1)
	go func() {
		for w.stdoutReader.Scan() {
			line := w.stdoutReader.Text()
			if w.handler != nil {
				w.handler.OnStdout(line)
			}

			// 心跳更新：收到任何 stdout 行都算
			w.mu.Lock()
			w.lastHeartbeat = time.Now()
			w.mu.Unlock()
		}
		stdoutDone <- w.stdoutReader.Err()
	}()

	// stderr 读取
	stderrDone := make(chan error, 1)
	go func() {
		for w.stderrReader.Scan() {
			line := w.stderrReader.Text()
			if w.handler != nil {
				w.handler.OnStderr(line)
			}
		}
		stderrDone <- w.stderrReader.Err()
	}()

	// 心跳监控
	heartbeatDone := make(chan struct{}, 1)
	go func() {
		ticker := time.NewTicker(HeartbeatInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				w.mu.RLock()
				elapsed := time.Since(w.lastHeartbeat)
				w.mu.RUnlock()
				if elapsed > w.shutdownTO*2 {
					if w.handler != nil {
						w.handler.OnHeartbeatTimeout()
					}
					w.cmd.Process.Kill()
					return
				}
			case <-heartbeatDone:
				return
			}
		}
	}()

	// 等待进程退出
	err := w.cmd.Wait()
	close(heartbeatDone)
	<-stdoutDone
	<-stderrDone

	return err
}

// ── 停止 ──

func (w *Watchdog) Stop() {
	close(w.quit)
	<-w.done
}

func (w *Watchdog) shutdown() {
	w.setState(StateStopping)

	w.mu.RLock()
	cmd := w.cmd
	stdin := w.stdin
	w.mu.RUnlock()

	if cmd != nil && cmd.Process != nil {
		// 先发 SIGTERM
		cmd.Process.Signal(os.Interrupt)

		// 等待或强制杀死
		done := make(chan struct{}, 1)
		go func() {
			cmd.Wait()
			done <- struct{}{}
		}()

		select {
		case <-done:
		case <-time.After(w.shutdownTO):
			cmd.Process.Kill()
		}
	}

	if stdin != nil {
		stdin.Close()
	}

	w.setState(StateStopped)
}

// ── 状态 ──

func (w *Watchdog) State() ProcessState {
	w.mu.RLock()
	defer w.mu.RUnlock()
	return w.state
}

func (w *Watchdog) PID() int {
	w.mu.RLock()
	defer w.mu.RUnlock()
	return w.pid
}

func (w *Watchdog) RestartCount() int {
	w.mu.RLock()
	defer w.mu.RUnlock()
	return w.restartCount
}

func (w *Watchdog) Send(data []byte) (int, error) {
	w.mu.RLock()
	stdin := w.stdin
	w.mu.RUnlock()
	if stdin == nil {
		return 0, fmt.Errorf("stdin 未就绪")
	}
	return stdin.Write(data)
}

func (w *Watchdog) Stdin() io.WriteCloser {
	w.mu.RLock()
	defer w.mu.RUnlock()
	return w.stdin
}

func (w *Watchdog) setState(s ProcessState) {
	w.mu.Lock()
	old := w.state
	w.state = s
	w.mu.Unlock()
	if w.handler != nil {
		w.handler.OnStateChange(old, s)
	}
}

// ── JSON-RPC 辅助 ──

type RPCRequest struct {
	ID     int64           `json:"id"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params,omitempty"`
}

type RPCResponse struct {
	ID     int64           `json:"id,omitempty"`
	Result json.RawMessage `json:"result,omitempty"`
	Error  *string         `json:"error,omitempty"`
}

func (w *Watchdog) SendRPC(method string, params interface{}) error {
	data, err := json.Marshal(params)
	if err != nil {
		return err
	}
	req := RPCRequest{
		ID:     time.Now().UnixNano(),
		Method: method,
		Params: data,
	}
	raw, err := json.Marshal(req)
	if err != nil {
		return err
	}
	_, err = w.Send(append(raw, '\n'))
	return err
}
