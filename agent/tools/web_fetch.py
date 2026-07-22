"""tools/web_fetch — 网页抓取工具。

让 Agent 能读取任意网页的纯文本内容。
对齐 Claude Code WebFetch 设计。

依赖:
  pip install requests beautifulsoup4
"""

from __future__ import annotations

from .registry import tool


@tool(
    name="web_fetch",
    category="web",
    timeout=30,
    is_readonly=True,
    is_concurrency_safe=True,
)
def web_fetch(url: str, timeout: int = 15) -> str:
    """抓取网页文本内容，去除噪声（脚本/样式/导航），返回纯文本。

    适用于读取技术文档、查看错误日志、获取 API 响应等场景。
    不渲染 JavaScript，只返回服务器返回的 HTML 解析后的纯文本。
    内容超过 10000 字符时会自动截断。

    Args:
        url: 要抓取的完整 URL（须包含协议，如 https://example.com）
        timeout: 请求超时秒数（默认 15，最长 30）
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return "[错误] 需要安装依赖: pip install requests beautifulsoup4"

    # 超时上限
    effective_timeout = min(max(timeout, 5), 30)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    try:
        response = requests.get(url, headers=headers, timeout=effective_timeout)
        response.raise_for_status()

        # 检测编码
        if response.encoding and response.encoding.lower() == "iso-8859-1":
            # 让 BeautifulSoup 自动检测
            response.encoding = None

        soup = BeautifulSoup(response.text, "html.parser")

        # 移除噪声标签
        for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                          "noscript", "iframe", "svg", "form", "input",
                          "button", "select", "option", "canvas"]):
            tag.decompose()

        # 提取标题
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        # 提取纯文本（空行分隔）
        content = soup.get_text(separator="\n", strip=True)

        # 清理多余空行
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        content = "\n".join(lines)

        # 截断过长内容
        max_len = 10000
        truncated = False
        if len(content) > max_len:
            content = content[:max_len]
            truncated = True

        # 构建结果
        result = f"=== {title} ===\n\n" if title else ""
        result += content
        if truncated:
            result += "\n\n... (内容已截断至 10000 字符，请指定更精确的 URL)"

        return result

    except requests.exceptions.Timeout:
        return f"[错误] 请求超时 ({effective_timeout}s)：{url}"
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code
        if status == 403:
            return f"[错误] 被服务器拒绝 (403 Forbidden)：{url}"
        elif status == 404:
            return f"[错误] 页面不存在 (404)：{url}"
        return f"[错误] HTTP {status}：{url}"
    except requests.exceptions.ConnectionError:
        return f"[错误] 无法连接：{url}（域名解析失败或服务器不可达）"
    except requests.exceptions.MissingSchema:
        return f"[错误] URL 格式无效（须包含协议，如 https://）：{url}"
    except Exception as e:
        return f"[错误] 抓取失败：{e}"
