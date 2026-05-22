from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    dpe_normalization_enabled: bool = False
    dpe_normalization_min_confidence: float = 0.55
    dpe_normalization_max_chars: int = 8000
    uce_base_url: str = "http://uce:8100"
    uce_denoise_enabled: bool = True

    class Config:
        env_file = ".env"


settings = Settings()
