import argparse
import logging
import sys
import json
import requests
from pathlib import Path
from collections.abc import Iterable
from .scraper import scrape_tenders

def main(argv: Iterable[str] | None = None):
    parser = argparse.ArgumentParser(description="Georgian tender keyword scraper")
    parser.add_argument("--output", default="found_tenders.json", help="Path to save JSON result")
    parser.add_argument("--max-pages", type=int, help="Stop after N results pages")
    parser.add_argument("--no-headless", action="store_true", help="Run with visible browser window")
    parser.add_argument("--reset-cache", action="store_true", help="Удалить visited_ids.txt перед началом работы",)
    parser.add_argument("--log", default="INFO", help="Logging level")
    args = parser.parse_args(argv)

    # ← если указали --reset-cache, удаляем файл кеша
    cache_file = Path("visited_ids.txt")
    if args.reset_cache and cache_file.exists():
        cache_file.unlink()
        print("Cache reset: removed visited_ids.txt")

    logging.basicConfig(
        level=getattr(logging, args.log.upper(), "INFO"),
        format="%(levelname)s: %(message)s"
    )

    logging.info("Starting scrape…")
    try:
        ids = scrape_tenders(max_pages=args.max_pages, headless=not args.no_headless)
    except KeyboardInterrupt:
        sys.exit("Interrupted by user")

    Path(args.output).write_text(json.dumps(ids, indent=2, ensure_ascii=False))
    print(f"Saved {len(ids)} tender IDs → {args.output}")


if __name__ == "__main__":
    main()