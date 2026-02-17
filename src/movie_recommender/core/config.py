from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Ratings
    min_rating_kp: float = 6.5
    min_rating_imdb: float = 6.0

    # Torrent filters
    min_seeders: int = 5
    quality_filter: str = "1080p"
    language_filter: str = "dubbing"
    speed_test_mb: int = 50
    speed_test_timeout: int = 60
    min_speed_mbps: float = 5.0

    # Lampa
    lampa_sync_url: str = ""
    lampa_cub_token: str = ""
    lampa_sync_interval: int = 3600

    # API Keys
    kp_api_token: str = ""
    tmdb_api_key: str = ""
    youtube_api_key: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_channel_id: str = ""
    telegram_discussion_group_id: str = ""
    telegram_publish_interval: int = 14400

    # Torrent sources
    jackett_url: str = "http://localhost:9117"
    jackett_api_key: str = ""
    rutracker_login: str = ""
    rutracker_password: str = ""

    # TorrServer
    torrserver_url: str = "http://94.156.232.242:8090"

    # Database
    database_url: str = "sqlite+aiosqlite:///data/movie_recommender.db"

    # Recommender
    recommend_top_n: int = 10
    recommend_interval: int = 86400
    content_types: str = "movie,series,cartoon"


settings = Settings()
