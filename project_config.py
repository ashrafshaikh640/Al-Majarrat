from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CORPUS_DIR = DATA_DIR / "corpora"
DB_DIR = DATA_DIR / "db"
DATASETS_DIR = DATA_DIR / "datasets"
RAW_DIR = DATA_DIR / "raw"
MODELS_DIR = DATA_DIR / "models"

DB_PATH = DB_DIR / "al_majarrat_master.db"
HADITH_MASTER_CSV = CORPUS_DIR / "hadith_master_corpus.csv"
QURAN_CORPUS_CSV = CORPUS_DIR / "quran_corpus.csv"
ALPACA_DATASET = DATASETS_DIR / "majarrat_finetune_alpaca.jsonl"
CHAT_DATASET = DATASETS_DIR / "majarrat_finetune_chat.jsonl"

DEFAULT_LOCAL_ENDPOINT = "http://localhost:11434/v1/chat/completions"
DEFAULT_MODEL = "qwen2.5:3b"
EMBEDDING_MODEL = "nomic-embed-text"
OLLAMA_EMBED_API = "http://localhost:11434/api/embeddings"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
PREFERRED_QURAN_TRANSLATION_ID = "20"

REQUIRED_DATA_FILES = (
    CORPUS_DIR / "bukhari_corpus.csv",
    CORPUS_DIR / "muslim_corpus.csv",
    CORPUS_DIR / "nasai_corpus.csv",
    CORPUS_DIR / "abudawud_corpus.csv",
    CORPUS_DIR / "tirmidhi_corpus.csv",
    CORPUS_DIR / "ibnmajah_corpus.csv",
    QURAN_CORPUS_CSV,
)


def project_path(*parts):
    return str(BASE_DIR.joinpath(*parts))
