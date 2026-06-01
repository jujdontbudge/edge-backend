from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""

    anthropic_api_key: str = ""
    openai_api_key: str = ""

    tutor_model_free: str = "claude-haiku-4-5"
    tutor_model_pro: str = "claude-sonnet-4-6"

    eval_model: str = "claude-haiku-4-5-20251001"

    tutor_daily_limit_free: int = 5
    tutor_daily_limit_pro: int = 500

    eval_daily_limit_free: int = 50
    eval_daily_limit_pro: int = 500

    onesignal_app_id: str = ""
    onesignal_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
