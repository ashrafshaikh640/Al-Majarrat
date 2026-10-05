import sqlite3
import urllib.request
import json
import sys
import time

ROOT_DIR = __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from project_config import DB_PATH, EMBEDDING_MODEL, PREFERRED_QURAN_TRANSLATION_ID

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

OLLAMA_API = "http://localhost:11434/api/embed"
BATCH_SIZE = 64

def get_connection():
    if not DB_PATH.exists():
        print(f"Error: {DB_PATH} not found.")
        sys.exit(1)
    return sqlite3.connect(str(DB_PATH), timeout=30.0)

def get_embeddings(texts):
    if not texts:
        return []
    payload = {
        "model": EMBEDDING_MODEL,
        "input": [text[:1000] for text in texts]
    }
    req = urllib.request.Request(OLLAMA_API, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            res = json.loads(response.read().decode('utf-8'))
            embeddings = res.get("embeddings", [])
            if len(embeddings) != len(texts):
                print(f"Embedding API returned {len(embeddings)} vectors for {len(texts)} inputs.")
                return None
            return embeddings
    except Exception as e:
        print(f"Embedding API Error: {e}")
        return None

def init_tables(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quran_vector_index (
            id INTEGER PRIMARY KEY,
            verse_key TEXT UNIQUE,
            embedding_json TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hadith_vector_index (
            id INTEGER PRIMARY KEY,
            hadith_db_id INTEGER UNIQUE,
            reference TEXT,
            embedding_json TEXT
        )
    """)
    conn.commit()

def index_quran(conn, limit=None):
    cursor = conn.cursor()
    sql = """
        SELECT q.id, q.verse_key, q.translation_text
        FROM quran_verses q
        WHERE q.id = (
            SELECT q2.id
            FROM quran_verses q2
            WHERE q2.verse_key = q.verse_key
              AND q2.translation_text != ''
              AND q2.translation_resource_id NOT IN ('ARABIC', '57')
            ORDER BY CASE WHEN q2.translation_resource_id = ? THEN 0 ELSE 1 END, q2.id
            LIMIT 1
        )
        ORDER BY q.chapter_number, q.verse_number
    """
    params = [PREFERRED_QURAN_TRANSLATION_ID]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(0, limit))
    cursor.execute(sql, params)
    verses = cursor.fetchall()
    existing_keys = {row[0] for row in cursor.execute("SELECT verse_key FROM quran_vector_index")}
    pending = [verse for verse in verses if verse[1] not in existing_keys]
    print(f"\n[Vector Indexer] {len(pending):,} of {len(verses):,} Quran verses need indexing...")

    indexed = 0
    failed = False
    start_t = time.time()
    for offset in range(0, len(pending), BATCH_SIZE):
        batch = pending[offset:offset + BATCH_SIZE]
        embeddings = get_embeddings([verse[2] for verse in batch])
        if embeddings is None:
            print("  Embedding failed; stopping Quran indexing. Re-run after the embedding service is available.")
            failed = True
            break
        cursor.executemany(
            "INSERT OR REPLACE INTO quran_vector_index (verse_key, embedding_json) VALUES (?, ?)",
            ((verse[1], json.dumps(embedding)) for verse, embedding in zip(batch, embeddings))
        )
        indexed += len(batch)
        conn.commit()
        if indexed % 512 == 0:
            print(f"  Indexed {indexed}/{len(pending)} verses...")

    conn.commit()
    elapsed = time.time() - start_t
    status = "Stopped" if failed else "Completed"
    print(f"  {status} Quran Vector Indexing: {indexed} new verses indexed in {elapsed:.1f}s.")

def index_hadiths(conn, limit=None):
    cursor = conn.cursor()
    sql = "SELECT id, reference, text_english FROM hadiths WHERE text_english != '' ORDER BY id"
    params = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(0, limit))
    cursor.execute(sql, params)
    hadiths = cursor.fetchall()
    existing_ids = {row[0] for row in cursor.execute("SELECT hadith_db_id FROM hadith_vector_index")}
    pending = [hadith for hadith in hadiths if hadith[0] not in existing_ids]
    print(f"\n[Vector Indexer] {len(pending):,} of {len(hadiths):,} Hadiths need indexing...")

    indexed = 0
    failed = False
    start_t = time.time()
    for offset in range(0, len(pending), BATCH_SIZE):
        batch = pending[offset:offset + BATCH_SIZE]
        embeddings = get_embeddings([hadith[2] for hadith in batch])
        if embeddings is None:
            print("  Embedding failed; stopping Hadith indexing. Re-run after the embedding service is available.")
            failed = True
            break
        cursor.executemany(
            "INSERT OR REPLACE INTO hadith_vector_index (hadith_db_id, reference, embedding_json) VALUES (?, ?, ?)",
            ((hadith[0], hadith[1], json.dumps(embedding)) for hadith, embedding in zip(batch, embeddings))
        )
        indexed += len(batch)
        conn.commit()
        if indexed % 1024 == 0:
            print(f"  Indexed {indexed}/{len(pending)} hadiths...")

    conn.commit()
    elapsed = time.time() - start_t
    status = "Stopped" if failed else "Completed"
    print(f"  {status} Hadith Vector Indexing: {indexed} new Hadiths indexed in {elapsed:.1f}s.")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build Vector Embeddings for Al-Majarrat Database")
    parser.add_argument("--quran-limit", type=int, default=None, help="Limit number of Quran verses to index")
    parser.add_argument("--hadith-limit", type=int, default=None, help="Limit number of Hadiths to index")
    args = parser.parse_args()

    conn = get_connection()
    init_tables(conn)
    index_quran(conn, limit=args.quran_limit)
    index_hadiths(conn, limit=args.hadith_limit)
    cursor = conn.cursor()
    quran_total = cursor.execute("""
        SELECT COUNT(DISTINCT verse_key)
        FROM quran_verses
        WHERE translation_text != '' AND translation_resource_id NOT IN ('ARABIC', '57')
    """).fetchone()[0]
    quran_indexed = cursor.execute("""
        SELECT COUNT(*) FROM quran_vector_index v
        WHERE EXISTS (SELECT 1 FROM quran_verses q WHERE q.verse_key = v.verse_key)
    """).fetchone()[0]
    hadith_total = cursor.execute("SELECT COUNT(*) FROM hadiths WHERE text_english != ''").fetchone()[0]
    hadith_indexed = cursor.execute("""
        SELECT COUNT(*) FROM hadith_vector_index v
        JOIN hadiths h ON h.id = v.hadith_db_id
        WHERE h.text_english != ''
    """).fetchone()[0]
    print(f"Vector coverage: Quran {quran_indexed:,}/{quran_total:,}; Hadith {hadith_indexed:,}/{hadith_total:,}.")
    conn.close()

if __name__ == "__main__":
    main()
