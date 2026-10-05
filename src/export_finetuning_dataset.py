import sqlite3
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from project_config import BASE_DIR, DB_PATH, ALPACA_DATASET, CHAT_DATASET

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

OUTPUT_ALPACA = ALPACA_DATASET
OUTPUT_CHAT = CHAT_DATASET

def export_dataset():
    if not DB_PATH.exists():
        print(f"Error: Database file '{DB_PATH}' not found. Run create_master_corpus.py first.")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    print(f"Reading records from {DB_PATH}...")

    # 1. Fetch Hadiths
    cursor.execute("""
        SELECT collection_name_en, collection_name_ar, reference, narrator, text_english, text_arabic, grading
        FROM hadiths
    """)
    hadiths = cursor.fetchall()
    print(f"Loaded {len(hadiths):,} Hadith entries.")

    # 2. Fetch Quran Verses
    cursor.execute("""
        SELECT q.chapter_number, q.verse_number, q.verse_key, q.text_uthmani, q.translation_name, q.translation_text
        FROM quran_verses q
        WHERE q.id = (
            SELECT q2.id
            FROM quran_verses q2
            WHERE q2.verse_key = q.verse_key
              AND q2.translation_text != ''
              AND q2.translation_resource_id NOT IN ('ARABIC', '57')
            ORDER BY CASE WHEN q2.translation_resource_id = '20' THEN 0 ELSE 1 END, q2.id
            LIMIT 1
        )
        ORDER BY q.chapter_number, q.verse_number
    """)
    verses = cursor.fetchall()
    print(f"Loaded {len(verses):,} Quran verse entries.")

    alpaca_count = 0
    chat_count = 0

    with open(str(OUTPUT_ALPACA), "w", encoding="utf-8") as f_alpaca, \
         open(str(OUTPUT_CHAT), "w", encoding="utf-8") as f_chat:

        system_prompt = (
            "You are an authentic Islamic Knowledge AI Assistant. "
            "Provide accurate answers grounded in authentic Quran verses and Hadith references."
        )

        # Export Hadiths
        for h in hadiths:
            name_en, name_ar, ref, narrator, text_en, text_ar, grading = h
            
            if not text_en and not text_ar:
                continue

            instruction = f"Provide the authentic Hadith reference for '{ref}' from {name_en}."
            
            output_parts = [f"Reference: {ref}"]
            if narrator:
                output_parts.append(f"Narrator: {narrator}")
            if grading:
                output_parts.append(f"Grading: {grading}")
            if text_en:
                output_parts.append(f"English Text: {text_en}")
            if text_ar:
                output_parts.append(f"Arabic Text: {text_ar}")
            
            output_text = "\n".join(output_parts)

            # Alpaca sample
            alpaca_sample = {
                "instruction": instruction,
                "input": f"Collection: {name_en} ({name_ar}), Reference: {ref}",
                "output": output_text
            }
            f_alpaca.write(json.dumps(alpaca_sample, ensure_ascii=False) + "\n")
            alpaca_count += 1

            # Chat sample
            chat_sample = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"What is the text of Hadith {ref} in {name_en}?"},
                    {"role": "assistant", "content": output_text}
                ]
            }
            f_chat.write(json.dumps(chat_sample, ensure_ascii=False) + "\n")
            chat_count += 1

        # Export Quran Verses
        for v in verses:
            ch_num, v_num, v_key, text_uthmani, t_name, t_text = v
            
            instruction = f"Provide the Arabic text and English translation for Quran Surah {v_key}."
            input_text = f"Surah {ch_num}, Verse {v_num} ({t_name})"
            output_text = f"Surah {v_key}\nArabic (Uthmani): {text_uthmani}\nTranslation ({t_name}): {t_text}"

            alpaca_sample = {
                "instruction": instruction,
                "input": input_text,
                "output": output_text
            }
            f_alpaca.write(json.dumps(alpaca_sample, ensure_ascii=False) + "\n")
            alpaca_count += 1

            chat_sample = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Show me Quran verse {v_key} with translation."},
                    {"role": "assistant", "content": output_text}
                ]
            }
            f_chat.write(json.dumps(chat_sample, ensure_ascii=False) + "\n")
            chat_count += 1

    print(f"\nFine-Tuning Dataset Export Complete!")
    print(f"Saved {alpaca_count:,} records to '{OUTPUT_ALPACA}' (Alpaca JSONL)")
    print(f"Saved {chat_count:,} records to '{OUTPUT_CHAT}' (ChatML JSONL)")

if __name__ == "__main__":
    export_dataset()
