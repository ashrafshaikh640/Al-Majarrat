import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import project_config
from src.validate_project import check_database, check_data_files


class TestProjectHealth(unittest.TestCase):
    def test_project_paths_are_absolute(self):
        self.assertTrue(Path(project_config.BASE_DIR).is_absolute())
        self.assertTrue(Path(project_config.DB_PATH).is_absolute())

    def test_data_files_exist(self):
        result = check_data_files()
        self.assertTrue(result["ok"], result["messages"])

    def test_database_check_handles_missing_file(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            missing_path = Path(tmp_dir) / "missing.db"
            result = check_database(missing_path)
            self.assertFalse(result["ok"])
            self.assertIn("not found", result["messages"][0].lower())

    def test_database_check_handles_valid_schema(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE hadiths (id INTEGER PRIMARY KEY, text_english TEXT)"
            )
            conn.execute(
                "CREATE TABLE quran_verses (id INTEGER PRIMARY KEY, verse_key TEXT)"
            )
            conn.execute(
                "CREATE VIRTUAL TABLE hadiths_fts USING fts5(text_english)"
            )
            conn.execute(
                "CREATE VIRTUAL TABLE quran_fts USING fts5(verse_key)"
            )
            conn.execute("INSERT INTO hadiths (text_english) VALUES ('test')")
            conn.execute("INSERT INTO quran_verses (verse_key) VALUES ('1:1')")
            conn.commit()
            conn.close()

            result = check_database(db_path)
            self.assertTrue(result["ok"], result["messages"])


if __name__ == "__main__":
    unittest.main()
