"""
Shadow Voice LLM Providers Package
==================================
Exports all local and cloud LLM providers:
- BaseLLMProvider
- OllamaProvider (Local 100% offline)
- CustomOpenAICompatibleProvider (LM Studio / vLLM / LocalAI)
- GroqProvider (Sub-100ms LPU voice inference)
- OpenRouterProvider (Multi-model cloud aggregator)
- OpenAIProvider (GPT-4o)
- GeminiProvider (Gemini 2.0 Flash)
- AnthropicProvider (Claude 3.5 Sonnet)
"""

from .base import BaseLLMProvider
from .ollama import OllamaProvider
from .custom import CustomOpenAICompatibleProvider
from .groq import GroqProvider
from .openrouter import OpenRouterProvider
from .openai import OpenAIProvider
from .gemini import GeminiProvider
from .anthropic import AnthropicProvider

__all__ = [
    "BaseLLMProvider",
    "OllamaProvider",
    "CustomOpenAICompatibleProvider",
    "GroqProvider",
    "OpenRouterProvider",
    "OpenAIProvider",
    "GeminiProvider",
    "AnthropicProvider"
]
