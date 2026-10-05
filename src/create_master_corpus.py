import csv
import os
import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from project_config import BASE_DIR, CORPUS_DIR, DB_PATH, QURAN_CORPUS_CSV

HADITH_FILES = [
    ("bukhari", "Sahih al-Bukhari", "صحيح البخاري", CORPUS_DIR / "bukhari_corpus.csv"),
    ("muslim", "Sahih Muslim", "صحيح مسلم", CORPUS_DIR / "muslim_corpus.csv"),
    ("nasai", "Sunan an-Nasa'i", "سنن النسائي", CORPUS_DIR / "nasai_corpus.csv"),
    ("abudawud", "Sunan Abi Dawud", "سنن أبي داود", CORPUS_DIR / "abudawud_corpus.csv"),
    ("tirmidhi", "Jami` at-Tirmidhi", "جامع الترمذي", CORPUS_DIR / "tirmidhi_corpus.csv"),
    ("ibnmajah", "Sunan Ibn Majah", "سنن ابن ماجه", CORPUS_DIR / "ibnmajah_corpus.csv")
]

QURAN_FILE = QURAN_CORPUS_CSV
OUTPUT_HADITH_CSV = CORPUS_DIR / "hadith_master_corpus.csv"
OUTPUT_DB = DB_PATH

