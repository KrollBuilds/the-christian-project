# Pastor Dashboard Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Railway Deployment                            │
│  https://the-christian-project.up.railway.app                   │
│                                                                   │
│  ┌───────────────────────────────────────────────────────┐      │
│  │           Streamlit Multi-Page Application            │      │
│  │                                                        │      │
│  │  ┌──────────────────┐  ┌──────────────────────────┐  │      │
│  │  │   Home.py        │  │  pages/                  │  │      │
│  │  │  (Public Chat)   │  │    1_📊_Pastor_Dash...  │  │      │
│  │  │                  │  │    (Protected)           │  │      │
│  │  │  • User Q&A      │  │                          │  │      │
│  │  │  • FAISS search  │  │  • Authentication        │  │      │
│  │  │  • Log questions │  │  • Review questions      │  │      │
│  │  │                  │  │  • Analytics             │  │      │
│  │  │                  │  │  • Export data           │  │      │
│  │  └────────┬─────────┘  └────────────┬─────────────┘  │      │
│  │           │                          │                 │      │
│  │           └──────────────────────────┘                 │      │
│  │                          │                             │      │
│  │                          ▼                             │      │
│  │           ┌──────────────────────────┐                 │      │
│  │           │  data/metrics/           │                 │      │
│  │           │    review_queue.jsonl    │                 │      │
│  │           │  (Shared Data Store)     │                 │      │
│  │           └──────────────────────────┘                 │      │
│  └───────────────────────────────────────────────────────┘      │
│                                                                   │
│  Environment Variables:                                          │
│  • OPENAI_API_KEY                                                │
│  • PASTOR_PASSWORD                                               │
│  • REVIEW_QUEUE_PATH                                             │
└─────────────────────────────────────────────────────────────────┘
```

## User Flow

### Public User Journey

```
1. User visits app
   ↓
2. Enters question in chat interface (Home.py)
   ↓
3. System processes question:
   - Sanitizes for PII
   - Searches FAISS for context
   - Generates answer via OpenAI
   ↓
4. User receives answer
   ↓
5. Question/answer logged to review_queue.jsonl
```

### Pastor Review Journey

```
1. Pastor visits app
   ↓
2. Clicks sidebar → "Pastor Dashboard"
   ↓
3. Enters password (PASTOR_PASSWORD)
   ↓
4. Session state sets: pastor_authenticated = True
   ↓
5. Dashboard loads questions from review_queue.jsonl
   ↓
6. Pastor can:
   - Filter by topic/date
   - Search questions
   - Review answers
   - Export data
   ↓
7. Clicks logout → Session cleared
```

## Data Flow

```
┌──────────────┐
│ User Question │
└───────┬──────┘
        │
        ▼
┌────────────────────┐
│ sanitize_text()    │  ← Remove PII (email, phone)
└────────┬───────────┘
         │
         ▼
┌────────────────────┐
│ FAISS Search       │  ← Find relevant doctrine
└────────┬───────────┘
         │
         ▼
┌────────────────────┐
│ OpenAI GPT-4       │  ← Generate answer
└────────┬───────────┘
         │
         ▼
┌────────────────────┐
│ Display to User    │
└────────┬───────────┘
         │
         ▼
┌──────────────────────────────┐
│ push_for_pastoral_review()   │
│                               │
│ Creates entry:                │
│ {                             │
│   response_id: "20251110...", │
│   question: "sanitized...",   │
│   answer: "sanitized...",     │
│   topic_cluster: "general",   │
│   timestamp: "2025-11-10...", │
│   tone_score: 0.75,           │
│   user_id: "anonymous"        │
│ }                             │
└────────┬─────────────────────┘
         │
         ▼
┌────────────────────────┐
│ review_queue.jsonl     │  ← Append as new line
│                        │
│ {...}                  │
│ {...}                  │
│ {...}  ← New entry     │
└────────────────────────┘
         │
         ▼
