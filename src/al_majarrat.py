import time
import sqlite3
import json
import urllib.request
import urllib.error
import argparse
import sys
import os
import math
import re
import difflib

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from project_config import (
    DB_PATH,
    DEFAULT_LOCAL_ENDPOINT,
    DEFAULT_MODEL,
    EMBEDDING_MODEL,
    OLLAMA_EMBED_API,
    PREFERRED_QURAN_TRANSLATION_ID,
)

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

def get_preferred_quran_verse_id(cursor, verse_key):
        cursor.execute("""
                SELECT id
                FROM quran_verses
                WHERE verse_key = ?
                    AND translation_text != ''
                    AND translation_resource_id NOT IN ('ARABIC', '57')
                ORDER BY CASE WHEN translation_resource_id = ? THEN 0 ELSE 1 END, id
                LIMIT 1
        """, (verse_key, PREFERRED_QURAN_TRANSLATION_ID))
        row = cursor.fetchone()
        return row[0] if row else None

def validate_runtime_requirements():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database '{DB_PATH}' not found. Run python create_master_corpus.py first.")

    required_tables = {"hadiths", "quran_verses", "hadiths_fts", "quran_fts"}
    with sqlite3.connect(str(DB_PATH), timeout=5.0) as conn:
        existing = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        }
        missing = sorted(required_tables - existing)
        if missing:
            raise RuntimeError(f"Database schema missing required tables: {', '.join(missing)}")


def get_db_connection():
    if not DB_PATH.exists():
        print(f"Error: Database '{DB_PATH}' not found.")
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except sqlite3.OperationalError:
        pass
    return conn

def cosine_similarity(v1, v2):
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    magnitude1 = math.sqrt(sum(a * a for a in v1))
    magnitude2 = math.sqrt(sum(b * b for b in v2))
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    return dot_product / (magnitude1 * magnitude2)

def get_query_embedding(query_text):
    payload = {
        "model": EMBEDDING_MODEL,
        "prompt": query_text
    }
    req = urllib.request.Request(OLLAMA_EMBED_API, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=1.5) as response:
            res = json.loads(response.read().decode('utf-8'))
            return res.get("embedding", [])
    except Exception:
        # Instant fallback to FTS5 lexical matching if embedding server takes > 1.5s
        return None

STOP_WORDS = {"what", "does", "islam", "say", "about", "is", "the", "in", "a", "an", "tell", "me", "how", "why", "who", "which", "where", "can", "you", "hadith", "quran", "verse"}
SEARCH_SYNONYMS = {
    "zakaat": ("zakat", "zakah"),
    "zakat": ("zakaat", "zakah"),
    "zakah": ("zakat", "zakaat"),
}
_SEARCH_TERM_FREQUENCIES = None
_SEARCH_TERMS = None

def get_search_vocabulary(cursor):
    global _SEARCH_TERM_FREQUENCIES, _SEARCH_TERMS
    if _SEARCH_TERM_FREQUENCIES is not None:
        return _SEARCH_TERM_FREQUENCIES

    frequencies = {}
    for vocab_table, fts_table in (("hadith_search_vocab", "hadiths_fts"), ("quran_search_vocab", "quran_fts")):
        try:
            cursor.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS temp.{vocab_table} USING fts5vocab(main, {fts_table}, 'row')")
            cursor.execute(f"SELECT term, doc FROM temp.{vocab_table}")
            for term, document_count in cursor:
                frequencies[term] = frequencies.get(term, 0) + document_count
        except sqlite3.Error:
            return None

    _SEARCH_TERM_FREQUENCIES = frequencies
    _SEARCH_TERMS = sorted(frequencies)
    return _SEARCH_TERM_FREQUENCIES

def get_fuzzy_search_term(word):
    if _SEARCH_TERMS is None or word in _SEARCH_TERM_FREQUENCIES or len(word) < 4:
        return None

    max_distance = 1 if len(word) < 8 else 2
    candidates = difflib.get_close_matches(word, _SEARCH_TERMS, n=12, cutoff=0.68)
    ranked = []
    for candidate in candidates:
        if abs(len(word) - len(candidate)) > max_distance:
            continue
        distance = edit_distance_with_transposition(word, candidate, max_distance)
        if distance <= max_distance:
            ranked.append((distance, -_SEARCH_TERM_FREQUENCIES[candidate], candidate))
    return min(ranked)[2] if ranked else None

