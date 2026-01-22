# WELS Data Collection Scripts - P0 Release

## Overview

This document covers the **Phase 0 (P0) scripts** for enhanced WELS data collection. These scripts provide incremental scraping capabilities for high-value Q&A content and daily devotions.

## 🎯 P0 Scripts

### 1. `scrape_whataboutjesus_qa.py`

**Purpose:** Scrape Q&A articles from What About Jesus website.

**Features:**
- ✅ Incremental scraping (only new articles)
- ✅ Checkpoint system for resume capability
- ✅ Pagination support (handles multi-page sections)
- ✅ Extracts question, answer, topics, scripture references
- ✅ Metadata capture (author, date, category)
- ✅ Rate limiting and respectful crawling

**Target URL:** https://whataboutjesus.com/questioning-god/

**Usage:**
```bash
# First run - scrapes all articles
python3 scripts/scrape_whataboutjesus_qa.py

# Subsequent runs - only scrapes new articles
python3 scripts/scrape_whataboutjesus_qa.py
```

**Output:**
- File: `data/raw/whataboutjesus/qa_articles.jsonl`
- Checkpoint: `data/raw/whataboutjesus/.checkpoint_qa.json`
- Format: One JSON object per line

**Output Schema:**
```json
{
  "id": "abc123def456",
  "question": "Can I trust the Bible?",
  "answer": "The Bible is the inspired Word of God...",
  "url": "https://whataboutjesus.com/...",
  "category": "questioning-god",
  "topics": ["Bible", "Faith", "Truth"],
  "scripture_refs": ["2 Timothy 3:16", "John 17:17"],
  "author": "Author Name",
  "date_published": "2024-01-15",
  "scraped_at": "2025-11-13T15:00:00.000000"
}
```

**Expected Results:**
- 150-300 Q&A articles from What About Jesus
- High-quality beginner-friendly theological Q&A

---

### 2. `scrape_daily_devotions.py`

**Purpose:** Scrape daily devotions from WELS website with incremental updates.

