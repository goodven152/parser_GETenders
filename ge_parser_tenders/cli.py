import argparse
import logging
import sys
import json
from pathlib import Path
from collections.abc import Iterable
from .scraper import scrape_tenders
from .config import ParserSettings

def main(argv: Iterable[str] | None = None):
    # --- 0. Предварительный парсер, чтобы узнать путь к конфигу ---
    prelim_parser = argparse.ArgumentParser(add_help=False)
    prelim_parser.add_argument(
        "--config",
        default="config.json",
        help="Path to JSON config file with scraper settings",
    )
    prelim_args, remaining_argv = prelim_parser.parse_known_args(argv)

    # Загружаем настройки из JSON
    settings = ParserSettings.load(prelim_args.config)

    # --- 1. Основной парсер с дефолтами из config.json ---
    parser = argparse.ArgumentParser(
        parents=[prelim_parser],
        description="Georgian tender keyword scraper",
    )
    parser.add_argument(
        "--output",
        default=settings.output,
        help="Path to save JSON result",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=settings.max_pages,
        help="Stop after N results pages",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run with visible browser window",
    )
    parser.add_argument(
        "--reset-cache",
        action="store_true",
        default=settings.reset_cache,
        help="Удалить visited_ids.txt перед началом работы",
    )
    parser.add_argument(
        "--log",
        default=settings.log,
        help="Logging level",
    )
    args = parser.parse_args(remaining_argv)

    # --- 2. Эффективные значения после учёта CLI-перекрытий ---
    headless = False if args.no_headless else settings.headless
    max_pages = args.max_pages
    output_path = args.output

    # --- 3. Сброс кеша при необходимости ---
    cache_file = Path("visited_ids.txt")
    if args.reset_cache and cache_file.exists():
        cache_file.unlink()
        print("Cache reset: removed visited_ids.txt")

    # --- 4. Логирование ---
    logging.basicConfig(
        level=getattr(logging, args.log.upper(), "INFO"),
        format="%(levelname)s: %(message)s",
    )

    logging.info("Starting scrape…")
    try:
        ids = scrape_tenders(max_pages=max_pages, headless=headless, settings=settings)
    except KeyboardInterrupt:
        sys.exit("Interrupted by user")

    Path(output_path).write_text(json.dumps(ids, indent=2, ensure_ascii=False))
    print(f"Saved {len(ids)} tender IDs → {output_path}")


if __name__ == "__main__":
    main()