def edit_distance_with_transposition(left, right, cutoff):
    if abs(len(left) - len(right)) > cutoff:
        return cutoff + 1

    previous_previous = None
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        row_minimum = left_index
        for right_index, right_char in enumerate(right, 1):
            cost = 0 if left_char == right_char else 1
            distance = min(
                previous[right_index] + 1,
                current[right_index - 1] + 1,
                previous[right_index - 1] + cost,
            )
            if (
                previous_previous is not None
                and left_index > 1
                and right_index > 1
                and left_char == right[right_index - 2]
                and left[left_index - 2] == right_char
            ):
                distance = min(distance, previous_previous[right_index - 2] + 1)
            current.append(distance)
            row_minimum = min(row_minimum, distance)
        if row_minimum > cutoff:
            return cutoff + 1
        previous_previous, previous = previous, current
    return previous[-1]

def clean_search_query(user_query, cursor=None):
    # Basic typo fix for common words
    typos = {"smilling": "smile", "smill": "smile", "praye": "prayer", "fastin": "fasting"}
    if cursor:
        get_search_vocabulary(cursor)
    
    words = re.findall(r'\w+', user_query.lower())
    terms = []
    for w in words:
        if w in typos:
            w = typos[w]
        if w not in STOP_WORDS and len(w) > 2:
            fuzzy_term = get_fuzzy_search_term(w) if cursor else None
            variants = (w, *SEARCH_SYNONYMS.get(w, ()), *((fuzzy_term,) if fuzzy_term else ()))
            for variant in variants:
                terms.append(variant)
                if len(variant) >= 4:
                    terms.append(f"{variant[:-1]}*") # Wildcard search for stemming
                    terms.append(f"{variant}*")

    if not terms:
        return user_query.strip()
    return " OR ".join(dict.fromkeys(terms))

