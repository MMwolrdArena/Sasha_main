import sys
from pathlib import Path

query = " ".join(sys.argv[1:]).strip()
if not query:
    raise SystemExit("Usage: python scripts/test_web_search.py <query>")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.argv = [sys.argv[0]]
from modules.web_search import perform_web_search


def main():
    data = perform_web_search(query=query, num_pages=3, fetch_content=True)
    print(data)


if __name__ == "__main__":
    main()
