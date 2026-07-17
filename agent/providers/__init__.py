"""ClaudeZ LLM 提供商。

支持：
  - Anthropic Claude（默认）
  - OpenAI / DeepSeek（兼容 API）
"""

from .base import create_provider, LLMProvider, LLMResponse
