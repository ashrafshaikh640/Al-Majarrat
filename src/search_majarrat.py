import sqlite3
import argparse
import sys
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from project_config import DB_PATH, PREFERRED_QURAN_TRANSLATION_ID

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

def get_connection():
    if not DB_PATH.exists():
        print(f"Error: Database file '{DB_PATH}' not found. Please run create_master_corpus.py first.")
        sys.exit(1)
    return sqlite3.connect(str(DB_PATH))

def format_hadith(row):
    (hid, slug, name_en, name_ar, book_id, book_en, book_ar, 
     chap_id, chap_en, chap_ar, hadith_id, hadith_in_book, 
     narrator, text_en, text_ar, grading, reference) = row

    header = f"[{reference}] {name_en} ({name_ar})"
    divider = "-" * len(header)
    output = [header, divider]
    
    if narrator:
        output.append(f"Narrator: {narrator}")
    if grading:
        output.append(f"Grading: {grading}")
    if text_en:
        output.append(f"\nEnglish:\n{text_en}")
    if text_ar:
        output.append(f"\nArabic:\n{text_ar}")
    
    output.append("=" * 60)
    return "\n".join(output)

def format_quran(row):
    (qid, ch_num, v_num, v_key, text_uthmani, t_id, t_name, t_author, t_text) = row

    header = f"[Surah {ch_num}:{v_num} ({v_key})] ({t_name} by {t_author})"
    divider = "-" * len(header)
    output = [header, divider]
    output.append(f"Arabic (Uthmani):\n{text_uthmani}")
    output.append(f"\nTranslation ({t_name}):\n{t_text}")
    output.append("=" * 60)
    return "\n".join(output)

def search_hadiths(query, collection=None, limit=10):
    conn = get_connection()
    cursor = conn.cursor()

    # Escape quotes for SQLite FTS match query
    sanitized_query = query.replace('"', '""')
    fts_query = f'"{sanitized_query}"'

    sql = """
        SELECT h.* 
        FROM hadiths h
        JOIN hadiths_fts fts ON h.id = fts.rowid
        WHERE hadiths_fts MATCH ?
    """
    params = [fts_query]

    if collection:
        sql += " AND h.collection_slug = ?"
        params.append(collection.lower())

    sql += " LIMIT ?"
    params.append(limit)

    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return rows
    except sqlite3.OperationalError:
        # Fallback to simple query if FTS syntax fails
        sql_fallback = """
            SELECT * FROM hadiths 
            WHERE (text_english LIKE ? OR text_arabic LIKE ? OR narrator LIKE ? OR reference LIKE ?)
        """
        like_param = f"%{query}%"
        params_fb = [like_param, like_param, like_param, like_param]

        if collection:
            sql_fallback += " AND collection_slug = ?"
            params_fb.append(collection.lower())

        sql_fallback += " LIMIT ?"
        params_fb.append(limit)

        cursor.execute(sql_fallback, params_fb)
        return cursor.fetchall()

def search_quran(query, limit=10):
    conn = get_connection()
    cursor = conn.cursor()

    sanitized_query = query.replace('"', '""')
    fts_query = f'"{sanitized_query}"'

    sql = """
        SELECT q.*
        FROM (
            SELECT q.verse_key, MIN(rank) AS search_rank
            FROM quran_verses q
            JOIN quran_fts fts ON q.id = fts.rowid
            WHERE quran_fts MATCH ?
            GROUP BY q.verse_key
            ORDER BY search_rank
            LIMIT ?
        ) matches
        JOIN quran_verses q ON q.id = (
            SELECT q2.id
            FROM quran_verses q2
            WHERE q2.verse_key = matches.verse_key
              AND q2.translation_text != ''
              AND q2.translation_resource_id NOT IN ('ARABIC', '57')
            ORDER BY CASE WHEN q2.translation_resource_id = ? THEN 0 ELSE 1 END, q2.id
            LIMIT 1
        )
        ORDER BY matches.search_rank
    """
    try:
        cursor.execute(sql, (fts_query, limit, PREFERRED_QURAN_TRANSLATION_ID))
        rows = cursor.fetchall()
        return rows
    except sqlite3.OperationalError:
        # Fallback to LIKE
        like_param = f"%{query}%"
        sql_fallback = """
            SELECT q.* FROM quran_verses q
            WHERE q.id = (
                SELECT q2.id
                FROM quran_verses q2
                WHERE q2.verse_key = q.verse_key
                  AND q2.translation_text != ''
                  AND q2.translation_resource_id NOT IN ('ARABIC', '57')
                ORDER BY CASE WHEN q2.translation_resource_id = ? THEN 0 ELSE 1 END, q2.id
                LIMIT 1
            )
              AND (q.translation_text LIKE ? OR q.text_uthmani LIKE ? OR q.verse_key LIKE ?)
            LIMIT ?
        """
        cursor.execute(sql_fallback, (PREFERRED_QURAN_TRANSLATION_ID, like_param, like_param, like_param, limit))
        return cursor.fetchall()

