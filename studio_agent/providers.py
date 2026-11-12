"""AI providers. Every one speaks the OpenAI Chat Completions format with tool calling."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Provider:
    id: str
    name: str
    base_url: str
    default_model: str
    needs_key: bool
    key_url: str = ""
    note: str = ""
    models: list[str] = field(default_factory=list)
    local: bool = False
    vision: bool = False


PROVIDERS: list[Provider] = [
    Provider(
        id="free",
        name="Free Cloud AI (no key)",
        base_url="free-pool",
        default_model="auto",
        needs_key=False,
        note="No key, no signup. Rotates across free servers (Kilo Gateway, OVHcloud, Pollinations). "
             "Limits are per internet connection, so big builds can slow down. Add a free Gemini or Groq key for speed.",
        models=["auto"],
    ),
    Provider(
        id="gemini",
        name="Google Gemini (free key)",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_model="gemini-2.5-flash",
        needs_key=True,
        key_url="https://aistudio.google.com/apikey",
        note="Free tier with a Google AI Studio key. Strong at coding.",
        models=["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"],
        vision=True,
    ),
    Provider(
        id="groq",
        name="Groq (free key)",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        needs_key=True,
        key_url="https://console.groq.com/keys",
        note="Free tier, very fast.",
        models=["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "qwen/qwen3-32b"],
    ),
    Provider(
        id="openrouter",
        name="OpenRouter (free models)",
        base_url="https://openrouter.ai/api/v1",
        default_model="openrouter/free",
        needs_key=True,
        key_url="https://openrouter.ai/keys",
        note="Free ':free' models with a free key; paid models too.",
        models=["openrouter/free", "deepseek/deepseek-chat-v3.1:free", "qwen/qwen3-coder:free"],
    ),
    Provider(
        id="deepseek",
        name="DeepSeek API",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        needs_key=True,
        key_url="https://platform.deepseek.com/api_keys",
        note="Cheap and very good at Luau.",
        models=["deepseek-chat", "deepseek-reasoner"],
    ),
    Provider(
        id="openai",
        name="OpenAI API",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4.1-mini",
        needs_key=True,
        key_url="https://platform.openai.com/api-keys",
        models=["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"],
        vision=True,
    ),
    Provider(
        id="ollama",
        name="Local AI (Ollama)",
        base_url="http://localhost:11434/v1",
        default_model="qwen2.5-coder:14b",
        needs_key=False,
        key_url="https://ollama.com/download",
        note="Runs on your PC. Pick a model that supports tools (qwen2.5-coder, llama3.1).",
        models=["qwen2.5-coder:14b", "qwen2.5-coder:7b", "llama3.1:8b", "qwen3:14b"],
        local=True,
    ),
    Provider(
        id="custom",
        name="Custom (OpenAI-compatible)",
        base_url="",
        default_model="",
        needs_key=True,
        note="Any OpenAI-compatible endpoint (LM Studio, Together, Mistral...).",
    ),
]


def get_provider(pid: str) -> Provider:
    for p in PROVIDERS:
        if p.id == pid:
            return p
    return PROVIDERS[0]
