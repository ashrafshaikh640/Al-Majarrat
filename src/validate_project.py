import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from project_config import (
    BASE_DIR,
    DB_PATH,
    DEFAULT_LOCAL_ENDPOINT,
    DEFAULT_MODEL,
    EMBEDDING_MODEL,
    OLLAMA_EMBED_API,
    OLLAMA_TAGS_URL,
    REQUIRED_DATA_FILES,
)


def check_data_files():
    missing = [str(path) for path in REQUIRED_DATA_FILES if not path.exists()]
    if missing:
        return {"ok": False, "messages": [f"Missing dataset file(s): {', '.join(missing)}"]}
    return {"ok": True, "messages": ["All source corpus files are present."]}


def check_database(db_path=DB_PATH):
    database_path = Path(db_path)
    if not database_path.exists():
        return {"ok": False, "messages": [f"Database file not found: {database_path}"]}

    required_tables = {"hadiths", "quran_verses", "hadiths_fts", "quran_fts"}
    try:
        with sqlite3.connect(str(database_path), timeout=5.0) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            missing = sorted(required_tables - tables)
            if missing:
                return {"ok": False, "messages": [f"Missing required tables: {', '.join(missing)}"]}

            hadith_count = conn.execute("SELECT COUNT(*) FROM hadiths").fetchone()[0]
            quran_count = conn.execute("SELECT COUNT(*) FROM quran_verses").fetchone()[0]
            return {
                "ok": True,
                "messages": [
                    f"Database is valid: {hadith_count} hadith rows, {quran_count} quran rows.",
                    "Required tables are present.",
                ],
            }
    except sqlite3.Error as exc:
        return {"ok": False, "messages": [f"Database validation failed: {exc}"]}


def check_ollama_models(endpoint=DEFAULT_LOCAL_ENDPOINT, model_name=DEFAULT_MODEL, embedding_model=EMBEDDING_MODEL):
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
            models = [item.get("name", "") for item in payload.get("models", [])]
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return {
            "ok": False,
            "messages": [f"Ollama is not responding at {OLLAMA_TAGS_URL}."] ,
            "models": [],
        }

    available = {name for name in models}
    chat_ok = any(name == model_name or name.startswith(f"{model_name}:") for name in available)
    embedding_ok = any(name == embedding_model or name.startswith(f"{embedding_model}:") for name in available)

    messages = []
    if not chat_ok:
        messages.append(f"Chat model '{model_name}' is not installed in Ollama.")
    if not embedding_ok:
        messages.append(f"Embedding model '{embedding_model}' is not installed in Ollama.")
    if not messages:
        messages.append("Ollama backend and required models are available.")

    return {
        "ok": chat_ok and embedding_ok,
        "messages": messages,
        "models": sorted(models),
    }


def run_validation(db_path=DB_PATH):
    steps = [
        ("data_files", check_data_files()),
        ("database", check_database(db_path)),
        ("ollama", check_ollama_models()),
    ]

    all_ok = True
    for name, result in steps:
        if not result["ok"]:
            all_ok = False
        print(f"[{name}] {'OK' if result['ok'] else 'FAIL'}")
        for message in result.get("messages", []):
            print(f"  - {message}")

    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Validate the Al-Majarrat project environment.")
    parser.add_argument("--db-path", type=str, default=str(DB_PATH), help="Path to the SQLite database file.")
    parser.add_argument("--skip-ollama", action="store_true", help="Skip Ollama connectivity validation.")
    args = parser.parse_args()

    steps = [
        ("data_files", check_data_files()),
        ("database", check_database(args.db_path)),
    ]
    if not args.skip_ollama:
        steps.append(("ollama", check_ollama_models()))

    all_ok = True
    for name, result in steps:
        print(f"[{name}] {'OK' if result['ok'] else 'FAIL'}")
        for message in result.get("messages", []):
            print(f"  - {message}")
        all_ok = all_ok and result["ok"]

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