**Features:**
- ✅ Incremental scraping (designed for daily runs)
- ✅ Flexible content extraction (handles varying HTML)
- ✅ Date tracking (knows what's already collected)
- ✅ Checkpoint system
- ✅ Rate limiting

**Target URL:** https://wels.net/serving-you/devotions/

**Usage:**
```bash
# Initial run - scrapes all available devotions
python3 scripts/scrape_daily_devotions.py

# Daily run - scrapes only new devotions
python3 scripts/scrape_daily_devotions.py
```

**Recommended Schedule:**
```bash
# Run daily via cron (example: every day at 9 AM)
0 9 * * * cd /path/to/project && python3 scripts/scrape_daily_devotions.py >> logs/devotions.log 2>&1
```

**Output:**
- File: `data/raw/wels_devotions_web/daily_devotions.jsonl`
- Checkpoint: `data/raw/wels_devotions_web/.checkpoint_daily.json`
- Format: Append mode (new devotions added to existing file)

**Output Schema:**
```json
{
  "id": "xyz789abc123",
  "title": "God's Grace in Daily Life",
  "scripture": "Ephesians 2:8-9",
  "content": "Full devotion text...",
  "category": "daily",
  "url": "https://wels.net/...",
  "date_published": "2025-11-13",
  "author": "Pastor Name",
  "image_url": "https://wels.net/wp-content/uploads/...",
  "scraped_at": "2025-11-13T09:00:00.000000"
}
```

**Note:** The structure of devotions may vary over time. The script uses flexible extraction patterns to handle different HTML layouts.

---

### 3. `process_whataboutjesus.py`

**Purpose:** Convert scraped Q&A articles into standardized training format.

**Features:**
- ✅ Converts to training format
- ✅ Deduplication (checks against existing Q&A)
- ✅ Quality filtering (length, completeness)
- ✅ Text normalization
- ✅ Metadata preservation

**Usage:**
```bash
# Run after scraping What About Jesus content
python3 scripts/process_whataboutjesus.py
```

**Input:** `data/raw/whataboutjesus/qa_articles.jsonl`
**Output:** `data/processed/whataboutjesus_qa.jsonl`

**Output Schema:**
```json
{
  "id": "stable_hash_id",
  "question": "Normalized question text",
  "answer": "Normalized answer text",
  "topic": "Primary topic",
  "source": "What About Jesus",
  "source_url": "https://whataboutjesus.com/...",
  "scripture_references": ["Reference 1", "Reference 2"],
  "topics": ["Topic 1", "Topic 2"],
  "author": "Author Name",
  "date_published": "2024-01-15",
  "processed_at": "2025-11-13T15:30:00.000000"
}
```

**Quality Filters:**
- Minimum question length: 10 characters
- Minimum answer length: 100 characters
- Maximum question length: 500 characters
- Maximum answer length: 10,000 characters

---

## 🔄 Complete Workflow

### Initial Setup (First Time)

```bash
# 1. Scrape What About Jesus Q&A
python3 scripts/scrape_whataboutjesus_qa.py

# 2. Process Q&A into training format
python3 scripts/process_whataboutjesus.py

# 3. Scrape daily devotions
python3 scripts/scrape_daily_devotions.py

# 4. Build training dataset (includes all processed data)
python3 scripts/build_training_dataset.py
```

### Incremental Updates (Ongoing)

**Daily** (for devotions):
```bash
# Scrape new daily devotions
python3 scripts/scrape_daily_devotions.py
```

**Weekly** (for Q&A):
```bash
# Check for new Q&A articles (if What About Jesus adds new content)
python3 scripts/scrape_whataboutjesus_qa.py
python3 scripts/process_whataboutjesus.py
```

**As Needed** (for training):
```bash
# When ready to retrain the model
python3 scripts/build_training_dataset.py
```

---

## 📊 Expected Data Volumes

| Source | Initial | Ongoing (per week) |
|--------|---------|-------------------|
| What About Jesus Q&A | 150-300 articles | 0-5 new articles |
| Daily Devotions | 50-200 devotions | 7 new devotions |

---

## 🛡️ Checkpoint System

Both scrapers use checkpoint files to track progress:

**Checkpoint Features:**
- Tracks visited URLs
- Stores last run timestamp
- Counts total items collected
- Prevents re-scraping existing content
- Enables resume after interruption

**Checkpoint Locations:**
- What About Jesus: `data/raw/whataboutjesus/.checkpoint_qa.json`
- Daily Devotions: `data/raw/wels_devotions_web/.checkpoint_daily.json`

**Reset Checkpoints:**
```bash
# To re-scrape everything (careful!)
rm data/raw/whataboutjesus/.checkpoint_qa.json
rm data/raw/wels_devotions_web/.checkpoint_daily.json
```

---

## ⚙️ Configuration

### Rate Limiting

Both scripts use respectful rate limiting:
- Delay between requests: 1.5 - 2.5 seconds (random)
- Respects robots.txt
- Timeout: 15 seconds per request

**Adjust rate limiting** (if needed):
```python
# In each script, modify:
DELAY_RANGE = (1.5, 2.5)  # Increase for slower scraping
```

### User Agent

```python
HEADERS = {
    "User-Agent": "TheChristianProjectBot/1.0 (WELS-approved; educational use)"
}
```

---

## 🧪 Testing

### Test Scraper (Small Sample)

To test without scraping everything:

```bash
# Test What About Jesus scraper (will respect checkpoint)
python3 scripts/scrape_whataboutjesus_qa.py

# Check output
head -5 data/raw/whataboutjesus/qa_articles.jsonl
wc -l data/raw/whataboutjesus/qa_articles.jsonl
```

### Validate Output

```bash
# Check JSONL validity
python3 -c "
import json
with open('data/raw/whataboutjesus/qa_articles.jsonl', 'r') as f:
    for i, line in enumerate(f, 1):
        try:
            json.loads(line)
        except json.JSONDecodeError as e:
            print(f'Line {i}: {e}')
print('✅ All lines valid')
"
```

---

## 🐛 Troubleshooting

### Issue: No articles found

**Solution:**
- Check internet connection
- Verify target website is accessible
- Check robots.txt permissions
- Review console output for error messages

### Issue: Checkpoint prevents scraping

**Solution:**
```bash
# View checkpoint status
cat data/raw/whataboutjesus/.checkpoint_qa.json

# Reset if needed
rm data/raw/whataboutjesus/.checkpoint_qa.json
```

### Issue: Duplicate content

**Solution:**
- Processing script automatically deduplicates
- Check `processed_at` timestamps to verify

### Issue: HTML structure changed

**Solution:**
- Scrapers use flexible extraction patterns
- If structure changes significantly, update extraction logic in:
  - `extract_qa_content()` (What About Jesus)
  - `extract_devotion_content()` (Daily Devotions)

---

## 📈 Monitoring

### Check Scraping Progress

```bash
# What About Jesus - view checkpoint
cat data/raw/whataboutjesus/.checkpoint_qa.json

# Daily Devotions - view checkpoint
cat data/raw/wels_devotions_web/.checkpoint_daily.json

# Count total articles
wc -l data/raw/whataboutjesus/qa_articles.jsonl
wc -l data/raw/wels_devotions_web/daily_devotions.jsonl
```

### View Latest Entries

```bash
# Last 3 Q&A articles
tail -3 data/raw/whataboutjesus/qa_articles.jsonl | python3 -m json.tool

# Last 3 devotions
tail -3 data/raw/wels_devotions_web/daily_devotions.jsonl | python3 -m json.tool
```

---

## 🔜 Next Steps (P1 Scripts)

After P0 scripts are working well, we'll add:

1. **Forward in Christ Archive Scraper**
   - 2,000+ articles from 2016-2025
   - Configurable date range (default: last 2 years)

2. **Data Consolidation Pipeline**
   - Merge all sources into master training set
   - Advanced deduplication
   - Topic classification

3. **Quality Validation Tools**
   - Automated quality checks
   - Content completeness validation
   - Training readiness assessment

---

## 📞 Support

If you encounter issues:
1. Check this README
2. Review script console output
3. Verify checkpoint files
4. Test with small samples first

---

**Version:** 1.0 (P0 Release)
**Last Updated:** 2025-11-13
**Author:** Caleb