SURAH_NAME_MAP = {
    # 1 - 10
    "fatiha": 1, "al-fatiha": 1, "opening": 1,
    "baqarah": 2, "al-baqarah": 2, "cow": 2,
    "imran": 3, "ali-imran": 3, "al-imran": 3, "family-of-imran": 3,
    "nisa": 4, "an-nisa": 4, "women": 4,
    "maidah": 5, "al-maidah": 5, "table-spread": 5,
    "anam": 6, "al-anam": 6, "cattle": 6,
    "araf": 7, "al-araf": 7, "heights": 7,
    "anfal": 8, "al-anfal": 8, "spoils-of-war": 8,
    "tawbah": 9, "at-tawbah": 9, "repentance": 9,
    "yunus": 10, "jonah": 10,

    # 11 - 20
    "hud": 11,
    "yusuf": 12, "joseph": 12,
    "rad": 13, "ar-rad": 13, "thunder": 13,
    "ibrahim": 14, "abraham": 14,
    "hijr": 15, "al-hijr": 15,
    "nahl": 16, "an-nahl": 16, "bee": 16,
    "isra": 17, "al-isra": 17, "night-journey": 17,
    "kahf": 18, "al-kahf": 18, "cave": 18,
    "maryam": 19, "mary": 19,
    "taha": 20, "ta-ha": 20,

    # 21 - 30
    "anbiya": 21, "al-anbiya": 21, "prophets": 21,
    "hajj": 22, "al-hajj": 22, "pilgrimage": 22,
    "muminun": 23, "al-muminun": 23, "believers": 23,
    "nur": 24, "an-nur": 24, "light": 24,
    "furqan": 25, "al-furqan": 25, "criterion": 25,
    "shuara": 26, "ash-shuara": 26, "poets": 26,
    "naml": 27, "an-naml": 27, "ant": 27,
    "qasas": 28, "al-qasas": 28, "stories": 28,
    "ankabut": 29, "al-ankabut": 29, "spider": 29,
    "rum": 30, "ar-rum": 30, "romans": 30,

    # 31 - 40
    "luqman": 31,
    "sajdah": 32, "as-sajdah": 32, "prostration": 32,
    "ahzab": 33, "al-ahzab": 33,
    "saba": 34, "sheba": 34,
    "fatir": 35, "originator": 35,
    "yaseen": 36, "yasin": 36, "ya-sin": 36,
    "saffat": 37, "as-saffat": 37,
    "sad": 38,
    "zumar": 39, "az-zumar": 39, "troops": 39,
    "ghafir": 40, "mumin-surah": 40, "forgiver": 40,

    # 41 - 50
    "fussilat": 41,
    "shura": 42, "ash-shura": 42, "consultation": 42,
    "zukhruf": 43, "az-zukhruf": 43, "ornaments": 43,
    "dukhan": 44, "ad-dukhan": 44, "smoke": 44,
    "jathiyah": 45, "al-jathiyah": 45,
    "ahqaf": 46, "al-ahqaf": 46,
    "muhammad": 47,
    "fath": 48, "al-fath": 48, "victory": 48,
    "hujurat": 49, "al-hujurat": 49, "rooms": 49,
    "qaf": 50,

    # 51 - 60
    "dhariyat": 51, "adh-dhariyat": 51,
    "tur": 52, "at-tur": 52, "mount": 52,
    "najm": 53, "an-najm": 53, "star": 53,
    "qamar": 54, "al-qamar": 54, "moon": 54,
    "rahman": 55, "ar-rahman": 55, "beneficent": 55,
    "waqiah": 56, "al-waqiah": 56, "inevitable": 56,
    "hadid": 57, "al-hadid": 57, "iron": 57,
    "mujadila": 58, "al-mujadila": 58,
    "hashr": 59, "al-hashr": 59, "exile": 59,
    "mumtahanah": 60, "al-mumtahanah": 60,

    # 61 - 70
    "saff": 61, "as-saff": 61, "ranks": 61,
    "jumuah": 62, "al-jumuah": 62, "friday": 62,
    "munafiqun": 63, "al-munafiqun": 63, "hypocrites": 63,
    "taghabun": 64, "at-taghabun": 64,
    "talaq": 65, "at-talaq": 65, "divorce": 65,
    "tahrim": 66, "at-tahrim": 66, "prohibition": 66,
    "mulk": 67, "al-mulk": 67, "dominion": 67,
    "qalam": 68, "al-qalam": 68, "pen": 68,
    "haqqah": 69, "al-haqqah": 69,
    "maarij": 70, "al-maarij": 70,

    # 71 - 80
    "nuh": 71, "noah": 71,
    "jinn": 72, "al-jinn": 72,
    "muzzammil": 73, "al-muzzammil": 73,
    "muddaththir": 74, "al-muddaththir": 74,
    "qiyamah": 75, "al-qiyamah": 75, "resurrection": 75,
    "insan": 76, "al-insan": 76, "dahr": 76,
    "mursalat": 77, "al-mursalat": 77,
    "naba": 78, "an-naba": 78, "tidings": 78,
    "naziat": 79, "an-naziat": 79,
    "abasa": 80,

    # 81 - 90
    "takwir": 81, "at-takwir": 81,
    "infitar": 82, "al-infitar": 82,
    "mutaffifin": 83, "al-mutaffifin": 83,
    "inshiqaq": 84, "al-inshiqaq": 84,
    "buruj": 85, "al-buruj": 85,
    "tariq": 86, "at-tariq": 86, "morning-star": 86,
    "ala": 87, "al-ala": 87,
    "ghashiyah": 88, "al-ghashiyah": 88,
    "fajr": 89, "al-fajr": 89, "dawn": 89,
    "balad": 90, "al-balad": 90, "city": 90,

    # 91 - 100
    "shams": 91, "ash-shams": 91, "sun": 91,
    "layl": 92, "al-layl": 92, "night": 92,
    "duha": 93, "ad-duha": 93,
    "sharh": 94, "ash-sharh": 94, "inshirah": 94,
    "tin": 95, "at-tin": 95, "fig": 95,
    "alaq": 96, "al-alaq": 96, "clot": 96,
    "qadr": 97, "al-qadr": 97,
    "bayyinah": 98, "al-bayyinah": 98,
    "zilzal": 99, "az-zilzal": 99, "zalzalah": 99, "earthquake": 99,
    "adiyat": 100, "al-adiyat": 100,

    # 101 - 114
    "qariah": 101, "al-qariah": 101,
    "takathur": 102, "at-takathur": 102,
    "asr": 103, "al-asr": 103,
    "humazah": 104, "al-humazah": 104,
    "fil": 105, "al-fil": 105, "elephant": 105,
    "quraish": 106, "quraysh": 106,
    "maun": 107, "al-maun": 107,
    "kawthar": 108, "al-kawthar": 108, "kauthar": 108,
    "kafirun": 109, "al-kafirun": 109,
    "nasr": 110, "an-nasr": 110,
    "masad": 111, "al-masad": 111, "lahab": 111,
    "ikhlas": 112, "al-ikhlas": 112, "purity": 112,
    "falaq": 113, "al-falaq": 113, "daybreak": 113,
    "nas": 114, "an-nas": 114, "naas": 114, "an-naas": 114, "mankind": 114
}

