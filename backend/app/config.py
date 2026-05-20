from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "mysql+aiomysql://root:Mobigen_1234@localhost:3306/chat_demo"
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str = ""
    openai_model: str = "openai/gpt-4o"
    anthropic_api_key: str = ""
    anthropic_model: str = "anthropic/claude-sonnet-4-5"
    default_ollama_model: str = "gemma4:26b"
    uce_enabled: bool = False
    uce_base_url: str = "http://uce:8080"
    uce_timeout_seconds: float = 15.0
    uce_debug_enabled: bool = False
    rca_debug_enabled: bool = True

    class Config:
        env_file = ".env"


settings = Settings()
