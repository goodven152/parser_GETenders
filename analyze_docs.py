# analyze_docs.py
import json
import logging
from pathlib import Path
from ge_parser_tenders.config import ParserSettings
from ge_parser_tenders.extractor import extract_text
from ge_parser_tenders.text_matcher import find_keyword_hits
from ge_parser_tenders.memory_manager import MemoryManager

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

INPUT_JSON = Path("found_tenders.json")
OUTPUT_JSON = Path("parsed_results.json")


def analyze_files(settings: ParserSettings):
    if not INPUT_JSON.exists():
        logging.error("Файл %s не найден", INPUT_JSON)
        return

    memory_manager = MemoryManager(
        warning_threshold_mb=settings.memory_warning_threshold_mb,
        critical_threshold_mb=settings.memory_critical_threshold_mb,
        gc_interval=settings.gc_interval_seconds
    )

    with INPUT_JSON.open("r", encoding="utf-8") as f:
        tenders = json.load(f)

    results = []

    for tender in tenders:
        tender_id = tender["tender_id"]
        matched_files = []

        for path_str in tender["files"]:
            path = Path(path_str)
            if not path.exists():
                logging.warning("Файл %s не существует, пропускаем", path)
                continue

            if not memory_manager.check_memory():
                logging.warning("Память критична, пропускаем %s", path)
                continue

            logging.info("🔍 Проверка %s…", path.name)
            try:
                text = extract_text(path)
                if not text.strip():
                    continue
                hits = find_keyword_hits(
                    text,
                    settings.keywords_geo,
                    threshold=settings.fuzzy_threshold,
                    memory_manager=memory_manager
                )
                if hits:
                    matched_files.append({
                        "path": str(path),
                        "hits": hits
                    })
            except Exception as exc:
                logging.error("Ошибка при обработке %s: %s", path.name, exc)

        if matched_files:
            results.append({
                "tender_id": tender_id,
                "matched_files": matched_files
            })

    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    logging.info("✅ Анализ завершён. Результаты в %s", OUTPUT_JSON)


if __name__ == "__main__":
    settings = ParserSettings.load()
    analyze_files(settings)
