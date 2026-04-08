import os
from dotenv import load_dotenv

# Load the .env file
load_dotenv()

class Settings:
    """Store all configuration settings"""

    # Database settings
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./company.db")
    DATABASE_TYPE: str = os.getenv("DATABASE_TYPE", "sqlite")

    # AI Model settings
    SLM_MODEL_NAME: str = os.getenv("SLM_MODEL_NAME", "google/flan-t5-base")
    DEVICE: str = os.getenv("DEVICE", "cpu")

    # API settings
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Safety
    SAFE_MODE: bool = os.getenv("SAFE_MODE", "true").lower() == "true"

# Create a single settings object to import everywhere
settings = Settings()
