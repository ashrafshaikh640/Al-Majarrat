"""
Noor AI - Quran Corpus Extractor (Quran Foundation API)
=========================================================
Pulls the full Quran (Arabic Uthmani text + every available English translation)
from the official Quran Foundation Content API and writes it to a CSV.

SETUP
-----
1. Get access: https://api-docs.quran.foundation/request-access/
2. Fill in CLIENT_ID and CLIENT_SECRET below (or set as env vars).
3. pip install requests
4. python extract_quran_corpus.py

OUTPUT
------
quran_corpus.csv with columns:
    chapter_number, verse_number, verse_key, text_uthmani,
    translation_resource_id, translation_name, translation_author, translation_text

Long format: one row per (verse, translation) pair, plus one row per verse
for the Arabic-only text (translation_resource_id = "ARABIC").
This makes it easy to pivot into wide format later with pandas if needed.
"""

import os
import re
import time
import csv
import json
import requests
from requests.adapters import HTTPAdapter
# pyrefly: ignore [missing-import]
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# CONFIG - fill these in once you have access
# ---------------------------------------------------------------------------
CLIENT_ID = os.environ.get("QF_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.environ.get("QF_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")

TOKEN_URL = "https://oauth2.quran.foundation/oauth2/token"
BASE_URL = "https://apis.quran.foundation/content/api/v4"
# NOTE: use "https://prelive-oauth2.quran.foundation/oauth2/token" and
# "https://apis-prelive.quran.foundation/content/api/v4" for the Pre-Production
# (Test) credentials instead of Production. Do not mix prelive and production tokens.

OUTPUT_CSV = "quran_corpus.csv"
CHECKPOINT_FILE = "quran_corpus_progress.json"  # tracks which chapters are done
REQUEST_DELAY = 0.5  # be polite to the API between calls

# A session with automatic retries on connection drops / timeouts / 5xx / 429.
# This is what fixes "ConnectionAbortedError" / "Connection aborted" crashes.
session = requests.Session()
retry_strategy = Retry(
    total=6,
    backoff_factor=2,  # 2s, 4s, 8s, 16s, 32s, 64s between retries
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"],
)
session.mount("https://", HTTPAdapter(max_retries=retry_strategy))
session.mount("http://", HTTPAdapter(max_retries=retry_strategy))


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------
def get_access_token():
    # Quran Foundation requires client credentials via HTTP Basic Auth,
    # NOT as client_id/client_secret fields in the form body.
    resp = session.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "scope": "content",
        },
        auth=(CLIENT_ID, CLIENT_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def api_headers(token):
    # Content API requires BOTH of these on every request (not "Authorization: Bearer").
    return {
        "x-auth-token": token,
        "x-client-id": CLIENT_ID,
    }


# ---------------------------------------------------------------------------
# STEP 1: discover available English translations
# ---------------------------------------------------------------------------
HTML_TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_RE = re.compile(r"<sup[^>]*>.*?</sup>", re.IGNORECASE | re.DOTALL)

# Not a meaning-translation -- Latin-script transliteration of the Arabic.
# Exclude it so the corpus only contains actual translated meanings.
EXCLUDED_TRANSLATION_IDS = {57}


def strip_html(text):
    """Remove footnote markers and any remaining HTML markup for a clean corpus."""
    if not text:
        return text
    text = FOOTNOTE_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    return text.strip()


def get_english_translation_ids(token):
    # NOTE: the "language" query param on this endpoint does NOT actually filter
    # server-side -- it silently returns translations in every language. We must
    # fetch everything and filter client-side on language_name instead.
    resp = session.get(
        f"{BASE_URL}/resources/translations",
        headers=api_headers(token),
    )
    resp.raise_for_status()
    data = resp.json().get("translations", [])
    english_only = [
        t for t in data
        if str(t.get("language_name", "")).strip().lower() == "english"
        and t.get("id") not in EXCLUDED_TRANSLATION_IDS
    ]
    return [
        {"id": t["id"], "name": t.get("name", ""), "author": t.get("author_name", "")}
        for t in english_only
    ]


# ---------------------------------------------------------------------------
# STEP 2: get chapter list (1-114)
# ---------------------------------------------------------------------------
def get_chapters(token):
    resp = session.get(f"{BASE_URL}/chapters", headers=api_headers(token))
    resp.raise_for_status()
    return resp.json()["chapters"]


# ---------------------------------------------------------------------------
# STEP 3: pull verses (Arabic + translations) per chapter
# ---------------------------------------------------------------------------
def get_verses_for_chapter(token, chapter_number, translation_ids):
    translations_param = ",".join(str(i) for i in translation_ids)
    verses = []
    page = 1
    while True:
        resp = session.get(
            f"{BASE_URL}/verses/by_chapter/{chapter_number}",
            timeout=30,
            headers=api_headers(token),
            params={
                "language": "en",
                "words": "false",
                "translations": translations_param,
                "fields": "text_uthmani",
                "per_page": 50,
                "page": page,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        verses.extend(payload["verses"])
        pagination = payload.get("pagination", {})
        if not pagination.get("next_page"):
            break
        page = pagination["next_page"]
        time.sleep(REQUEST_DELAY)
    return verses


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    if CLIENT_ID.startswith("YOUR_") or CLIENT_SECRET.startswith("YOUR_"):
        raise SystemExit(
            "Set QF_CLIENT_ID / QF_CLIENT_SECRET env vars, or edit the constants "
            "at the top of this script, before running."
        )

    print("Authenticating...")
    token = get_access_token()

    print("Fetching English translation list...")
    translations = get_english_translation_ids(token)
    translation_lookup = {t["id"]: t for t in translations}
    print(f"Found {len(translations)} English translations:")
    for t in translations:
        print(f"  [{t['id']}] {t['name']} - {t['author']}")

    print("\nFetching chapter list...")
    chapters = get_chapters(token)
    print(f"Found {len(chapters)} chapters.\n")

    # --- checkpoint/resume: skip chapters already fetched in a prior run ---
    file_exists = os.path.exists(OUTPUT_CSV)
    resume = file_exists and os.path.exists(CHECKPOINT_FILE)
    done_chapters = set()
    if resume:
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            done_chapters = set(json.load(f))
        print(f"Resuming: {len(done_chapters)} chapters already done, skipping them.\n")

    fieldnames = [
        "chapter_number", "verse_number", "verse_key", "text_uthmani",
        "translation_resource_id", "translation_name", "translation_author",
        "translation_text",
    ]
    csv_file = open(OUTPUT_CSV, "a" if resume else "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    if not resume:
        writer.writeheader()

    total_rows = 0
    for ch in chapters:
        ch_num = ch["id"]
        if ch_num in done_chapters:
            continue

        print(f"Fetching Surah {ch_num} ({ch.get('name_simple', '')})...")
        try:
            verses = get_verses_for_chapter(token, ch_num, list(translation_lookup.keys()))
        except requests.exceptions.RequestException as e:
            print(f"  FAILED on Surah {ch_num}: {e}")
            print("  Progress saved. Re-run the script to resume from here.")
            break

        rows = []
        for v in verses:
            verse_key = v["verse_key"]
            verse_num = v["verse_number"]
            arabic_text = strip_html(v.get("text_uthmani", ""))

            # one row for the Arabic text
            rows.append({
                "chapter_number": ch_num,
                "verse_number": verse_num,
                "verse_key": verse_key,
                "text_uthmani": arabic_text,
                "translation_resource_id": "ARABIC",
                "translation_name": "Arabic (Uthmani)",
                "translation_author": "",
                "translation_text": "",
            })

            # one row per translation
            for tr in v.get("translations", []):
                tr_id = tr["resource_id"]
                meta = translation_lookup.get(tr_id, {})
                rows.append({
                    "chapter_number": ch_num,
                    "verse_number": verse_num,
                    "verse_key": verse_key,
                    "text_uthmani": arabic_text,
                    "translation_resource_id": tr_id,
                    "translation_name": meta.get("name", ""),
                    "translation_author": meta.get("author", ""),
                    "translation_text": strip_html(tr.get("text", "")),
                })

        writer.writerows(rows)
        csv_file.flush()
        total_rows += len(rows)

        done_chapters.add(ch_num)
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(done_chapters), f)

        time.sleep(REQUEST_DELAY)

    csv_file.close()

    if len(done_chapters) == len(chapters):
        print(f"\nAll {len(chapters)} chapters done. Wrote {total_rows} new rows this run.")
        print(f"Final CSV: {OUTPUT_CSV}")
        # cleanup checkpoint since the corpus is complete
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
    else:
        print(f"\nStopped early. {len(done_chapters)}/{len(chapters)} chapters done so far.")
        print(f"Wrote {total_rows} new rows this run to {OUTPUT_CSV}.")
        print("Just re-run the script — it will pick up where it left off.")


if __name__ == "__main__":
    main()