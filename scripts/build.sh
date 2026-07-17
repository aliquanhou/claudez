#!/bin/bash
# scripts/build.sh — 构建 ClaudeZ 组件
# 用法: bash scripts/build.sh [harness|py|all]

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "🔨 ClaudeZ Build Script"
echo "========================"

build_harness() {
    echo ""
    echo "📦 构建 Go Harness..."

    cd harness

    # 构建各平台
    echo "  → Windows x64..."
    GOOS=windows GOARCH=amd64 go build -ldflags="-s -w" -o "../@claudez/harness-win32-x64/bin/claudez.exe" .

    echo "  → macOS ARM64..."
    GOOS=darwin GOARCH=arm64 go build -ldflags="-s -w" -o "../@claudez/harness-darwin-arm64/bin/claudez" .

    echo "  → Linux x64..."
    GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o "../@claudez/harness-linux-x64/bin/claudez" .

    cd "$ROOT"
    echo "  ✅ Harness 构建完成"
}

build_py() {
    echo ""
    echo "📦 构建 Python 包..."

    # 检查依赖
    python -c "import anthropic, openai, chromadb, psutil" 2>/dev/null || {
        echo "  ⚠️  安装 Python 依赖..."
        pip install anthropic openai chromadb psutil
    }

    # 验证导入
    python -c "
import sys
sys.path.insert(0, '.')
from agent.core import Agent
from agent.providers import create_provider
from agent.tools import get_all_tools
from agent.prompt import build_system_prompt, PromptContext
print('  ✅ Python 核心导入成功')
print(f'  工具数量: {len(get_all_tools())}')
" || {
        echo "  ❌ Python 核心验证失败"
        exit 1
    }

    cd "$ROOT"
    echo "  ✅ Python 包验证完成"
}

case "${1:-all}" in
    harness)
        build_harness
        ;;
    py)
        build_py
        ;;
    all)
        build_py
        build_harness
        ;;
esac

echo ""
echo "✅ 构建完成"
