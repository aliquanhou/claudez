// updater/check.go — 自动更新检查
//
// 文档对齐：原生 Harness 自动更新机制
// 功能：GitHub Release 检查、版本对比、增量下载

package updater

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"time"
)

// ── 版本信息 ──

const (
	Owner = "claudez"
	Repo  = "claudez"
)

var (
	CurrentVersion = "1.0.0"
	CheckURL       = fmt.Sprintf("https://api.github.com/repos/%s/%s/releases/latest", Owner, Repo)
)

// ── Release 信息 ──

type ReleaseInfo struct {
	Version     string `json:"tag_name"`
	PublishedAt string `json:"published_at"`
	Body        string `json:"body"`
	Assets      []AssetInfo `json:"assets"`
}

type AssetInfo struct {
	Name        string `json:"name"`
	URL         string `json:"browser_download_url"`
	Size        int64  `json:"size"`
	ContentType string `json:"content_type"`
}

type UpdateStatus int

const (
	StatusCurrent UpdateStatus = iota
	StatusAvailable
	StatusCheckFailed
)

type UpdateResult struct {
	Status    UpdateStatus
	Current   string
	Latest    string
	Release   *ReleaseInfo
	Error     error
}

// ── 更新检查器 ──

type Checker struct {
	CurrentVersion string
	CheckURL       string
	HTTPClient     *http.Client
	Platform       string
	Arch           string
}

func NewChecker() *Checker {
	return &Checker{
		CurrentVersion: CurrentVersion,
		CheckURL:       CheckURL,
		HTTPClient: &http.Client{
			Timeout: 10 * time.Second,
			Transport: &http.Transport{
				IdleConnTimeout: 5 * time.Second,
			},
		},
		Platform: runtime.GOOS,
		Arch:     runtime.GOARCH,
	}
}

func (c *Checker) Check() *UpdateResult {
	result := &UpdateResult{
		Current: c.CurrentVersion,
	}

	req, err := http.NewRequest("GET", c.CheckURL, nil)
	if err != nil {
		result.Status = StatusCheckFailed
		result.Error = fmt.Errorf("创建请求失败: %w", err)
		return result
	}
	req.Header.Set("Accept", "application/vnd.github.v3+json")
	req.Header.Set("User-Agent", "ClaudeZ-Harness/"+c.CurrentVersion)

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		result.Status = StatusCheckFailed
		result.Error = fmt.Errorf("检查更新失败: %w", err)
		return result
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		result.Status = StatusCheckFailed
		result.Error = fmt.Errorf("读取响应失败: %w", err)
		return result
	}

	var release ReleaseInfo
	if err := json.Unmarshal(body, &release); err != nil {
		result.Status = StatusCheckFailed
		result.Error = fmt.Errorf("解析响应失败: %w", err)
		return result
	}

	// 去除版本号前的 'v'
	latest := release.Version
	if len(latest) > 0 && latest[0] == 'v' {
		latest = latest[1:]
	}
	result.Latest = latest
	result.Release = &release

	if latest > c.CurrentVersion {
		result.Status = StatusAvailable
	} else {
		result.Status = StatusCurrent
	}

	return result
}

// ── 平台资产查找 ──

func (c *Checker) FindPlatformAsset(release *ReleaseInfo) *AssetInfo {
	pattern := fmt.Sprintf("claudez-harness-%s-%s", c.Platform, c.Arch)
	for _, asset := range release.Assets {
		if matchesPlatform(asset.Name, c.Platform, c.Arch) {
			return &asset
		}
		_ = pattern
	}
	return nil
}

func matchesPlatform(name, platform, arch string) bool {
	patterns := []string{
		fmt.Sprintf("%s-%s", platform, arch),
		fmt.Sprintf("%s_%s", platform, arch),
	}
	if platform == "windows" {
		patterns = append(patterns,
			fmt.Sprintf("win32-%s", arch),
			fmt.Sprintf("win-%s", arch),
		)
	}
	for _, p := range patterns {
		if contains(name, p) {
			return true
		}
	}
	return false
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr ||
		(len(s) > len(substr) && (s[:len(substr)] == substr || s[len(s)-len(substr):] == substr)))
}

// ── 下载更新 ──

func (c *Checker) Download(asset *AssetInfo, destDir string) (string, error) {
	resp, err := c.HTTPClient.Get(asset.URL)
	if err != nil {
		return "", fmt.Errorf("下载失败: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("下载失败: HTTP %d", resp.StatusCode)
	}

	destPath := filepath.Join(destDir, asset.Name)
	f, err := os.Create(destPath)
	if err != nil {
		return "", fmt.Errorf("创建文件失败: %w", err)
	}
	defer f.Close()

	written, err := io.Copy(f, resp.Body)
	if err != nil {
		return "", fmt.Errorf("写入文件失败: %w", err)
	}

	// 验证大小
	if asset.Size > 0 && written != asset.Size {
		return "", fmt.Errorf("文件大小不匹配: 期望 %d, 实际 %d", asset.Size, written)
	}

	// 设置可执行权限 (Unix)
	if runtime.GOOS != "windows" {
		os.Chmod(destPath, 0755)
	}

	return destPath, nil
}

// ── 格式化工具有无更新 ──

func (r *UpdateResult) String() string {
	switch r.Status {
	case StatusCurrent:
		return fmt.Sprintf("已是最新版本: %s", r.Current)
	case StatusAvailable:
		return fmt.Sprintf("发现新版本: %s → %s", r.Current, r.Latest)
	case StatusCheckFailed:
		return fmt.Sprintf("检查更新失败: %v", r.Error)
	default:
		return "未知状态"
	}
}
