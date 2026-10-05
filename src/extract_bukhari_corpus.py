import json
import csv
import re
import urllib.request
import os

URL = "https://raw.githubusercontent.com/AhmedBaset/hadith-json/v1.2.0/db/by_book/the_9_books/bukhari.json"
RAW_FILE = "bukhari_raw.json"
OUTPUT_CSV = "bukhari_corpus.csv"

def strip_html(text):
    if not text:
        return ""
    # Remove HTML tags just in case
    return re.sub(r'<[^>]+>', '', text).strip()

def main():
    if not os.path.exists(RAW_FILE):
        print("Downloading JSON data...")
        urllib.request.urlretrieve(URL, RAW_FILE)
        print("Download complete.")

    print(f"Loading data from {RAW_FILE}...")
    with open(RAW_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    book_name_en = data.get("metadata", {}).get("english", {}).get("title", "Sahih al-Bukhari")
    book_name_ar = data.get("metadata", {}).get("arabic", {}).get("title", "صحيح البخاري")

    chapters = {ch["id"]: ch for ch in data.get("chapters", [])}

    fieldnames = [
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

    print(f"Writing to {OUTPUT_CSV}...")
    count = 0
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

        for h in data.get("hadiths", []):
            chapter = chapters.get(h.get("chapterId"), {})
            
            english_data = h.get("english", {})
            narrator = english_data.get("narrator", "")
            text_english = english_data.get("text", "")
            
            writer.writerow({
                "book_id": h.get("bookId", ""),
                "book_name_en": book_name_en,
                "book_name_ar": book_name_ar,
                "chapter_id": h.get("chapterId", ""),
                "chapter_name_en": chapter.get("english", ""),
                "chapter_name_ar": chapter.get("arabic", ""),
                "hadith_id": h.get("id", ""),
                "hadith_id_in_book": h.get("idInBook", ""),
                "narrator": strip_html(narrator),
                "text_english": strip_html(text_english),
                "text_arabic": strip_html(h.get("arabic", "")),
                "grading": "Sahih",  # All narrations in this collection are considered Sahih
                "reference": f"Sahih al-Bukhari {h.get('idInBook', '')}"
            })
            count += 1
            
    print(f"Extraction complete! Saved {count} hadiths to {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
