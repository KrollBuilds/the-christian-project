# Data Pipeline Workflow

Complete workflow from scraping raw content to training the model.

## Step 1: Scrape Raw Data

Run the scraper scripts to collect content from WELS sources:

```bash
source mlenv/bin/activate

# Scrape What About Jesus Q&A (questioning-god section)
python3 scripts/scrape_whataboutjesus_qa.py

# Scrape WELS daily devotions
python3 scripts/scrape_daily_devotions.py

# Scrape WELS doctrinal content
python3 scripts/scrape_wels_content.py
```

**Output:**
- Raw data saved to `data/raw/whataboutjesus/qa_articles.jsonl`
- Raw data saved to `data/raw/wels_devotions_web/*.jsonl`
- Raw data saved to `data/raw/wels/*.jsonl`

**What's in raw data:**
- URLs (not useful for training)
- Messy HTML/metadata
- Unclean text
- Need processing before use

---

## Step 2: Process & Clean Data

Clean the raw scraped data into training-ready format:

```bash
# Process What About Jesus Q&A articles
python3 scripts/process_whataboutjesus.py

# (Add other processing scripts as needed for devotions/WELS content)
```

**What this does:**
- Removes URLs and metadata
- Cleans HTML artifacts
- Extracts clean question/answer pairs
- Deduplicates against existing data
- Normalizes text formatting
- Generates stable IDs

**Output:**
- Clean data saved to `data/processed/whataboutjesus_qa.jsonl`

---

## Step 3: Build Training Dataset

Combine all processed data into the master training dataset:

```bash
# Build training dataset from all approved entries
python3 scripts/build_training_dataset.py

# Or build from last 30 days only
python3 scripts/build_training_dataset.py --days 30
```

**What this does:**
- Combines processed Q&A from multiple sources
- Adds manually approved entries from Pastor Dashboard
- Formats for fine-tuning (instruction format)
- Creates train/validation splits

**Output:**
- `data/training/training_data.jsonl` - Main training file
- `data/training/validation_data.jsonl` - Validation file

---

## Step 4: Build Vector Store (RAG Database)

Create the semantic search database for context retrieval:

```bash
python3 scripts/build_vector_store.py
```

**What this does:**
- Chunks all doctrinal content
- Generates embeddings (vector representations)
- Builds FAISS vector database
- Enables fast semantic search during inference

**Output:**
- Vector database saved to `data/vector_stores/`

---

## Complete Workflow Summary

```
┌─────────────────────┐
│  1. SCRAPE          │  scrape_*.py scripts
│  (Raw Data)         │  → data/raw/
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  2. PROCESS         │  process_*.py scripts
│  (Clean Data)       │  → data/processed/
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  3. BUILD TRAINING  │  build_training_dataset.py
│  (Training Data)    │  → data/training/
└──────────┬──────────┘
           ↓
┌─────────────────────┐
│  4. BUILD VECTORS   │  build_vector_store.py
│  (RAG Database)     │  → data/vector_stores/
└─────────────────────┘
```

---

## Quick Start: Full Pipeline

Run all steps in sequence:

```bash
source mlenv/bin/activate

# Step 1: Scrape all sources
python3 scripts/scrape_whataboutjesus_qa.py
python3 scripts/scrape_daily_devotions.py
python3 scripts/scrape_wels_content.py

# Step 2: Process scraped data
python3 scripts/process_whataboutjesus.py

# Step 3: Build training dataset
python3 scripts/build_training_dataset.py

# Step 4: Build vector store
python3 scripts/build_vector_store.py
```

---

## File Locations

### Raw Data (messy, needs processing)
- `data/raw/whataboutjesus/qa_articles.jsonl`
- `data/raw/wels_devotions_web/*.jsonl`
- `data/raw/wels/*.jsonl`

### Processed Data (clean, ready for training)
- `data/processed/whataboutjesus_qa.jsonl`
- `data/processed/qa_clean.jsonl`

### Training Data (final format)
- `data/training/training_data.jsonl`
- `data/training/validation_data.jsonl`

### Pastor Dashboard Data
- `data/metrics/review_queue.jsonl` - Questions awaiting review
- `data/metrics/approved_training.jsonl` - Pastor-approved Q&A

### Vector Store (RAG database)
- `data/vector_stores/` - Semantic search database

---

## Notes

- **Incremental Updates**: Scrapers use checkpoints to avoid re-scraping
- **Deduplication**: Processing scripts check for duplicates
- **Pastor Approval**: Use dashboard to review/approve before training
- **Robots.txt**: All scrapers now handle robots.txt correctly

---

## Troubleshooting

**Scraper returns 0 results:**
- Fixed! All scrapers now handle robots.txt properly
- Check internet connection
- Verify target site is accessible

**Duplicate data:**
- Processing scripts deduplicate automatically
- Uses stable hash IDs based on content

**Missing processed data:**
- Make sure to run Step 2 (process scripts) after Step 1 (scraping)
- Raw data alone isn't usable for training
