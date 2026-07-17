// tui/spinner.go — 加载动画样式
package tui

import "github.com/charmbracelet/bubbles/spinner"

// NewSpinner 创建 ClaudeZ 风格的加载动画
func NewSpinner() spinner.Model {
	s := spinner.New()
	s.Style = StyleSpinner
	s.Spinner = spinner.Dot
	return s
}

// SpinnerFrames 自定义帧（可选）
var SpinnerFrames = []string{"⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"}