def interactive_mode():
    print("==================================================")
    print("   PROJECT AL-MAJARRAT - QURAN & HADITH SEARCH   ")
    print("==================================================")
    print("Commands:")
    print("  h <query>           - Search Hadiths across all collections")
    print("  h:<collection> <q> - Search within specific collection (bukhari, muslim, tirmidhi, etc.)")
    print("  q <query>           - Search Quran verses")
    print("  all <query>         - Search both Quran and Hadiths")
    print("  exit / quit         - Exit the search CLI\n")

    while True:
        try:
            user_input = input("Al-Majarrat Search> ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit", "q!"]:
                print("Goodbye!")
                break

            parts = user_input.split(" ", 1)
            cmd = parts[0].lower()
            query = parts[1].strip() if len(parts) > 1 else ""

            if not query:
                print("Please enter a search query.\n")
                continue

            if cmd == "q":
                print(f"\n--- Searching Quran for: '{query}' ---")
                results = search_quran(query)
                if not results:
                    print("No matching Quran verses found.\n")
                else:
                    for r in results:
                        print(format_quran(r))
                    print(f"Found {len(results)} results.\n")

            elif cmd.startswith("h"):
                collection = None
                if ":" in cmd:
                    collection = cmd.split(":", 1)[1]
                
                coll_str = f" in [{collection}]" if collection else " across all collections"
                print(f"\n--- Searching Hadiths{coll_str} for: '{query}' ---")
                results = search_hadiths(query, collection=collection)
                if not results:
                    print("No matching Hadiths found.\n")
                else:
                    for r in results:
                        print(format_hadith(r))
                    print(f"Found {len(results)} results.\n")

            elif cmd == "all":
                print(f"\n=== QURAN RESULTS FOR: '{query}' ===")
                q_results = search_quran(query)
                for r in q_results:
                    print(format_quran(r))
                print(f"Quran matches: {len(q_results)}\n")

                print(f"=== HADITH RESULTS FOR: '{query}' ===")
                h_results = search_hadiths(query)
                for r in h_results:
                    print(format_hadith(r))
                print(f"Hadith matches: {len(h_results)}\n")

            else:
                # Default search all
                query = user_input
                print(f"\n=== QURAN RESULTS FOR: '{query}' ===")
                q_results = search_quran(query)
                for r in q_results:
                    print(format_quran(r))

                print(f"=== HADITH RESULTS FOR: '{query}' ===")
                h_results = search_hadiths(query)
                for r in h_results:
                    print(format_hadith(r))

        except KeyboardInterrupt:
            print("\nExiting search...")
            break
        except Exception as e:
            print(f"Error: {e}\n")

def main():
    parser = argparse.ArgumentParser(description="Al-Majarrat Quran & Hadith SQLite FTS5 Search CLI")
    parser.add_argument("-q", "--quran", type=str, help="Search Quran verses")
    parser.add_argument("-H", "--hadith", type=str, help="Search Hadith text")
    parser.add_argument("-c", "--collection", type=str, help="Hadith collection slug (bukhari, muslim, nasai, abudawud, tirmidhi, ibnmajah)")
    parser.add_argument("-a", "--all", type=str, help="Search across both Quran and Hadiths")
    parser.add_argument("-l", "--limit", type=int, default=10, help="Maximum number of results to return (default: 10)")
    parser.add_argument("-i", "--interactive", action="store_true", help="Start interactive search prompt")

    args = parser.parse_args()

    if len(sys.argv) == 1 or args.interactive:
        interactive_mode()
        return

    if args.quran:
        print(f"\n=== QURAN SEARCH RESULTS: '{args.quran}' ===")
        results = search_quran(args.quran, limit=args.limit)
        for r in results:
            print(format_quran(r))
        print(f"Total results: {len(results)}")

    if args.hadith:
        print(f"\n=== HADITH SEARCH RESULTS: '{args.hadith}' ===")
        results = search_hadiths(args.hadith, collection=args.collection, limit=args.limit)
        for r in results:
            print(format_hadith(r))
        print(f"Total results: {len(results)}")

    if args.all:
        print(f"\n=== QURAN SEARCH RESULTS: '{args.all}' ===")
        q_results = search_quran(args.all, limit=args.limit)
        for r in q_results:
            print(format_quran(r))

        print(f"\n=== HADITH SEARCH RESULTS: '{args.all}' ===")
        h_results = search_hadiths(args.all, collection=args.collection, limit=args.limit)
        for r in h_results:
            print(format_hadith(r))

if __name__ == "__main__":
    main()
