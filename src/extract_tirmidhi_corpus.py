import json
import csv
import urllib.request
import os
import re

URL_ENG = "https://raw.githubusercontent.com/fawazahmed0/hadith-api/1/editions/eng-tirmidhi.json"
URL_ARA = "https://raw.githubusercontent.com/fawazahmed0/hadith-api/1/editions/ara-tirmidhi.json"
FILE_ENG = "fawaz_tirmidhi_eng.json"
FILE_ARA = "fawaz_tirmidhi_ara.json"
OUTPUT_CSV = "tirmidhi_corpus.csv"

def strip_html(text):
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text).strip()

def download(url, filename):
    if not os.path.exists(filename):
        print(f"Downloading {filename}...")
        urllib.request.urlretrieve(url, filename)

def main():
    download(URL_ENG, FILE_ENG)
    download(URL_ARA, FILE_ARA)

    with open(FILE_ENG, "r", encoding="utf-8") as f:
        data_eng = json.load(f)
        
    with open(FILE_ARA, "r", encoding="utf-8") as f:
        data_ara = json.load(f)

    # Map Arabic Hadiths by hadithnumber
    ara_hadiths = {h["hadithnumber"]: h for h in data_ara.get("hadiths", [])}
    
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

        for h_eng in data_eng.get("hadiths", []):
            h_num = h_eng.get("hadithnumber")
            h_ara = ara_hadiths.get(h_num, {})
            
            eng_text = h_eng.get("text", "")
            narrator = ""
            if ":" in eng_text:
                first_part = eng_text.split(":")[0]
                if "reported" in first_part or "narrated" in first_part.lower():
                    if len(first_part) < 100:
                        parts = eng_text.split(":", 1)
                        narrator = parts[0].strip()
                        eng_text = parts[1].strip()
            
            ara_text = h_ara.get("text", "")
            
            ref = h_eng.get("reference", {})
            book = ref.get("book", "")
            hadith_in_book = ref.get("hadith", "")

            # Grading extraction
            grades = h_eng.get("grades", [])
            grading_str = ""
            if grades:
                grading_str = ", ".join([f"{g.get('name', '')}: {g.get('grade', '')}" if g.get('name') else g.get('grade', '') for g in grades])

            writer.writerow({
                "book_id": book,
                "book_name_en": data_eng.get("metadata", {}).get("name", "Jami` at-Tirmidhi"),
                "book_name_ar": "جامع الترمذي",
                "chapter_id": "",
                "chapter_name_en": "",
                "chapter_name_ar": "",
                "hadith_id": h_num,
                "hadith_id_in_book": hadith_in_book,
                "narrator": strip_html(narrator),
                "text_english": strip_html(eng_text),
                "text_arabic": strip_html(ara_text),
                "grading": grading_str,  
                "reference": f"Jami` at-Tirmidhi {h_num}"
            })
            count += 1
            
    print(f"Extraction complete! Saved {count} hadiths to {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
