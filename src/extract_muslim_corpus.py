import json
import csv
import urllib.request
import os
import re

URL_ENG = "https://raw.githubusercontent.com/fawazahmed0/hadith-api/1/editions/eng-muslim.json"
URL_ARA = "https://raw.githubusercontent.com/fawazahmed0/hadith-api/1/editions/ara-muslim.json"
FILE_ENG = "fawaz_muslim_eng.json"
FILE_ARA = "fawaz_muslim_ara.json"
OUTPUT_CSV = "muslim_corpus.csv"

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

    # Convert arabic hadiths to a dictionary mapped by hadithnumber for easy lookup
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
            
            # Extract narrator from English text if possible
            eng_text = h_eng.get("text", "")
            narrator = ""
            # Often hadiths begin with something like "Abu Huraira reported:" or "It was narrated that X said:"
            if "reported" in eng_text.split(":")[0] or "narrated" in eng_text.split(":")[0].lower():
                if ":" in eng_text:
                    parts = eng_text.split(":", 1)
                    if len(parts[0]) < 100: # heuristic to ensure it's not a sentence with a colon later
                        narrator = parts[0].strip()
                        eng_text = parts[1].strip()
            
            ara_text = h_ara.get("text", "")
            
            ref = h_eng.get("reference", {})
            book = ref.get("book", "")
            hadith_in_book = ref.get("hadith", "")

            text_en_clean = strip_html(eng_text)
            text_ar_clean = strip_html(ara_text)

            # Skip hadiths with no text content in either language
            if not text_en_clean and not text_ar_clean:
                continue

            writer.writerow({
                "book_id": book,
                "book_name_en": data_eng.get("metadata", {}).get("name", "Sahih Muslim"),
                "book_name_ar": "صحيح مسلم",
                "chapter_id": "", # not explicitly mapped in this structure
                "chapter_name_en": "",
                "chapter_name_ar": "",
                "hadith_id": h_num,
                "hadith_id_in_book": hadith_in_book,
                "narrator": strip_html(narrator),
                "text_english": text_en_clean,
                "text_arabic": text_ar_clean,
                "grading": "Sahih",  
                "reference": f"Sahih Muslim {h_num}"
            })
            count += 1
            
    print(f"Extraction complete! Saved {count} hadiths to {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