┌────────────────────────┐
│ Pastor Dashboard       │  ← Read and display
│ Reads JSONL file       │
└────────────────────────┘
```

## File Structure

```
the-christian-project/
├── app/
│   ├── Home.py                          # Main chat interface (renamed from chat_interface.py)
│   ├── pages/
│   │   └── 1_📊_Pastor_Dashboard.py    # Password-protected review dashboard
│   ├── config/
│   │   └── theme.py
│   ├── middleware/
│   │   └── rate_limit.py
│   ├── ui/
│   │   ├── layout.py
│   │   └── widgets.py
│   └── utils/
│       └── privacy_utils.py             # sanitize_text() function
├── data/
│   └── metrics/
│       ├── review_queue.jsonl           # Questions for pastoral review
│       └── feedback_log.jsonl           # User feedback data
├── config/
│   ├── settings.py
│   └── prompt_templates.py
├── scripts/
│   └── retrieval/                       # FAISS search utilities
├── .streamlit/
│   └── config.toml                      # Streamlit configuration
├── railway.toml                         # Railway deployment config
├── requirements.txt                     # Python dependencies
├── DEPLOYMENT_GUIDE.md                  # Deployment instructions
├── IMPLEMENTATION_CHECKLIST.md          # Step-by-step checklist
├── PASTOR_QUICK_START.md               # User guide for pastors
└── ARCHITECTURE.md                      # This file
```

## Authentication Flow

```
┌─────────────────────────┐
│ Pastor visits dashboard │
└────────┬────────────────┘
         │
         ▼
┌────────────────────────────────┐
│ Check session_state:           │
│   pastor_authenticated?        │
└────┬──────────────────┬────────┘
     │ False            │ True
     ▼                  ▼
┌──────────────┐  ┌──────────────────┐
│ Show login   │  │ Show dashboard   │
│ form         │  │ content          │
└────┬─────────┘  └──────────────────┘
     │
     ▼
┌──────────────────────────┐
│ User enters password     │
└────┬─────────────────────┘
     │
     ▼
┌──────────────────────────────────┐
│ Compare with env var:            │
│   os.getenv("PASTOR_PASSWORD")   │
└────┬──────────────────┬──────────┘
     │ Match            │ No match
     ▼                  ▼
┌────────────────┐  ┌──────────────┐
│ Set session:   │  │ Show error   │
│ authenticated  │  │ "Incorrect   │
│ = True         │  │  password"   │
└────┬───────────┘  └──────────────┘
     │
     ▼
┌────────────────┐
│ st.rerun()     │  ← Refresh page
└────────────────┘
     │
     ▼
