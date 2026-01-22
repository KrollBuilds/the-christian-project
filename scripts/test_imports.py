from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scripts.query_rag import query_with_gpt, format_truncated_answer
    print("✅ Retrieval utilities imported successfully.")
except Exception as e:
    print("❌ Import failed:", e)
