---
title: The Christian Project
emoji: ✝️
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
license: mit
---

# The Christian Project

> A RAG-powered AI assistant that answers theological questions using vetted pastoral teachings — built to keep a congregation's doctrinal voice intact.

---

## The Problem

I was at a Bible study when someone asked a question the pastor couldn't get to that night. Someone suggested "just ask ChatGPT." I knew enough about how large language models work to know why that was a problem: ChatGPT doesn't know what *this* church body teaches. It would give a confident, blended answer drawn from every tradition at once — and for a congregation with specific doctrinal commitments, that's not helpful. It's quietly corrosive.

I looked into building a custom GPT with uploaded documents. Same problem — I couldn't control what got surfaced or how it was framed. I couldn't audit the outputs. I couldn't ensure the model would stay within the bounds of what the pastors had actually taught.

So I built something else.

---

## What It Does

The Christian Project is a **Retrieval-Augmented Generation (RAG)** system that answers theological questions by retrieving directly from a curated corpus of pastoral teachings. When someone asks a question, the system:

1. Converts the question to a vector embedding
2. Searches a FAISS index built from pastor-authored content
3. Returns the most semantically relevant passages
4. Passes those passages to GPT-4o as grounded context
5. Generates a response — then appends a directive to seek pastoral guidance

The AI doesn't speak from its own training data. It speaks from what the pastors actually said.

---

## Architecture

```
Raw pastoral transcripts (Q&A, sermons, devotions)
        ↓
Normalization scripts (clean_csv.py, prepare_pastoral_teachings.py)
        ↓
Chunking + embedding (embed_dataset.py → all-MiniLM-L6-v2)
        ↓
FAISS vector index (cosine similarity, stored in data/processed/)
        ↓
Streamlit chat interface (app/Home.py)
        ↓
OpenAI GPT-4o (retrieval-grounded generation)
        ↓
Response + pastoral guidance directive
```

**Tech Stack:**
- **Backend:** Python, FAISS, sentence-transformers (`all-MiniLM-L6-v2`)
- **AI:** OpenAI API (GPT-4o and GPT-4o-mini)
- **Frontend:** Streamlit
- **Data Pipeline:** Custom normalization scripts, RSS scraper with GitHub Actions
- **Deployment:** Docker + Railway
- **CI/CD:** GitHub Actions — weekly automated RSS scrape + embedding rebuild

---

## Ethical Design

This project was built with specific ethical constraints from the start:

**1. Source data used with formal permission.**
The primary corpus is WELS (Wisconsin Evangelical Lutheran Synod) Q&A content. I contacted WELS directly, explained the use case, and received written permission before ingesting any of their material. This wasn't a legal formality — it was the right thing to do.

**2. Every response includes a pastoral guidance directive.**
The system is designed to be a *starting point*, not a conclusion. Every AI response ends with a reminder that the user should bring theological questions to their pastor. The AI surfaces what the church has taught; it doesn't replace the relationship.

**3. No hallucinated doctrine.**
By grounding every response in retrieved passages, the system cannot fabricate theology. If the answer isn't in the corpus, the system says so. This was the core reason for choosing RAG over a fine-tuned model or generic ChatGPT.

**4. Rate limiting and abuse prevention.**
The app includes per-user rate limiting middleware to prevent misuse and control API costs.

---

## What I Learned

**Technical:**
- How embeddings work in practice — not as a concept, but as a pipeline you debug at 11pm when your chunk sizes are wrong
- The difference between semantic similarity and doctrinal accuracy, and why RAG alone doesn't solve the second problem
- Docker image optimization for deployment size constraints (got a 6GB image down to under 4GB for Railway's limit)
- CI/CD pipeline design for automated data refresh without manual intervention

**Non-technical:**
- The church body ultimately didn't adopt this system. That taught me something I couldn't have learned from a textbook: technical correctness is not enough. Stakeholder trust, pastoral buy-in, and organizational change management are their own engineering problems.
- "Move fast and ask forgiveness" is exactly wrong for tools that touch people's faith. I'm glad I moved slowly and asked permission.
- Building something nobody asked you to build is a different skill than building something someone assigned to you. I learned to validate the problem before optimizing the solution.

---

## Getting Started

### Prerequisites

- Python 3.10+
- An OpenAI API key
- Docker (optional, for containerized deployment)

### Setup

```bash
# Clone the repo
git clone https://github.com/yourusername/the-christian-project.git
cd the-christian-project

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy the example env file and fill in your values
cp .env.example .env
# Edit .env with your OPENAI_API_KEY

# Build the FAISS index (requires source data in data/processed/)
python3 -m scripts.embed_dataset

# Run the app
streamlit run app/Home.py
```

### Environment Variables

Copy `.env.example` to `.env` and fill in your values. See `.env.example` for descriptions of each variable. Never commit `.env` to version control.

---

## Project Structure

```
the-christian-project/
├── app/
│   ├── Home.py               # Streamlit chat interface
│   ├── middleware/            # Rate limiting
│   └── ui/                   # UI components and layout
├── config/
│   ├── settings.py           # Runtime settings via env vars
│   └── prompt_templates.py   # System prompt templates
├── scripts/
│   ├── embed_dataset.py      # Build FAISS index from processed data
│   ├── prepare_pastoral_teachings.py  # Normalize raw transcripts
│   ├── build_training_dataset.py      # Export training-ready data
│   └── scrape_rss.py         # RSS content ingestion
├── data/
│   ├── raw/                  # Source transcripts (not committed)
│   ├── processed/            # Normalized JSONL datasets
│   └── cleaned/              # Cleaned intermediate data
├── tests/
│   └── test_security_phase1.py
├── .github/workflows/
│   └── auto_scrape.yml       # Weekly RSS scrape + rebuild
└── Dockerfile
```

---

## Data Pipeline: Refreshing the Index

To incorporate new pastoral material:

```bash
# 1. Add transcripts to data/raw/pastoral_teachings/
# 2. Update manifest.json with metadata (pastor, date, topic)

# 3. Normalize raw content
python3 -m scripts.prepare_pastoral_teachings

# 4. Rebuild embeddings
python3 -m scripts.embed_dataset

# 5. Restart the Streamlit service
```

The weekly GitHub Actions workflow handles RSS content automatically.

---

## About This Project

This is a portfolio project built over roughly two years to demonstrate applied AI engineering: problem identification, data pipeline design, ethical system architecture, and full-stack deployment.

The church body I built it for didn't end up adopting it — that's part of the story, not a footnote. It taught me as much about building for real organizations as the technical work did.

If you're hiring for AI Solutions Engineering or want to talk about RAG systems, responsible AI design, or what I learned building this, I'd like to connect.

**Jonah Kroll** — [LinkedIn](https://linkedin.com/in/jonahkroll) · [GitHub](https://github.com/yourusername)
