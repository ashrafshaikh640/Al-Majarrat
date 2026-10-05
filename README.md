# Al-Majarrat

Al-Majarrat is a local Quran and Hadith research project that combines SQLite search, FTS5 indexing, vector search, and a local LLM for grounded answers.

## Project structure

```text
Project AL Majarrat/
├── data/
│   ├── corpora/
│   │   ├── bukhari_corpus.csv
│   │   ├── muslim_corpus.csv
│   │   ├── nasai_corpus.csv
│   │   ├── abudawud_corpus.csv
│   │   ├── tirmidhi_corpus.csv
│   │   ├── ibnmajah_corpus.csv
│   │   ├── quran_corpus.csv
│   │   └── hadith_master_corpus.csv
│   ├── db/
│   │   └── al_majarrat_master.db
│   ├── datasets/
│   │   ├── majarrat_finetune_alpaca.jsonl
│   │   └── majarrat_finetune_chat.jsonl
│   ├── raw/
│   └── models/
├── src/
│   ├── al_majarrat.py
│   ├── create_master_corpus.py
│   ├── build_vector_index.py
│   ├── search_majarrat.py
│   ├── serve_web_ui.py
│   ├── export_finetuning_dataset.py
│   ├── train_qwen_lora.py
│   └── validate_project.py
├── tests/
│   └── test_project_health.py
├── web/
│   └── index.html
├── .gitignore
├── project_config.py
├── requirements.txt
├── requirements-training.txt
├── README.md
└── .venv/
```

## Setup

1. Create or activate the project virtual environment.
2. Install the base dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Build the database and prepared corpus files:

   ```bash
   python src/create_master_corpus.py
   ```

4. Ensure Ollama is running and the required models are installed:

   ```bash
   ollama pull nomic-embed-text
   ollama pull qwen2.5:3b
   ```

5. (Optional but recommended) build semantic vectors:

   ```bash
   python src/build_vector_index.py
   ```

6. Launch the web interface:

   ```bash
   python src/serve_web_ui.py
   ```

7. Or run the CLI retrieval engine:

   ```bash
   python src/al_majarrat.py -a "what does the Quran say about patience?"
   ```

## Run the AI model

The project uses Ollama to run the chat model locally. From the project root:

1. Start Ollama. Open the Ollama desktop application, or run this in a terminal if the Ollama service is not already running:

   ```bash
   ollama serve
   ```

   Keep that terminal open while using the model.

2. In another terminal, download the chat and embedding models:

   ```bash
   ollama pull qwen2.5:3b
   ollama pull nomic-embed-text
   ```

3. Confirm that both models are installed:

   ```bash
   ollama list
   ```

4. Make sure the project database has been built (see Setup above), then ask a question using the CLI:

   ```bash
   python src/al_majarrat.py --ask "What does the Quran say about patience?"
   ```

   To use a different installed Ollama chat model, pass its name with `--model`, for example:

   ```bash
   python src/al_majarrat.py --model qwen2.5:3b --ask "What does the Quran say about patience?"
   ```

5. Alternatively, start the web interface:

   ```bash
   python src/serve_web_ui.py
   ```

   Open `http://127.0.0.1:8765` in your browser and submit a question.

If you only want to test retrieval without generating an AI answer, use `--test-retrieval`:

```bash
python src/al_majarrat.py --test-retrieval "patience"
```

## Validation

Run the health check before troubleshooting or startup:

```bash
python src/validate_project.py
```

This validates:

- required corpus files are present
- the SQLite database schema exists and is populated
- Ollama is responding and required models are available

## Important notes

- All project paths are centralized in `project_config.py` so the app resolves data correctly from any working directory.
- Generated runtime artifacts are stored in `data/` instead of the repository root to avoid clutter and collisions.
- The project is structured so source code, generated data, web assets, and tests remain separated and do not overlap.
- The local LLM is optional for retrieval-only workflows but required for full grounded AI responses.
