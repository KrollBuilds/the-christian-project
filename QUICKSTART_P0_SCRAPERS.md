# Quick Start Guide - P0 Data Scrapers

## 🚀 Getting Started

### Step 1: Install Dependencies (if needed)

```bash
# If you haven't installed dependencies yet
pip3 install -r requirements.txt

# Or if using a virtual environment
source venv/bin/activate  # or your venv path
pip install -r requirements.txt
```

All required libraries (requests, beautifulsoup4) are already in requirements.txt!

---

## 📥 Collecting Data

### Option A: Collect Everything at Once

```bash
# 1. Scrape What About Jesus Q&A (150-300 articles)
python3 scripts/scrape_whataboutjesus_qa.py

# 2. Process into training format
python3 scripts/process_whataboutjesus.py

# 3. Scrape daily devotions
python3 scripts/scrape_daily_devotions.py
```

**Time Estimate:**
- What About Jesus: 5-15 minutes
- Processing: < 1 minute
- Daily Devotions: 10-30 minutes

---

### Option B: Start with What About Jesus Only

```bash
# Just get the high-value Q&A content first
python3 scripts/scrape_whataboutjesus_qa.py
python3 scripts/process_whataboutjesus.py
```

---

## 📊 Check Your Results

```bash
# View Q&A stats
wc -l data/raw/whataboutjesus/qa_articles.jsonl
wc -l data/processed/whataboutjesus_qa.jsonl

# View devotions stats
wc -l data/raw/wels_devotions_web/daily_devotions.jsonl

# View sample Q&A
tail -3 data/raw/whataboutjesus/qa_articles.jsonl | python3 -m json.tool
```

---

## 🔄 Incremental Updates (Daily/Weekly)

Once you've done the initial scrape, you can run periodically for updates:

```bash
# Daily - get new devotions (run this every day)
python3 scripts/scrape_daily_devotions.py

# Weekly - check for new Q&A articles (run once a week)
python3 scripts/scrape_whataboutjesus_qa.py
python3 scripts/process_whataboutjesus.py
```

**Tip:** The scripts use checkpoints, so they'll only scrape NEW content!

---

## 🎓 Add to Training Pipeline

Once you've collected and processed data:

```bash
# Build training dataset (includes all sources)
python3 scripts/build_training_dataset.py
```

This will include:
- Existing 1,886 WELS Q&A ✅
- NEW What About Jesus Q&A (150-300)
- Your approved training data

---

## 📁 Expected Output Structure

After running all P0 scripts:

```
data/
├── raw/
│   ├── whataboutjesus/
│   │   ├── qa_articles.jsonl          # Scraped Q&A
│   │   └── .checkpoint_qa.json        # Checkpoint
│   └── wels_devotions_web/
│       ├── daily_devotions.jsonl      # Scraped devotions
│       └── .checkpoint_daily.json     # Checkpoint
├── processed/
│   └── whataboutjesus_qa.jsonl        # Processed for training
```

---

## ⚠️ Important Notes

1. **First Run Takes Time:** Initial scraping may take 15-45 minutes total
2. **Incremental is Fast:** Subsequent runs only grab new content (< 5 min)
3. **Checkpoints Save Progress:** If interrupted, scripts resume where they left off
4. **Rate Limited:** Scripts are respectful (1.5-2.5 sec between requests)

---

## 🐛 Troubleshooting

**Problem:** Scripts run but no output files

**Solution:** Check console output for errors. Verify internet connection.

---

**Problem:** "ModuleNotFoundError: No module named 'requests'"

**Solution:**
```bash
pip3 install requests beautifulsoup4
# or
pip3 install -r requirements.txt
```

---

**Problem:** Want to re-scrape everything

**Solution:** Delete checkpoint files
```bash
rm data/raw/whataboutjesus/.checkpoint_qa.json
rm data/raw/wels_devotions_web/.checkpoint_daily.json
```

---

## 📞 Need Help?

See full documentation: `scripts/README_NEW_SCRAPERS.md`

---

**Ready to start?** Run this:
```bash
python3 scripts/scrape_whataboutjesus_qa.py
```

🎉 You'll have 150-300 high-quality Q&A articles in 5-15 minutes!