def retrieve_hybrid_context(user_query, max_quran=6, max_hadith=5):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Get Query Vector Embedding
    query_vec = get_query_embedding(user_query)

    # ------------------- QURAN HYBRID RETRIEVAL -------------------
    # A. Direct Verse Key / Surah Pattern Match (e.g. 2:255 or Surah 2 verse 60)
    direct_quran_ids = []
    
    # Check for chapter:verse format like 2:255 or "Surah 2 verse 60"
    verse_key_match = re.search(r'\b(\d{1,3}):(\d{1,3})\b', user_query)
    surah_verse_text_match = re.search(r'\bsurah\s*(\d{1,3})\s*verse\s*(\d{1,3})\b', user_query.lower())
    
    if verse_key_match:
        vk_pattern = f"{verse_key_match.group(1)}:{verse_key_match.group(2)}"
        verse_id = get_preferred_quran_verse_id(cursor, vk_pattern)
        direct_quran_ids = [verse_id] if verse_id is not None else []
    elif surah_verse_text_match:
        vk_pattern = f"{surah_verse_text_match.group(1)}:{surah_verse_text_match.group(2)}"
        verse_id = get_preferred_quran_verse_id(cursor, vk_pattern)
        direct_quran_ids = [verse_id] if verse_id is not None else []

    # Check for Surah number format (e.g. "surah 114") or Surah name (e.g. "surah an-nas", "surah nas")
    if not direct_quran_ids:
        s_num = None
        surah_num_match = re.search(r'\bsurah\s*(\d{1,3})\b', user_query.lower())
        if surah_num_match:
            s_num = int(surah_num_match.group(1))
        else:
            query_tokens = re.findall(r'[a-z\-]+', user_query.lower())
            for t in query_tokens:
                clean_t = t.replace("-", "")
                if t in SURAH_NAME_MAP:
                    s_num = SURAH_NAME_MAP[t]
                    break
                elif clean_t in SURAH_NAME_MAP:
                    s_num = SURAH_NAME_MAP[clean_t]
                    break
        
        if s_num:
            # Fetch all verses of the requested Surah (up to 300) so no verses or core contexts are missed
            cursor.execute("SELECT verse_key FROM quran_verses WHERE chapter_number = ? GROUP BY verse_number ORDER BY verse_number LIMIT 300", (s_num,))
            for (verse_key,) in cursor.fetchall():
                verse_id = get_preferred_quran_verse_id(cursor, verse_key)
                if verse_id is not None:
                    direct_quran_ids.append(verse_id)

    # B. FTS5 Lexical Search for Quran
    fts_term = clean_search_query(user_query, cursor)
    fts_quran_ids = list(direct_quran_ids)
    if not direct_quran_ids:
        try:
            cursor.execute("""
                SELECT q.verse_key
                FROM quran_verses q
                JOIN quran_fts fts ON q.id = fts.rowid
                WHERE quran_fts MATCH ?
                GROUP BY q.verse_key
                ORDER BY MIN(rank)
                LIMIT 15
            """, (fts_term,))
            for (verse_key,) in cursor.fetchall():
                verse_id = get_preferred_quran_verse_id(cursor, verse_key)
                if verse_id is not None and verse_id not in fts_quran_ids:
                    fts_quran_ids.append(verse_id)
        except Exception:
            pass

    # B. Vector Cosine Search
    vector_quran_scores = {}
    if query_vec:
        cursor.execute("""
            SELECT q.id, v.embedding_json
            FROM quran_vector_index v
            JOIN quran_verses q ON q.id = (
                SELECT q2.id
                FROM quran_verses q2
                WHERE q2.verse_key = v.verse_key
                  AND q2.translation_text != ''
                  AND q2.translation_resource_id NOT IN ('ARABIC', '57')
                ORDER BY CASE WHEN q2.translation_resource_id = ? THEN 0 ELSE 1 END, q2.id
                LIMIT 1
            )
        """, (PREFERRED_QURAN_TRANSLATION_ID,))
        for q_id, emb_str in cursor:
            emb = json.loads(emb_str)
            score = cosine_similarity(query_vec, emb)
            vector_quran_scores[q_id] = score

    # Reciprocal Rank Fusion (RRF) for Quran
    rrf_quran = {}
    for rank, q_id in enumerate(fts_quran_ids):
        rrf_quran[q_id] = rrf_quran.get(q_id, 0) + (1.0 / (60 + rank + 1))

    sorted_vector_quran = sorted(vector_quran_scores.items(), key=lambda x: x[1], reverse=True)[:15]
    for rank, (q_id, v_score) in enumerate(sorted_vector_quran):
        rrf_quran[q_id] = rrf_quran.get(q_id, 0) + (1.0 / (60 + rank + 1))

    if direct_quran_ids:
        final_quran_ids = direct_quran_ids[:max_quran]
    else:
        final_quran_ids = [q_id for q_id, _ in sorted(rrf_quran.items(), key=lambda x: x[1], reverse=True)[:max_quran]]
    
    quran_context = []
    if final_quran_ids:
        placeholders = ",".join("?" * len(final_quran_ids))
        cursor.execute(f"SELECT verse_key, text_uthmani, translation_name, translation_text FROM quran_verses WHERE id IN ({placeholders})", final_quran_ids)
        for vk, ar, tn, en in cursor.fetchall():
            quran_context.append(f"• [Surah {vk}] (Translation: {tn})\n  Arabic: {ar}\n  English: {en}")

    # ------------------- HADITH HYBRID RETRIEVAL -------------------
    # A. FTS5 BM25 Relevance Search (Searches across all 34,157 Hadiths by relevance rank)
    fts_hadith_ids = []
    try:
        cursor.execute("SELECT h.id FROM hadiths h JOIN hadiths_fts fts ON h.id = fts.rowid WHERE hadiths_fts MATCH ? ORDER BY rank LIMIT 25", (fts_term,))
        fts_hadith_ids = [r[0] for r in cursor.fetchall()]
    except Exception:
        pass

    # Fallback keyword match if FTS returns fewer than max_hadith
    if len(fts_hadith_ids) < max_hadith:
        query_words = [w for w in re.findall(r'\w+', user_query.lower()) if w not in STOP_WORDS and len(w) > 2]
        for qw in query_words:
            if qw in ["smilling", "smill"]:
                qw = "smile"
            try:
                cursor.execute("SELECT id FROM hadiths WHERE text_english LIKE ? LIMIT 10", (f"%{qw}%",))
                for r in cursor.fetchall():
                    if r[0] not in fts_hadith_ids:
                        fts_hadith_ids.append(r[0])
            except Exception:
                pass

    # B. Vector Cosine Search
    vector_hadith_scores = {}
    if query_vec:
        cursor.execute("SELECT h.id, v.embedding_json FROM hadiths h JOIN hadith_vector_index v ON h.id = v.hadith_db_id")
        for h_id, emb_str in cursor:
            emb = json.loads(emb_str)
            score = cosine_similarity(query_vec, emb)
            vector_hadith_scores[h_id] = score

    # RRF Fusion for Hadiths
    rrf_hadith = {}
    for rank, h_id in enumerate(fts_hadith_ids):
        rrf_hadith[h_id] = rrf_hadith.get(h_id, 0) + (1.0 / (60 + rank + 1))

    sorted_vector_hadith = sorted(vector_hadith_scores.items(), key=lambda x: x[1], reverse=True)[:20]
    for rank, (h_id, v_score) in enumerate(sorted_vector_hadith):
        rrf_hadith[h_id] = rrf_hadith.get(h_id, 0) + (1.0 / (60 + rank + 1))

    final_hadith_ids = [h_id for h_id, _ in sorted(rrf_hadith.items(), key=lambda x: x[1], reverse=True)[:max_hadith]]

    hadith_context = []
    if final_hadith_ids:
        placeholders = ",".join("?" * len(final_hadith_ids))
        cursor.execute(f"SELECT reference, collection_name_en, narrator, text_english, grading FROM hadiths WHERE id IN ({placeholders})", final_hadith_ids)
        for ref, coll, narrator, en, grading in cursor.fetchall():
            narrator_str = f" ({narrator})" if narrator else ""
            grading_str = f" [Grading: {grading}]" if grading else ""
            hadith_context.append(f"• [{ref}] {coll}{narrator_str}{grading_str}\n  English: {en}")

    return quran_context, hadith_context

