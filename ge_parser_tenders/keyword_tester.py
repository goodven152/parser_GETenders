#!/usr/bin/env python3
"""
    keyword_tester.py — standalone / in‑package utility to test keyword detection
    in a single document using fuzzy‑matching (RapidFuzz) and optional lemma
    support via Stanza.

    How to run (from project root):
        # as a module, so relative imports work
        python -m ge_parser_tenders.keyword_tester path/to/file.pdf \
               --threshold 85 --log DEBUG

    If you prefer to install the package:
        pip install -e .
        keyword_tester path/to/file.pdf

    Requirements:
        pip install rapidfuzz stanza
        python -c "import stanza; stanza.download('ka')"  # once, models
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rapidfuzz import fuzz
import stanza

# ---------------------------------------------------------------------------
#  Import project helpers (relative, because script lives inside the package)
# ---------------------------------------------------------------------------

from .extractor import extract_text  # type: ignore  # noqa: E402
from .config import KEYWORDS_GEO      # type: ignore  # noqa: E402

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _normalise_whitespace(text: str) -> str:
    """Collapse runs of whitespace → single spaces."""
    return " ".join(text.split())


def _build_lemma_text(text: str) -> str:
    """Return lemma‑level representation of *text* using Stanza (Georgian)."""
    try:
        nlp = stanza.Pipeline(
            "ka",
            processors="tokenize,pos,lemma",
            tokenize_no_ssplit=True,
            use_gpu=False,
            logging_level="WARN",
        )
    except Exception as exc:
        logging.warning("Stanza initialisation failed (%s). Lemma matching disabled.", exc)
        return ""

    doc = nlp(text)
    lemmas: list[str] = []
    for sentence in doc.sentences:
        lemmas.extend(word.lemma or word.text for word in sentence.words)
    return " ".join(lemmas)


def _fuzzy_hits(keywords: list[str], haystack: str, threshold: int) -> dict[str, int]:
    """Return dict(keyword → best_score) for scores >= *threshold*."""
    results: dict[str, int] = {}
    for kw in keywords:
        score = fuzz.partial_ratio(kw, haystack)
        if score >= threshold:
            results[kw] = score
    return results


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Georgian keyword fuzzy‑tester")
    parser.add_argument("file", type=Path, help="Document (.pdf/.xlsx/.docx …)")
    parser.add_argument("--threshold", type=int, default=80, help="Similarity cutoff 0‑100")
    parser.add_argument("--log", default="INFO", help="Logging level (DEBUG/INFO)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log.upper(), "INFO"),
                        format="%(levelname)s: %(message)s")

    logging.info("Scanning %s", args.file)
    text = extract_text(args.file)
    if not text.strip():
        logging.error("No text extracted — aborting.")
        sys.exit(2)

    text_norm = _normalise_whitespace(text)
    logging.debug("Original text length: %d characters", len(text_norm))

    direct_hits = _fuzzy_hits(KEYWORDS_GEO, text_norm, args.threshold)
    logging.info("Direct match: %d hits", len(direct_hits))

    lemma_hits: dict[str, int] = {}
    lemma_text = _build_lemma_text(text_norm)
    if lemma_text:
        lemma_hits = _fuzzy_hits(KEYWORDS_GEO, lemma_text, args.threshold)
        logging.info("Lemma match:  %d hits", len(lemma_hits))

    hits = {**direct_hits}
    for kw, score in lemma_hits.items():
        hits[kw] = max(score, hits.get(kw, 0))

    if hits:
        logging.info("\nFound keywords (threshold=%d):", args.threshold)
        for kw, score in sorted(hits.items(), key=lambda t: -t[1]):
            print(f"{kw:<60} score={score}")
    else:
        logging.info("No keywords found (threshold=%d)", args.threshold)


if __name__ == "__main__":
    main()
