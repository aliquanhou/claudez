// tui/render.go — ClaudeZ Terminal UI (bubbletea)
//
// 文档对齐：原生 Harness 的 TUI 渲染层
// 功能：分屏布局、语法高亮、进度条、动态状态栏

package tui

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// ── 主题色 ──

var (
	ColorPrimary   = lipgloss.Color("#7C3AED") // 紫色
	ColorSecondary = lipgloss.Color("#3B82F6") // 蓝色
	ColorSuccess   = lipgloss.Color("#10B981") // 绿色
	ColorWarning   = lipgloss.Color("#F59E0B") // 黄色
	ColorError     = lipgloss.Color("#EF4444") // 红色
	ColorMuted     = lipgloss.Color("#6B7280") // 灰色
	ColorBg        = lipgloss.Color("#1E1E2E") // 背景
	ColorSurface   = lipgloss.Color("#2D2D3F") // 表面色
	ColorText      = lipgloss.Color("#E0E0F0") // 文字
)

// ── 样式 ──

var (
	StyleApp = lipgloss.NewStyle().
		Background(ColorBg).
		Padding(0, 1)

	StyleTitle = lipgloss.NewStyle().
			Foreground(ColorPrimary).
			Bold(true).
			Padding(0, 1)

	StyleStatusBar = lipgloss.NewStyle().
			Background(ColorSurface).
			Foreground(ColorText).
			Padding(0, 1).
			Width(80)

	StyleMessage = lipgloss.NewStyle().
			Foreground(ColorText).
			Padding(0, 1)

	StyleToolCall = lipgloss.NewStyle().
			Foreground(ColorSecondary).
			Italic(true)

	StyleToolResult = lipgloss.NewStyle().
			Foreground(ColorSuccess)

	StyleError = lipgloss.NewStyle().
			Foreground(ColorError).
			Bold(true)

	StyleThinking = lipgloss.NewStyle().
			Foreground(ColorWarning).
			Italic(true)

	StyleSpinner = lipgloss.NewStyle().
			Foreground(ColorPrimary)

	StyleSeparator = lipgloss.NewStyle().
			Foreground(ColorMuted).
			Width(80).
			Border(lipgloss.NormalBorder(), false, false, true, false).
			BorderForeground(ColorMuted)
)

// ── 消息类型 ──

type EventType int

const (
	EventText EventType = iota
	EventToolStart
	EventToolResult
	EventError
	EventThinking
	EventComplete
	EventStatus
	EventProgress
	EventStream
)

type UIEvent struct {
	Type    EventType
	Content string
	Meta    map[string]string
}

// ── TUI 模型 ──

type Model struct {
	ready       bool
	viewport    viewport.Model
	spinner     spinner.Model
	spinnerOn   bool
	content     strings.Builder
	statusText  string
	modeText    string
	modelText   string
	toolCount   int
	errorCount  int
	width       int
	height      int
	eventCh     chan UIEvent
	quitCh      chan struct{}
	done        bool
}

func NewModel() Model {
	s := spinner.New()
	s.Style = StyleSpinner
	s.Spinner = spinner.Dot

	return Model{
		spinner:   s,
		statusText: "就绪",
		modeText:   "agent",
		modelText:  "claude-sonnet-4",
		eventCh:    make(chan UIEvent, 256),
		quitCh:     make(chan struct{}),
	}
}

func (m Model) Init() tea.Cmd {
	return tea.Batch(
		m.spinner.Tick,
		listenForEvents(m.eventCh),
	)
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		if !m.ready {
			m.viewport = viewport.New(msg.Width-2, msg.Height-4)
			m.viewport.YPosition = 0
			m.viewport.Style = lipgloss.NewStyle().Padding(0, 1)
			m.ready = true
		} else {
			m.viewport.Width = msg.Width - 2
			m.viewport.Height = msg.Height - 4
		}
		return m, nil

	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c", "q":
			m.done = true
			return m, tea.Quit
		case "up", "k":
			m.viewport.LineUp(1)
		case "down", "j":
			m.viewport.LineDown(1)
		case "pgup":
			m.viewport.HalfViewUp()
		case "pgdown":
			m.viewport.HalfViewDown()
		}
		return m, nil

	case UIEvent:
		m.handleEvent(msg)
		return m, nil

	case spinner.TickMsg:
		var cmd tea.CMD
		m.spinner, cmd = m.spinner.Update(msg)
		return m, cmd

	default:
		return m, nil
	}
}

