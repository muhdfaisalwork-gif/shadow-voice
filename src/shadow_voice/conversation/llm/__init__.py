"""
Shadow Voice Conversation LLM Package
=====================================
Multi-model LLM streaming engine supporting:
- 100% Local Models: Ollama (localhost:11434), LM Studio / vLLM (localhost:1234/v1)
- Cloud Models: Groq, OpenRouter, OpenAI, Gemini, Anthropic
- Barge-in token cancellation and TTFT instrumentation
- Full backward compatibility with StreamingLLMClient
"""

from .client import UniversalLLMClient, StreamingLLMClient, LLMGenerationResult
from .providers import (
    BaseLLMProvider,
    OllamaProvider,
    CustomOpenAICompatibleProvider,
    GroqProvider,
    OpenRouterProvider,
    OpenAIProvider,
    GeminiProvider,
    AnthropicProvider
)

__all__ = [
    "UniversalLLMClient",
    "StreamingLLMClient",
    "LLMGenerationResult",
    "BaseLLMProvider",
    "OllamaProvider",
    "CustomOpenAICompatibleProvider",
    "GroqProvider",
    "OpenRouterProvider",
    "OpenAIProvider",
    "GeminiProvider",
    "AnthropicProvider"
]
