<h1 align="center">Let's Play DnD</h1>

<p align="center">
  <a href="README.md">中文</a> ·
  <a href="README_EN.md">English</a>
</p>

<div align="center">

  ![Status](https://img.shields.io/badge/status-online-brightgreen)
  ![WIP](https://img.shields.io/badge/WIP-yes-yellow)
  ![Python](https://img.shields.io/badge/python-3.10%2B-blue)
  ![Flask](https://img.shields.io/badge/flask-framework-black?logo=flask)
  ![Bilingual](https://img.shields.io/badge/lang-zh%20%7C%20en-orange)
  [![中文](https://img.shields.io/badge/lang-中文-red)](README.md)
  [![English](https://img.shields.io/badge/lang-English-blue)](README_EN.md)
  ![License](https://img.shields.io/badge/license-MIT-green)

</div>

<p align="center">
  <strong>Live demo:</strong>
  <a href="https://rosemarysun.com/letsplaydnd/">https://rosemarysun.com/letsplaydnd/</a>
</p>

## Description

LetsPlayDnD is a web-based Dungeons & Dragons (D&D 5e) campaign assistant. Players can register and sign in through the browser, ask rules questions via **Consult the DM**, and continue multi-turn play inside **game saves**. The project includes a RAG (retrieval-augmented generation) system with Chinese/English support: UI and consult languages are switchable, while each game save's language is locked when the save is created.

This repository is mainly for learning and reference. For the full experience, please use the live demo above.

Current focus: accounts, UI, and the Consult flow. The main game loop (`game_zh` / `game_en`) is still under development.

## Tech Stack

| Layer | Technologies |
|------|----------------|
| Backend | Python 3, Flask |
| Frontend | Vanilla HTML / CSS / JavaScript |
| Accounts & saves | SQLite (`account.db`, per-save `chat.db`) |
| LLM | OpenAI-compatible API (DeepSeek by default); users bring their own API key |
| RAG | Chroma, sentence-transformers, PyMuPDF |
| Embedding | `BAAI/bge-small-zh-v1.5` (Chinese), `BAAI/bge-small-en-v1.5` (English) |

## Setup

### Requirements

- Python 3.10+
- Access to Hugging Face (to download embedding models)
- A DeepSeek (or OpenAI-compatible) API key on the client side

### Install

```bash
git clone <repository-url>
cd LetsPlayDnD

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

Pre-download RAG models (recommended, so the first consult does not wait on downloads):

```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5'); SentenceTransformer('BAAI/bge-small-en-v1.5'); print('ok')"
```

Build the vector store (you need local Chinese/English D&D rulebook PDFs; edit paths and collection names `dnd_rules_zh` / `dnd_rules_en` in `RAG/build_index.py`, then run twice for a bilingual index—or once if you only need one language):

```bash
python RAG/build_index.py
```

### Configuration

Create a `.env` file in the project root (adjust model and thinking options as needed):

```env
FLASK_SECRET_KEY=replace-with-a-long-random-string
DEEPSEEK_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_THINKING_ENABLED=true
DEEPSEEK_REASONING_EFFORT=medium
```

Generate `FLASK_SECRET_KEY` with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Run

```bash
source venv/bin/activate
python server.py
```

The app listens on `http://0.0.0.0:5000` by default. Open `http://localhost:5000/login.html` to register or sign in. Users enter their API key in settings.

### Project layout (overview)

```
server.py              Flask entry point
UI/                    Frontend static assets
System/
  consult/             Consult-the-DM logic
  game/                Game-save logic (shared IO in game.py; flows in game_zh / game_en)
  api_client.py        LLM client wrapper
RAG/                   Index building and retrieval
Prompts/               Prompt files (consult / game)
Tools/                 Function-calling tool definitions
Account/               User data (gitignored; only .gitkeep)
Templates/user/        Template for new user directories
```

## Notes

**Deployment paths**  
Frontend requests use relative paths (e.g. `api/me`, `login.html`) so the app can live under a subpath. Avoid absolute URLs that start with `/` in JS.

**Do not commit secrets or local data**  
`.gitignore` excludes `.env`, `account.db`, `Account/*` (keeps `Account/.gitkeep`), and `RAG/vector_db/`. Do not commit vector stores or account data.

**Vector store is not in Git**  
Chinese and English rule indexes live under `RAG/vector_db/`. Build them locally with `RAG/build_index.py`; a fresh clone will not include them.

**Embedding models are not in requirements.txt**  
`pip install -r requirements.txt` only installs Python packages. Pre-download models before first RAG use (see Install above), or the first run will fetch them online and feel slow.

**Low-memory installs**  
`sentence-transformers` depends on PyTorch. On a machine with little RAM and no swap, `pip install` may get `Killed` while downloading torch. Add swap, or install a CPU build of torch first.

**Chroma batch size limit**  
If `build_index.py` calls `add` with too many chunks at once, it can fail. Write in batches (e.g. 5000 at a time).

**Consult vs game language**  
Home / Consult UI language follows user settings (refresh if it does not update immediately). A game save's `in_game_language` is fixed at creation and does not change when you switch the UI language.

**Secrets and API keys**  
`FLASK_SECRET_KEY` is used for sessions and for encrypting user API keys. After rotating the secret, users must re-enter their API key in settings.

**Rulebook PDFs**  
The indexer needs local PDFs (not shipped, for copyright reasons). Configure paths in `build_index.py` yourself; do not commit personal absolute paths to a public repo.

**Lazy RAG import**  
`consult` imports `RAG` only when retrieval runs, so opening Consult does not load embeddings immediately. The first retrieval in a process can still be slow.

Questions or suggestions? Please open an Issue.
