# Relay: local text feature

Build and test this folder on your laptop first. You do not need to download or clone the GitHub repository. Upload the source files to your `text-dispatch` branch after testing.

## 1. Open the folder

Unzip `relay-text-feature.zip`. Open the extracted `relay-text-feature` folder in VS Code. Open **Terminal → New Terminal**. The terminal should be in the folder containing this file and `requirements.txt`.

Requires Python 3.10 or newer. Check with `python3 --version`.

## 2. Install and run on a Mac

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. Keep the terminal running; use **Control+C** to stop the server. If port 8000 is occupied, replace `8000` with `8001` and open that port in the browser.

For later sessions, activate the environment and run the final command again. `.env` is a hidden local file; open it from VS Code's Explorer.

## 3. See the feature immediately

With an empty API key, the interface clearly says **Scripted preview**. Click any of the six sample messages to see the conversation reply, responder summary, missing information, evidence quotes, and question-answering references. The preview uses fixed example interpretations, not AI. Arbitrary messages and multi-turn follow-ups require live AI.

Nothing is sent to an AI provider in preview mode. Messages you successfully submit are stored locally in `storage/relay.sqlite3`. A new conversation leaves prior conversations in that database; deleting `storage/` while the server is stopped resets the local demo.

## 4. Enable actual AI

Edit `.env` on your laptop:

```dotenv
ANTHROPIC_API_KEY=your_actual_key_here
ANTHROPIC_MODEL=claude-haiku-5-5
```

Stop and restart the server. The badge changes to **Claude · live AI**. Use an API model available to your account if the default is unavailable. A Claude chat subscription is separate from API access and API usage is billed by the provider. Do not paste your key into the web chat or upload `.env` to GitHub.

Now try:

1. `We need food.`
2. Answer its clarification: `20 food packs, at Riverside School in Hanover.`
3. `Is anyone delivering?`

The backend supplies the last 20 conversation messages to Claude so it can interpret follow-up answers. Facts are tied to community quotes, and missing quantities stay unknown. The reference file is small enough to send directly to the model; no vector database or training is needed.

## What is included

- Community text input and a readable reply.
- Multi-purpose message interpretation: questions, requests, delivery reports, problems, offers, and other messages.
- Structured requested items, quantities, locations, access barriers, and source quotes.
- Targeted clarification for missing request details.
- Q&A using the supplied reference file. The backend constructs factual answers from that file rather than letting the model invent answers.
- An inbox and responder cards, with persistent local conversations.
- API endpoints for your dashboard teammate; see **http://127.0.0.1:8000/docs**.

**This first module does not dispatch supplies, deduct stock, verify receipt, send SMS/WhatsApp messages, or integrate video.** Delivery messages are unverified reports for human review. The inventory and dispatch module can be added next using approved records. Source-quote checks validate that quotes exist; they do not prove an interpretation is correct.

All data in `backend/knowledge.json` is explicitly fictional. For this hackathon, keep it a labeled demonstration. A real service needs current responder-approved information, freshness rules, authentication, controlled access to messages, and an appropriate operational workflow.

## Files and integration

| File | Purpose |
| --- | --- |
| `backend/main.py` | API, local persistence, and page serving |
| `backend/text_service.py` | Claude connection, preview examples, evidence checks, reply assembly |
| `backend/schemas.py` | Validated input and AI interpretation formats |
| `backend/knowledge.json` | Fictional approved reference information |
| `backend/static/index.html` | A lightweight local test interface; your teammate can replace it |
| `requirements.txt` | Backend dependencies |

### API contract

`POST /messages`

```json
{
  "conversation_id": "community-1",
  "text": "We need 20 food packs at Riverside School. Is anyone delivering?"
}
```

Returns `id`, `message_id`, `conversation_id`, `original_message`, `community_reply`, `clarifying_questions`, `interpretation`, `sources`, `status`, `review_required`, `mode`, and `created_at`.

- `GET /requests`: latest 100 interpretation cards; optionally filter with `?conversation_id=community-1`.
- `GET /conversations/community-1`: saved conversation messages.
- `GET /health`: mode, configured model ID, scenario label, and preview examples. Never returns the key.

The test interface and API share the same origin. For a separate frontend development server, use its development proxy for API calls, or add a CORS allowlist for the actual frontend origin.

### Move to GitHub later

1. Open `KTujjar/Project-DR`, and select **text-dispatch**.
2. Use **Add file → Upload files** and upload `backend/`, `requirements.txt`, `requirements-dev.txt`, `START_HERE.md`, and `tests/`.
3. Include `.env.example` and merge the rules in `.gitignore` with any existing repository ignore rules. Finder may hide these dotfiles; **Command+Shift+.** shows them.
4. Upload the contents of this folder at the repository root, preserving the `backend/` folder. Do not upload the enclosing `relay-text-feature` folder if you want the same run commands.
5. Exclude `.env`, `.venv/`, `storage/`, caches, and your API key. If teammates have added a root requirements file, merge dependencies rather than overwrite it.
6. Commit to **text-dispatch**. Your teammate can review and integrate the branch afterward.

## Checks

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

These checks use the scripted preview and a fake AI service. They do not call Claude or spend API credits. Live API behavior must be checked with your own configured API access.

Official references: https://github.com/anthropics/anthropic-sdk-python and https://platform.claude.com/docs/en/build-with-claude/structured-outputs