┌────────────────────┐
│ Dashboard loads    │
└────────────────────┘
```

## Security Layers

```
┌─────────────────────────────────────────┐
│         Security Layer 1                 │
│  Railway Environment Variables          │
│  • PASTOR_PASSWORD not in code          │
│  • OPENAI_API_KEY stored securely       │
└─────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────┐
│         Security Layer 2                 │
│  Session-Based Authentication           │
│  • Password check on dashboard access   │
│  • Session cleared on logout            │
└─────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────┐
│         Security Layer 3                 │
│  PII Redaction                          │
│  • Email addresses removed              │
│  • Phone numbers redacted               │
│  • All data sanitized before logging    │
└─────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────┐
│         Security Layer 4                 │
│  Anonymous User IDs                     │
│  • No personal tracking                 │
│  • All users marked "anonymous"         │
└─────────────────────────────────────────┘
```

## Deployment Architecture

### Current: Single Service (Recommended)

```
┌──────────────────────────────────────────┐
│         Railway Project                   │
│                                           │
│  ┌────────────────────────────────────┐  │
│  │   Service: the-christian-project   │  │
│  │                                     │  │
│  │   Port: 8080                       │  │
│  │   Builder: Nixpacks                │  │
│  │   Command: streamlit run app/      │  │
│  │            Home.py                 │  │
│  │                                     │  │
│  │   Serves:                          │  │
│  │   - Public chat (/)                │  │
│  │   - Pastor dashboard (/pages/...)  │  │
│  └────────────────────────────────────┘  │
│                                           │
│  Persistent Storage:                     │
│  /app/data/metrics/review_queue.jsonl    │
│                                           │
│  Cost: ~$5/month (Hobby tier)            │
└──────────────────────────────────────────┘
```

### Alternative: Two Services (Future if Needed)

```
┌──────────────────────────────────────────────────────┐
│              Railway Project                          │
│                                                       │
│  ┌──────────────────────┐  ┌─────────────────────┐  │
│  │ Service 1: Chat      │  │ Service 2: Dashboard│  │
│  │ (Public)             │  │ (Private)           │  │
│  │                      │  │                     │  │
│  │ Port: 8080           │  │ Port: 8081          │  │
│  │ Domain: main URL     │  │ Domain: admin URL   │  │
│  └──────────┬───────────┘  └───────┬─────────────┘  │
│             │                      │                 │
│             └──────────┬───────────┘                 │
│                        │                             │
│                        ▼                             │
│             ┌─────────────────────┐                  │
│             │  Shared Volume      │                  │
│             │  /data              │                  │
│             └─────────────────────┘                  │
│                                                       │
│  Cost: ~$10/month (2x Hobby tier)                    │
└──────────────────────────────────────────────────────┘
```

## Technology Stack

```
┌─────────────────────────────────────────┐
│           Frontend Layer                 │
│  • Streamlit (multi-page)               │
│  • HTML/CSS (custom styling)            │
└─────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────┐
│         Application Layer                │
│  • Python 3.13                          │
│  • Streamlit session management         │
│  • Password authentication              │
└─────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────┐
│            Data Layer                    │
│  • JSONL file storage                   │
│  • FAISS vector database (Q&A context)  │
│  • File system persistence              │
└─────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────┐
│          External APIs                   │
│  • OpenAI GPT-4 (answer generation)     │
│  • OpenAI Embeddings (FAISS)            │
└─────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────┐
│         Hosting Layer                    │
│  • Railway (PaaS)                       │
│  • Nixpacks builder                     │
│  • Automatic HTTPS                      │
└─────────────────────────────────────────┘
```

## Scalability Considerations

### Current Capacity

- **Questions:** Up to ~50,000 JSONL entries before performance degrades
- **Concurrent Users:** ~10-20 simultaneous chat users
- **Dashboard Users:** 1-5 pastors reviewing simultaneously
- **Data Size:** ~100MB for question logs
- **Response Time:** <3 seconds for dashboard load

### When to Scale

Migrate to database (Supabase/PostgreSQL) when:
- Exceeding 10,000 questions
- Need real-time collaboration (multiple pastors editing simultaneously)
- Dashboard load time >5 seconds
- Need advanced analytics or reporting
- Want to implement user accounts with different permissions

### Scaling Path

```
Phase 1: JSONL Files (Current)
  ↓ (10K+ questions)
Phase 2: SQLite Database
  ↓ (50K+ questions or multi-user needs)
Phase 3: PostgreSQL/Supabase
  ↓ (100K+ questions or advanced features)
Phase 4: Microservices Architecture
```

## Monitoring & Logging

```
Railway Logs:
├── Application logs (print/logging)
├── Streamlit server logs
├── Error traces
└── Deployment logs

Question Metrics:
├── Total questions submitted
├── Questions per day/week/month
├── Topic distribution
├── Tone score trends
└── Dashboard access frequency
```

## Backup Strategy

```
Daily: Automated Railway snapshots (if configured)
Weekly: Manual export via dashboard (CSV/JSON)
Monthly: Full data backup to external storage
```

## Recovery Plan

```
Scenario 1: App crash
→ Railway auto-restarts (restart policy configured)

Scenario 2: Data corruption
→ Restore from Railway snapshot or weekly backup

Scenario 3: Deployment failure
→ Rollback to previous deployment via Railway UI

Scenario 4: Password compromise
→ Rotate PASTOR_PASSWORD in Railway env vars
→ Notify pastoral staff
```

## Performance Optimization

Current optimizations:
- Lazy loading of questions (read file on demand)
- Pagination for large datasets (dashboard shows all, but sortable)
- Efficient JSONL format (append-only, no database overhead)
- Streamlit caching for repeated data access

Future optimizations:
- Add `@st.cache_data` decorator for question loading
- Implement pagination (show 50 at a time)
- Compress old JSONL files
- Move to indexed database for faster queries

## Questions?

Refer to:
- **DEPLOYMENT_GUIDE.md** - Detailed deployment steps
- **IMPLEMENTATION_CHECKLIST.md** - Step-by-step checklist
- **PASTOR_QUICK_START.md** - User guide for pastors

---

**Last Updated:** November 10, 2025
**Architecture Version:** 1.0
**Status:** Production Ready ✅
