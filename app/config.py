from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://jobradar:jobradar@localhost:5432/jobradar"

    anthropic_api_key: str = ""
    brave_search_api_key: str = ""

    # Model adı sağlayıcıyı da belirler:
    #   claude-haiku-4-5  → Anthropic API
    #   ollama:qwen3:8b   → yerelde Ollama (ücretsiz, veri makineden çıkmaz)
    model_detect: str = "claude-opus-5"
    model_extract: str = "claude-haiku-4-5"
    model_score: str = "claude-haiku-4-5"
    model_tailor: str = "claude-opus-5"

    # "localhost" yerine 127.0.0.1: Windows'ta localhost önce IPv6'ya çözülür ve
    # yalnızca IPv4 dinleyen bir servise bağlanmak TCP zaman aşımı kadar sürer.
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_timeout: float = 900.0

    crawler_user_agent: str = "jobradar/0.1"
    crawl_domain_delay: float = 2.0
    crawl_timeout: float = 20.0
    crawl_concurrency: int = 8
    respect_robots_txt: bool = True

    panel_host: str = "0.0.0.0"
    panel_port: int = 8000

    delivery_dry_run: bool = True
    gmail_credentials_path: str = "./secrets/gmail_client_secret.json"
    gmail_token_path: str = "./secrets/gmail_token.json"

    embedding_model: str = "intfloat/multilingual-e5-base"
    embedding_dim: int = 768


@lru_cache
def get_settings() -> Settings:
    return Settings()