def build_prompt(user_query, quran_context, hadith_context):
    system_prompt = (
        "You are an authentic Islamic Knowledge AI Assistant powered by Project Al-Majarrat.\n"
        "Your duty is to answer the user's question accurately using ONLY the retrieved authentic Quran verses and Hadiths provided below.\n"
        "MANDATORY RULES:\n"
        "1. LANGUAGE: Always write your full response in ENGLISH. Always include the English translation text for every Hadith or Quranic verse cited.\n"
        "2. CITATIONS: For EVERY point, quote, or claim in your response, you MUST include the exact bracketed reference tag (e.g., [Sahih al-Bukhari 6114] or [Surah 114:1]) directly from the provided context.\n"
        "3. SURAH EXPLANATIONS: Explain only the verses included in the retrieved context. State when the context is a selection; never imply that every verse is listed unless every verse is present.\n"
        "4. NO FABRICATION: Do NOT invent, fabricate, or paraphrase unverified Hadiths or verses.\n"
        "5. If no relevant context is provided below, state clearly that no direct references were found in the database for this query."
    )

    context_str = "=== RETRIEVED GROUNDING CONTEXT FROM AL-MAJARRAT DATABASE ===\n\n"
    
    if quran_context:
        context_str += "--- QURAN VERSES ---\n" + "\n\n".join(quran_context) + "\n\n"
    else:
        context_str += "--- QURAN VERSES ---\nNo matching Quran verses found for this query.\n\n"

    if hadith_context:
        context_str += "--- HADITH PASSAGES ---\n" + "\n\n".join(hadith_context) + "\n\n"
    else:
        context_str += "--- HADITH PASSAGES ---\nNo matching Hadith passages found for this query.\n\n"

    user_message = f"{context_str}=== USER QUESTION ===\n{user_query}\n\nRemember to write your answer in English and explicitly cite the bracketed references (e.g., [Sahih al-Bukhari ...]) for every point."
    
    return system_prompt, user_message

