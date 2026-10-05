import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import al_majarrat as rag
from project_config import BASE_DIR, DB_PATH as PROJECT_DB_PATH, OLLAMA_TAGS_URL


ROOT = BASE_DIR
WEB_ROOT = ROOT / "web"
DB_PATH = PROJECT_DB_PATH
MAX_REQUEST_BYTES = 16_384


def get_status():
    database = {"ready": False, "hadiths": 0, "verses": 0, "quran_vectors": 0, "hadith_vectors": 0}
    if DB_PATH.exists():
        try:
            uri = f"file:{DB_PATH.as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=3) as conn:
                database.update({
                    "ready": True,
                    "hadiths": conn.execute("SELECT COUNT(*) FROM hadiths").fetchone()[0],
                    "verses": conn.execute("SELECT COUNT(DISTINCT verse_key) FROM quran_verses").fetchone()[0],
                    "quran_vectors": conn.execute("SELECT COUNT(*) FROM quran_vector_index").fetchone()[0],
                    "hadith_vectors": conn.execute("SELECT COUNT(*) FROM hadith_vector_index").fetchone()[0],
                })
        except sqlite3.Error as error:
            database["error"] = str(error)

    ollama = {"ready": False, "models": [], "chat_model": rag.DEFAULT_MODEL, "embedding_model": rag.EMBEDDING_MODEL}
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=2) as response:
            model_rows = json.loads(response.read().decode("utf-8")).get("models", [])
        ollama["models"] = [item.get("name", "") for item in model_rows]
        ollama["ready"] = True
        ollama["chat_model_available"] = any(
            name == rag.DEFAULT_MODEL or name.startswith(f"{rag.DEFAULT_MODEL}:")
            for name in ollama["models"]
        )
        ollama["embedding_model_available"] = any(
            name == rag.EMBEDDING_MODEL or name.startswith(f"{rag.EMBEDDING_MODEL}:")
            for name in ollama["models"]
        )
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        ollama["error"] = str(error)

    return {"database": database, "ollama": ollama}


class WebHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def do_GET(self):
        if self.path == "/api/status":
            self.send_json(200, get_status())
            return
        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/ask":
            self.send_json(404, {"error": "Endpoint not found."})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self.send_json(413, {"error": "Request must be under 16 KB."})
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            query = str(payload.get("query", "")).strip()
            mode = payload.get("mode", "all")
            if not query:
                self.send_json(400, {"error": "Enter a question to search."})
                return
            if len(query) > 2_000:
                self.send_json(400, {"error": "Question is limited to 2,000 characters."})
                return
            if mode not in {"all", "quran", "hadith"}:
                self.send_json(400, {"error": "Choose Quran, Hadith, or all sources."})
                return

            quran, hadith = rag.retrieve_hybrid_context(query)
            if mode == "quran":
                hadith = []
            elif mode == "hadith":
                quran = []
            system_prompt, user_message = rag.build_prompt(query, quran, hadith)
            answer = rag.query_local_llm(system_prompt, user_message)
            self.send_json(200, {
                "query": query,
                "mode": mode,
                "answer": answer,
                "quran": quran,
                "hadith": hadith,
                "generated": not answer.startswith(("LOCAL_LLM_OFFLINE:", "LOCAL_LLM_ERROR:")),
            })
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError) as error:
            self.send_json(400, {"error": f"Invalid request: {error}"})
        except Exception as error:
            self.send_json(500, {"error": f"Search failed: {error}"})

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        print(f"[Web UI] {self.address_string()} - {format_string % args}")


def main():
    parser = argparse.ArgumentParser(description="Local Al-Majarrat Quran and Hadith research UI")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (defaults to localhost only)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not WEB_ROOT.is_dir():
        raise SystemExit(f"Web assets not found: {WEB_ROOT}")

    server = ThreadingHTTPServer((args.host, args.port), WebHandler)
    print(f"Al-Majarrat Research Desk: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Al-Majarrat Research Desk.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()