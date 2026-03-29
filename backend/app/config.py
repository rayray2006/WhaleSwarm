"""Configuration loaded from environment variables."""
import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv


@dataclass
class Config:
    # Primary LLM
    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model_name: str = "qwen/qwen3-235b-a22b-2507"

    # Smart LLM (falls back to primary if not set)
    smart_provider: Optional[str] = None
    smart_api_key: Optional[str] = None
    smart_base_url: Optional[str] = None
    smart_model_name: Optional[str] = None

    # Embeddings
    embedding_provider: str = "openai"
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_base_url: str = "https://openrouter.ai/api"
    embedding_api_key: str = ""
    embedding_dimensions: int = 768

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "WhaleSwarm"

    # Simulation
    default_max_rounds: int = 10

    # Web enrichment
    web_enrichment_enabled: bool = True
    web_search_model: Optional[str] = None

    # Polymarket real-price anchoring
    polymarket_clob_url: str = "https://clob.polymarket.com"
    polymarket_anchoring_enabled: bool = False

    # Server
    flask_host: str = "0.0.0.0"
    flask_port: int = 5001
    flask_debug: bool = False

    # Extension A
    bet_calibration_enabled: bool = False
    bet_calibration_cdf_path: str = "backend/data/polymarket_cdfs/cdfs.json"
    bet_calibration_fallback: str = "heuristic"

    # Vertex AI
    vertex_project: str = ""
    vertex_location: str = "us-central1"

    # Extension B
    agent_persistence_enabled: bool = False
    model_tier_base: str = "gemini-2.5-flash-lite"
    model_tier_mid: str = "gemini-2.5-flash"
    model_tier_top: str = "gemini-2.5-pro"
    kill_threshold: float = 0.0
    whale_percentile: float = 0.01
    elite_percentile: float = 0.001

    # Derived paths
    upload_dir: str = ""

    def __post_init__(self):
        if not self.upload_dir:
            self.upload_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "uploads",
            )
        os.makedirs(os.path.join(self.upload_dir, "projects"), exist_ok=True)
        os.makedirs(os.path.join(self.upload_dir, "simulations"), exist_ok=True)
        os.makedirs(os.path.join(self.upload_dir, "reports"), exist_ok=True)
        os.makedirs(os.path.join(self.upload_dir, "series"), exist_ok=True)

        # Smart LLM falls back to primary
        if not self.smart_provider:
            self.smart_provider = self.llm_provider
        if not self.smart_api_key:
            self.smart_api_key = self.llm_api_key
        if not self.smart_base_url:
            self.smart_base_url = self.llm_base_url
        if not self.smart_model_name:
            self.smart_model_name = self.llm_model_name

    @classmethod
    def from_env(cls, dotenv_path: str = None) -> "Config":
        # Try explicit path, then project root, then cwd
        if dotenv_path:
            load_dotenv(dotenv_path)
        else:
            # Search upward for .env
            here = os.path.dirname(os.path.abspath(__file__))
            for candidate in [
                os.path.join(here, "..", "..", ".env"),  # backend/.env (project root)
                os.path.join(here, "..", ".env"),
                ".env",
            ]:
                if os.path.exists(candidate):
                    load_dotenv(candidate)
                    break
            else:
                load_dotenv()

        def get(key, default=""):
            return os.getenv(key, default)

        def get_bool(key, default=False):
            return get(key, str(default)).lower() in ("true", "1", "yes")

        def get_int(key, default=0):
            try:
                return int(get(key, str(default)))
            except ValueError:
                return default

        def get_float(key, default=0.0):
            try:
                return float(get(key, str(default)))
            except ValueError:
                return default

        return cls(
            llm_provider=get("LLM_PROVIDER", "openai"),
            llm_api_key=get("LLM_API_KEY"),
            llm_base_url=get("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
            llm_model_name=get("LLM_MODEL_NAME", "qwen/qwen3-235b-a22b-2507"),
            smart_provider=get("SMART_PROVIDER") or None,
            smart_api_key=get("SMART_API_KEY") or None,
            smart_base_url=get("SMART_BASE_URL") or None,
            smart_model_name=get("SMART_MODEL_NAME") or None,
            embedding_provider=get("EMBEDDING_PROVIDER", "openai"),
            embedding_model=get("EMBEDDING_MODEL", "openai/text-embedding-3-small"),
            embedding_base_url=get("EMBEDDING_BASE_URL", "https://openrouter.ai/api"),
            embedding_api_key=get("EMBEDDING_API_KEY"),
            embedding_dimensions=get_int("EMBEDDING_DIMENSIONS", 768),
            neo4j_uri=get("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=get("NEO4J_USER", "neo4j"),
            neo4j_password=get("NEO4J_PASSWORD", "WhaleSwarm"),
            default_max_rounds=get_int("DEFAULT_MAX_ROUNDS", 10),
            polymarket_clob_url=get("POLYMARKET_CLOB_URL", "https://clob.polymarket.com"),
            polymarket_anchoring_enabled=get_bool("POLYMARKET_ANCHORING_ENABLED", False),
            web_enrichment_enabled=get_bool("WEB_ENRICHMENT_ENABLED", True),
            web_search_model=get("WEB_SEARCH_MODEL") or None,
            flask_host=get("FLASK_HOST", "0.0.0.0"),
            flask_port=get_int("FLASK_PORT", 5001),
            flask_debug=get_bool("FLASK_DEBUG", False),
            bet_calibration_enabled=get_bool("BET_CALIBRATION_ENABLED", False),
            bet_calibration_cdf_path=get("BET_CALIBRATION_CDF_PATH", "backend/data/polymarket_cdfs/cdfs.json"),
            bet_calibration_fallback=get("BET_CALIBRATION_FALLBACK", "heuristic"),
            vertex_project=get("GOOGLE_CLOUD_PROJECT", ""),
            vertex_location=get("GOOGLE_CLOUD_LOCATION", "us-central1"),
            agent_persistence_enabled=get_bool("AGENT_PERSISTENCE_ENABLED", False),
            model_tier_base=get("MODEL_TIER_BASE", "gemini-2.5-flash-lite"),
            model_tier_mid=get("MODEL_TIER_MID", "gemini-2.5-flash"),
            model_tier_top=get("MODEL_TIER_TOP", "gemini-2.5-pro"),
            kill_threshold=get_float("KILL_THRESHOLD", 0.0),
            whale_percentile=get_float("WHALE_PERCENTILE", 0.01),
            elite_percentile=get_float("ELITE_PERCENTILE", 0.001),
        )