def build_hadith_master_csv():
    print(f"Building {OUTPUT_HADITH_CSV}...")
    fieldnames = [
        "collection_slug",
        "collection_name_en",
        "collection_name_ar",
        "book_id",
        "book_name_en",
        "book_name_ar",
        "chapter_id",
        "chapter_name_en",
        "chapter_name_ar",
        "hadith_id",
        "hadith_id_in_book",
        "narrator",
        "text_english",
        "text_arabic",
        "grading",
        "reference"
    ]

    total_count = 0
    with open(str(OUTPUT_HADITH_CSV), "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()

        for slug, name_en, name_ar, filepath in HADITH_FILES:
            if not os.path.exists(filepath):
                print(f"Warning: {filepath} not found, skipping...")
                continue
            
            count = 0
            with open(str(filepath), "r", encoding="utf-8") as in_f:
                reader = csv.DictReader(in_f)
                for row in reader:
                    text_eng = row.get("text_english", "").strip()
                    text_ara = row.get("text_arabic", "").strip()
                    if not text_eng and not text_ara:
                        continue

                    row_out = {
                        "collection_slug": slug,
                        "collection_name_en": name_en,
                        "collection_name_ar": name_ar,
                        "book_id": row.get("book_id", ""),
                        "book_name_en": row.get("book_name_en", name_en),
                        "book_name_ar": row.get("book_name_ar", name_ar),
                        "chapter_id": row.get("chapter_id", ""),
                        "chapter_name_en": row.get("chapter_name_en", ""),
                        "chapter_name_ar": row.get("chapter_name_ar", ""),
                        "hadith_id": row.get("hadith_id", ""),
                        "hadith_id_in_book": row.get("hadith_id_in_book", ""),
                        "narrator": row.get("narrator", ""),
                        "text_english": row.get("text_english", ""),
                        "text_arabic": row.get("text_arabic", ""),
                        "grading": row.get("grading", ""),
                        "reference": row.get("reference", "")
                    }
                    writer.writerow(row_out)
                    count += 1
            print(f"  Added {count:,} hadiths from {name_en}")
            total_count += count

    print(f"Saved {total_count:,} total hadiths to {OUTPUT_HADITH_CSV}\n")
    return total_count

def build_sqlite_db():
    print(f"Building SQLite database {OUTPUT_DB}...")
    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()

    conn = sqlite3.connect(str(OUTPUT_DB))
    cursor = conn.cursor()

    # 1. Create Hadith Table
    cursor.execute("""
        CREATE TABLE hadiths (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_slug TEXT,
            collection_name_en TEXT,
            collection_name_ar TEXT,
            book_id TEXT,
            book_name_en TEXT,
            book_name_ar TEXT,
            chapter_id TEXT,
            chapter_name_en TEXT,
            chapter_name_ar TEXT,
            hadith_id INTEGER,
            hadith_id_in_book TEXT,
            narrator TEXT,
            text_english TEXT,
            text_arabic TEXT,
            grading TEXT,
            reference TEXT
        )
    """)

    # Index for fast lookup
    cursor.execute("CREATE INDEX idx_hadiths_collection ON hadiths(collection_slug);")
    cursor.execute("CREATE INDEX idx_hadiths_hadith_id ON hadiths(hadith_id);")
    cursor.execute("CREATE INDEX idx_hadiths_grading ON hadiths(grading);")

    # Populate Hadiths
    with open(str(OUTPUT_HADITH_CSV), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        hadith_rows = []
        for r in reader:
            hadith_rows.append((
                r["collection_slug"],
                r["collection_name_en"],
                r["collection_name_ar"],
                r["book_id"],
                r["book_name_en"],
                r["book_name_ar"],
                r["chapter_id"],
                r["chapter_name_en"],
                r["chapter_name_ar"],
                int(r["hadith_id"]) if r["hadith_id"].isdigit() else None,
                r["hadith_id_in_book"],
                r["narrator"],
                r["text_english"],
                r["text_arabic"],
                r["grading"],
                r["reference"]
            ))

    cursor.executemany("""
        INSERT INTO hadiths (
            collection_slug, collection_name_en, collection_name_ar,
            book_id, book_name_en, book_name_ar,
            chapter_id, chapter_name_en, chapter_name_ar,
            hadith_id, hadith_id_in_book, narrator,
            text_english, text_arabic, grading, reference
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, hadith_rows)
    print(f"  Inserted {len(hadith_rows):,} rows into 'hadiths' table.")

    # 2. Create Quran Table
    cursor.execute("""
        CREATE TABLE quran_verses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_number INTEGER,
            verse_number INTEGER,
            verse_key TEXT,
            text_uthmani TEXT,
            translation_resource_id TEXT,
            translation_name TEXT,
            translation_author TEXT,
            translation_text TEXT
        )
    """)

    cursor.execute("CREATE INDEX idx_quran_verse_key ON quran_verses(verse_key);")
    cursor.execute("CREATE INDEX idx_quran_chapter_verse ON quran_verses(chapter_number, verse_number);")
    cursor.execute("CREATE INDEX idx_quran_translation_id ON quran_verses(translation_resource_id);")

    if QURAN_FILE.exists():
        with open(str(QURAN_FILE), "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            quran_rows = []
            for r in reader:
                if r["translation_resource_id"] == "57":
                    continue
                quran_rows.append((
                    int(r["chapter_number"]) if r["chapter_number"].isdigit() else None,
                    int(r["verse_number"]) if r["verse_number"].isdigit() else None,
                    r["verse_key"],
                    r["text_uthmani"],
                    r["translation_resource_id"],
                    r["translation_name"],
                    r["translation_author"],
                    r["translation_text"]
                ))

        cursor.executemany("""
            INSERT INTO quran_verses (
                chapter_number, verse_number, verse_key,
                text_uthmani, translation_resource_id, translation_name,
                translation_author, translation_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, quran_rows)
        print(f"  Inserted {len(quran_rows):,} rows into 'quran_verses' table.")

    # 3. Create Full-Text Search (FTS5) Tables
    cursor.execute("""
        CREATE VIRTUAL TABLE hadiths_fts USING fts5(
            collection_name_en,
            reference,
            narrator,
            text_english,
            text_arabic,
            content='hadiths',
            content_rowid='id'
        );
    """)

    cursor.execute("""
        INSERT INTO hadiths_fts(rowid, collection_name_en, reference, narrator, text_english, text_arabic)
        SELECT id, collection_name_en, reference, narrator, text_english, text_arabic FROM hadiths;
    """)

    cursor.execute("""
        CREATE VIRTUAL TABLE quran_fts USING fts5(
            verse_key,
            text_uthmani,
            translation_name,
            translation_text,
            content='quran_verses',
            content_rowid='id'
        );
    """)

    cursor.execute("""
        INSERT INTO quran_fts(rowid, verse_key, text_uthmani, translation_name, translation_text)
        SELECT id, verse_key, text_uthmani, translation_name, translation_text FROM quran_verses;
    """)

    conn.commit()
    conn.close()
    print(f"Successfully built SQLite database: {OUTPUT_DB}\n")

def main():
    build_hadith_master_csv()
    build_sqlite_db()

if __name__ == "__main__":
    main()
