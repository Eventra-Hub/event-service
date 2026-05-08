from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MONGO_URL: str
    DB_NAME: str
    JWT_SECRET: str
    RABBITMQ_URL: str
    PORT: int = 8000
    SERVICE_NAME: str = "event-service"
    REGISTRATION_SERVICE_URL: str = "http://localhost:8003"

    class Config:
        env_file = ".env"

settings = Settings()