def query_local_llm(system_prompt, user_message, endpoint=DEFAULT_LOCAL_ENDPOINT, model=DEFAULT_MODEL):
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.3,
        "max_tokens": 1024
    }

    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            choices = res_data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return "No response content generated by local LLM."
    except urllib.error.URLError as e:
        return f"LOCAL_LLM_OFFLINE: Could not connect to Local LLM at '{endpoint}'. Error: {e.reason}"
    except Exception as e:
        return f"LOCAL_LLM_ERROR: {str(e)}"

def process_rag_query(user_query, endpoint=DEFAULT_LOCAL_ENDPOINT, model=DEFAULT_MODEL, verbose=True):
    validate_runtime_requirements()
    if verbose:
        print(f"\n[Step 1/2] Searching database via FTS5 + Vectors for: '{user_query}'...")

    quran_ctx, hadith_ctx = retrieve_hybrid_context(user_query)

    if verbose:
        print(f"[Step 1/2] Found {len(quran_ctx)} Quran verses and {len(hadith_ctx)} Hadiths.")
    
    system_prompt, user_message = build_prompt(user_query, quran_ctx, hadith_ctx)

    if verbose:
        print(f"[Step 2/2] Generating AI answer via {model} (GPU)... Please wait a few seconds...\n")

    response = query_local_llm(system_prompt, user_message, endpoint=endpoint, model=model)
    return response, quran_ctx, hadith_ctx

