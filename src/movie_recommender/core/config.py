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
    torrserver_url: str = "http://150.241.81.67:17090"

    # Database
    database_url: str = "sqlite+aiosqlite:///data/movie_recommender.db"

    # Recommender
    recommend_top_n: int = 10
    recommend_interval: int = 86400
    content_types: str = "movie,series,cartoon"
    pipeline_interval_hours: int = 12

    # Lampa CUB community reactions
    cub_api_url: str = "https://cub.rip/api/reactions/get"
    cub_mirrors: list[str] = ["https://cubnotrip.top/api/reactions/get"]
    cub_min_fires: int = 50

    # Recommendation filters
    rec_min_year: int = 2020
    rec_blocked_countries: list[str] = [
        "Mexico", "Taiwan", "India", "Vietnam", "Brazil",
        "Russia", "Belarus", "Ukraine", "Kazakhstan", "Uzbekistan",
        "Kyrgyzstan", "Tajikistan", "Turkmenistan", "Armenia",
        "Azerbaijan", "Moldova", "Georgia",
    ]
    rec_bayesian_prior: float = 6.5
    rec_bayesian_min_votes: int = 500
    rec_bayesian_min_rating: float = 7.0
    rec_bayesian_vote_threshold: int = 200

    # Ranking weights
    rank_quality: float = 0.25
    rank_fire_ratio: float = 0.20
    rank_cub_popularity: float = 0.15
    rank_tmdb_popularity: float = 0.10
    rank_pipeline: float = 0.10
    rank_freshness: float = 0.20

    # API rate limiting
    tmdb_request_delay: float = 0.3
    publish_delay: float = 3.0

    # LLM reranker (Claude Sonnet)
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"  # Sonnet 4.6 — verified valid 2026-04-26
    llm_rerank_enabled: bool = True
    llm_rerank_shortlist_size: int = 30
    llm_max_tokens: int = 2000
    llm_timeout_seconds: int = 60
    llm_debug_log: bool = False  # if True, dump prompts/responses to data/llm_debug/{date}.json

    # Published TTL — re-recommend movies older than this
    published_ttl_days: int = 60

    # Lampa watch progress thresholds (ratio = time_watched / duration)
    finished_threshold: float = 0.80      # ratio > 0.80 => "finished" signal
    dropped_min_threshold: float = 0.10   # 0.10 <= ratio <= dropped_max => "dropped" signal
    dropped_max_threshold: float = 0.50


settings = Settings()
