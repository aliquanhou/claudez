// tui/theme.go — 主题配置
package tui

import "github.com/charmbracelet/lipgloss"

func init() {
	// 确保所有样式在 init 时完成初始化
	_ = StyleApp
	_ = StyleTitle
}

// ColorScheme 返回当前配色
func ColorScheme() map[string]lipgloss.Color {
	return map[string]lipgloss.Color{
		"primary":   ColorPrimary,
		"secondary": ColorSecondary,
		"success":   ColorSuccess,
		"warning":   ColorWarning,
		"error":     ColorError,
		"muted":     ColorMuted,
		"bg":        ColorBg,
		"surface":   ColorSurface,
		"text":      ColorText,
	}
}