def main():
    parser = argparse.ArgumentParser(description="Al-Majarrat Hybrid AI RAG Engine (FTS5 + Vector Embeddings)")
    parser.add_argument("-a", "--ask", type=str, help="Ask a natural language question")
    parser.add_argument("-t", "--test-retrieval", type=str, help="Test Hybrid retrieval without querying local LLM")
    parser.add_argument("-e", "--endpoint", type=str, default=DEFAULT_LOCAL_ENDPOINT, help=f"Local LLM API endpoint URL")
    parser.add_argument("-m", "--model", type=str, default=DEFAULT_MODEL, help=f"Local LLM model name")

    args = parser.parse_args()

    if args.test_retrieval:
        query = args.test_retrieval
        print(f"=== TESTING HYBRID RETRIEVAL FOR: '{query}' ===")
        quran_ctx, hadith_ctx = retrieve_hybrid_context(query)
        sys_p, user_m = build_prompt(query, quran_ctx, hadith_ctx)
        print("\n--- GROUNDED USER MESSAGE ---")
        print(user_m)
        return

    if args.ask:
        response, quran_ctx, hadith_ctx = process_rag_query(args.ask, endpoint=args.endpoint, model=args.model)
        
        if "LOCAL_LLM_OFFLINE" in response or "LOCAL_LLM_ERROR" in response:
            print(f"\n⚠️  {response}\n")
            print("=== RETRIEVED GROUNDING CONTEXT ===")
            for q in quran_ctx:
                print(q)
            for h in hadith_ctx:
                print(h)
        else:
            print("=== AI RESPONSE (HYBRID GROUNDED) ===")
            print(response)
        return

    # Interactive Loop Mode
    print("==========================================================")
    print("   PROJECT AL-MAJARRAT - HYBRID AI RAG ENGINE (FTS5 + VECTORS) ")
    print("==========================================================")
    print(f"Embedding Model:   {EMBEDDING_MODEL}")
    print(f"Local LLM Model:   {DEFAULT_MODEL}")
    print("Type your questions naturally. Type 'exit' to quit.\n")

    while True:
        try:
            time.sleep(0.1)
            sys.stdout.flush()
            user_input = input("\nHybrid Al-Majarrat AI> ").strip()
            if not user_input:
                continue
            
            # Exact command match for exit/quit
            if user_input.lower() in ["exit", "quit", "q!", "bye", "/exit", "/quit"]:
                print("\nGoodbye!")
                break

            response, quran_ctx, hadith_ctx = process_rag_query(user_input, endpoint=args.endpoint, model=args.model)

            if "LOCAL_LLM_OFFLINE" in response or "LOCAL_LLM_ERROR" in response:
                print(f"\n⚠️  {response}\n")
                print("=== RETRIEVED GROUNDED CONTEXT ===")
                for q in quran_ctx:
                    print(q)
                for h in hadith_ctx:
                    print(h)
                print()
            else:
                print("\n=== AI RESPONSE ===")
                print(response.strip())
                print("\n" + "="*60)
            
            sys.stdout.flush()

        except KeyboardInterrupt:
            print("\nExiting RAG Engine...")
            break
        except Exception as e:
            print(f"Error: {e}\n")

if __name__ == "__main__":
    main()
