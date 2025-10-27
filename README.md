The Christian Project is a biblically grounded AI assistant designed to answer theological questions using carefully curated Christian teachings. This project uses retrieval-augmented generation (RAG) and will evolve into a self-learning, doctrinally faithful system.

## Ethical Safeguards

- All AI-generated answers conclude with a directive to seek personal pastoral guidance, ensuring that users understand The Christian Project is not a substitute for pastoral care.

## Demo Retrieval Refresh

Use this sequence to incorporate newly vetted pastoral material ahead of live demos:

1. Add transcripts and metadata to `data/raw/pastoral_teachings` and update `manifest.json` with ids, pastors, dates, topics, and relative paths to each transcript.
2. Normalize the raw content into retrieval-ready JSONL records:
   ```
   python3 -m scripts.prepare_pastoral_teachings
   ```
3. Regenerate the doctrinal + pastoral teaching embeddings for the chat experience:
   ```
   python3 -m scripts.embed_dataset
   ```
4. (Optional) Rebuild the combined QA/doctrine index if you have updated question/answer material:
   ```
   python3 -m scripts.build_vector_store --datasets qa doctrine
   ```
5. Restart the Streamlit service so it loads the refreshed FAISS index from `data/processed/wels_embeddings`.

The retrieval layer now carries pastor-authored teaching segments with source, pastor, date, and topic metadata so leadership can see how feedback will guide future training.