func (m *Model) handleEvent(evt UIEvent) {
	switch evt.Type {
	case EventText:
		m.content.WriteString(StyleMessage.Render(evt.Content) + "\n")

	case EventStream:
		m.content.WriteString(evt.Content)

	case EventToolStart:
		m.toolCount++
		args := evt.Content
		if len(args) > 100 {
			args = args[:100] + "..."
		}
		m.content.WriteString(fmt.Sprintf("\n  %s %s(%s)\n",
			StyleToolCall.Render("🛠"),
			StyleToolCall.Render(evt.Meta["name"]),
			StyleToolCall.Render(args),
		))

	case EventToolResult:
		data := evt.Content
		if len(data) > 200 {
			data = data[:200] + "..."
		}
		icon := "✅"
		if evt.Meta["success"] == "false" {
			icon = "❌"
		}
		m.content.WriteString(fmt.Sprintf("     %s %s\n",
			StyleToolResult.Render(icon),
			StyleToolResult.Render(data),
		))

	case EventError:
		m.errorCount++
		m.content.WriteString(StyleError.Render(fmt.Sprintf("\n  ❌ %s\n", evt.Content)))

	case EventThinking:
		m.content.WriteString(StyleThinking.Render(fmt.Sprintf("\n  💭 %s\n", evt.Content)))

	case EventComplete:
		m.content.WriteString(StyleSeparator.Render("") + "\n")

	case EventStatus:
		m.statusText = evt.Content

	case EventProgress:
		if pct, ok := evt.Meta["percent"]; ok {
			m.statusText = fmt.Sprintf("进度 %s%%", pct)
		}
	}

	// 更新视口
	m.viewport.SetContent(m.content.String())
	m.viewport.GotoBottom()
}

func (m Model) View() string {
	if !m.ready {
		return "\n  初始化中..."
	}

	// 标题栏
	spinnerView := ""
	if m.spinnerOn {
		spinnerView = m.spinner.View() + " "
	}

	title := StyleTitle.Render(fmt.Sprintf("  ClaudeZ  %s", spinnerView))

	// 状态栏
	statusInfo := fmt.Sprintf("  %s  tools:%d  errors:%d",
		m.statusText, m.toolCount, m.errorCount)
	modeInfo := fmt.Sprintf("mode:%s  model:%s", m.modeText, m.modelText)

	statusBar := StyleStatusBar.Render(
		fmt.Sprintf("%-50s %s",
			statusInfo,
			modeInfo,
		),
	)

	// 视口
	viewContent := m.viewport.View()

	// 组装
	main := lipgloss.JoinVertical(
		lipgloss.Left,
		title,
		StyleSeparator.Render(""),
		viewContent,
	)

	footer := lipgloss.NewStyle().Padding(0, 1).Render(
		fmt.Sprintf("  ↑↓/j k 滚动  q/ctrl+c 退出"),
	)

	return lipgloss.JoinVertical(
		lipgloss.Left,
		main,
		statusBar,
		footer,
	)
}

// ── 事件监听 ──

func listenForEvents(ch <-chan UIEvent) tea.Cmd {
	return func() tea.Msg {
		evt, ok := <-ch
		if !ok {
			return nil
		}
		return evt
	}
}

// ── 线程安全的 Push ──

func (m *Model) PushEvent(evt UIEvent) {
	select {
	case m.eventCh <- evt:
	default:
		// 队列满时丢弃，不阻塞
	}
}

func (m *Model) PushText(text string) {
	m.PushEvent(UIEvent{Type: EventText, Content: text})
}

func (m *Model) PushStream(chunk string) {
	m.PushEvent(UIEvent{Type: EventStream, Content: chunk})
}

func (m *Model) PushToolStart(name string, args string) {
	m.PushEvent(UIEvent{
		Type:    EventToolStart,
		Content: args,
		Meta:    map[string]string{"name": name},
	})
}

func (m *Model) PushToolResult(data string, success bool) {
	meta := map[string]string{"success": "true"}
	if !success {
		meta["success"] = "false"
	}
	m.PushEvent(UIEvent{
		Type:    EventToolResult,
		Content: data,
		Meta:    meta,
	})
}

func (m *Model) PushError(err string) {
	m.PushEvent(UIEvent{Type: EventError, Content: err})
}

func (m *Model) PushThinking(msg string) {
	m.PushEvent(UIEvent{Type: EventThinking, Content: msg})
}

func (m *Model) PushComplete() {
	m.PushEvent(UIEvent{Type: EventComplete})
}

func (m *Model) SetStatus(status string) {
	m.PushEvent(UIEvent{Type: EventStatus, Content: status})
}

func (m *Model) SetMode(mode string) {
	m.modeText = mode
}

func (m *Model) SetModelName(name string) {
	m.modelText = name
}

func (m *Model) ToggleSpinner(on bool) {
	m.spinnerOn = on
}

func (m *Model) QuitCh() chan struct{} {
	return m.quitCh
}

// ── 获取内容（用于测试/日志导出） ──

func (m *Model) Content() string {
	return m.content.String()
}
