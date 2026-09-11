import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # OpenAI / Ollama LLM
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
    AVAILABLE_MODELS = [m.strip() for m in os.getenv("AVAILABLE_MODELS", "Qwen3.7-Max").split(",")]
    MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "4000"))

    # Ollama / Embedding
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"))
    EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "ollama")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "qwen3-embedding:8b")
    EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "4096"))

    # RAG
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
    RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
    RAG_HYBRID_ENABLED = os.getenv("RAG_HYBRID_ENABLED", "true").lower() == "true"
    RAG_BM25_WEIGHT = float(os.getenv("RAG_BM25_WEIGHT", "0.3"))
    RAG_VECTOR_WEIGHT = float(os.getenv("RAG_VECTOR_WEIGHT", "0.7"))
    RAG_QUERY_REWRITE_ENABLED = os.getenv("RAG_QUERY_REWRITE_ENABLED", "false").lower() == "true"
    RAG_RERANK_ENABLED = os.getenv("RAG_RERANK_ENABLED", "false").lower() == "true"

    # Files
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")
    IMAGE_UPLOAD_FOLDER = os.getenv("IMAGE_UPLOAD_FOLDER", "uploads/images")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(50 * 1024 * 1024)))

    # Tools
    WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "false").lower() == "true"
    WEB_SEARCH_PROVIDER = os.getenv("WEB_SEARCH_PROVIDER", "duckduckgo")
    CODE_EXEC_ENABLED = os.getenv("CODE_EXEC_ENABLED", "true").lower() == "true"
    CODE_EXEC_TIMEOUT = int(os.getenv("CODE_EXEC_TIMEOUT", "10"))
    SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

    # API Key (安全认证)
    API_KEY = os.getenv("API_KEY", "")
    INPUT_FILTER_ENABLED = os.getenv("INPUT_FILTER_ENABLED", "true").lower() == "true"

    # Cache (响应优化)
    CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() == "true"
    CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "1"))
    CACHE_MAX_SIZE = int(os.getenv("CACHE_MAX_SIZE", "1000"))

    # Retry (错误恢复)
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_DELAY_SECONDS = int(os.getenv("RETRY_DELAY_SECONDS", "2"))
    FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "")

    # LangSmith
    LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "false")
    LANGCHAIN_PROJECT = os.getenv("LANGCHAIN_PROJECT", "flask_chat")
    LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY", "")
    LANGCHAIN_ENDPOINT = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")

    # Answer Verification
    VERIFY_ENABLED = os.getenv("VERIFY_ENABLED", "false").lower() == "true"
    VERIFY_MODEL = os.getenv("VERIFY_MODEL", "")
