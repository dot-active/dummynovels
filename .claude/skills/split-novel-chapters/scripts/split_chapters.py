#!/usr/bin/env python3
"""Split a full-novel text file into per-chapter files (001.txt, 002.txt, ...).

Auto-detects the chapter heading style used in the source file — Chinese
"第X回"/"第X章"/"卷X" (Chinese numerals or Arabic digits, optionally under a
Markdown "#" heading), or English "Chapter N" — plus common special markers
like 序章/楔子/番外/尾声/后记. No style needs to be specified up front.

Usage:
    python3 split_chapters.py <input.txt> <output_dir> [--min-chapters N] [--dry-run]
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------------------
# Encoding handling
# ---------------------------------------------------------------------------

# Ordered by how common they are for novel text files. utf-8-sig transparently
# strips a BOM if present and otherwise behaves like utf-8.
CANDIDATE_ENCODINGS = ["utf-8-sig", "utf-8", "gb18030", "big5", "shift_jis"]


def read_text(path: Path) -> tuple[str, str]:
    """Decode the file, trying encodings in order. Returns (text, encoding_used)."""
    raw = path.read_bytes()
    last_err = None
    for enc in CANDIDATE_ENCODINGS:
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError) as e:
            last_err = e
            continue
    # Last resort: don't crash the whole run over a handful of bad bytes.
    return raw.decode("utf-8", errors="replace"), "utf-8 (with replacement)"


# ---------------------------------------------------------------------------
# Chapter-heading detection
# ---------------------------------------------------------------------------

CN_NUM = r"[〇零一二三四五六七八九十百千万萬两廿卅0-9]+"

# Each style: a regex matched against a *stripped, decoration-free* line.
# Order doesn't matter here; scoring picks whichever style has the most hits.
STYLES = {
    "hui": re.compile(rf"^第\s*({CN_NUM})\s*回\b"),
    "zhang": re.compile(rf"^第\s*({CN_NUM})\s*章\b"),
    "jie": re.compile(rf"^第\s*({CN_NUM})\s*[节節篇集部]\b"),
    "juan": re.compile(rf"^卷\s*({CN_NUM})\b"),
    "juan_di": re.compile(rf"^第\s*({CN_NUM})\s*卷\b"),
    "english": re.compile(
        r"^chapter\s+([0-9]+|[ivxlcdm]+|[a-z]+(?:[\s-][a-z]+)?)\b", re.IGNORECASE
    ),
}

# Markers that always count as a chapter/section boundary regardless of the
# dominant numbering style (front matter, interludes, back matter, extras).
SPECIAL_MARKERS = re.compile(
    r"^(序章|楔子|引子|序言|前言|自序|尾声|尾聲|终章|終章|後記|后记|後序|后序"
    r"|结局|結局|外传|外傳|番外(?:篇)?\s*" + CN_NUM + r"?|结语|結語"
    r"|prologue|epilogue|preface|foreword|afterword|introduction|interlude"
    r"|appendix|acknowledge?ments?|author'?s\s+note)\b",
    re.IGNORECASE,
)

# Strip Markdown/decoration noise from the front of a line before matching,
# e.g. "## 第一章 病毒破晓" or "**Chapter 1**" or "- 第一回".
DECORATION_RE = re.compile(r"^[#>\-\*\s]+")

# Heading lines are short. This guards against matching a narrative sentence
# that merely starts with "第一章" (e.g. "第一章的内容让他印象深刻...").
MAX_HEADING_LEN = 60


def normalize_line(line: str) -> str:
    line = unicodedata.normalize("NFKC", line)
    # NFKC turns full-width digits/letters into ASCII, which helps matching,
    # but keep a separate raw-ish stripped version for the stored title text.
    return line.strip().strip("　").strip()


def strip_decoration(line: str) -> str:
    return DECORATION_RE.sub("", line).strip()


def find_matches(lines: list[str]) -> dict[str, list[tuple[int, str]]]:
    """For each style, collect (line_index, heading_text) of every match."""
    hits: dict[str, list[tuple[int, str]]] = {name: [] for name in STYLES}
    for i, raw_line in enumerate(lines):
        norm = normalize_line(raw_line)
        if not norm or len(norm) > MAX_HEADING_LEN:
            continue
        candidate = strip_decoration(norm)
        if not candidate or len(candidate) > MAX_HEADING_LEN:
            continue
        for name, pattern in STYLES.items():
            if pattern.match(candidate):
                hits[name].append((i, candidate))
                break  # a line only counts once, for its first matching style
    return hits


def find_special_markers(lines: list[str]) -> list[tuple[int, str]]:
    hits = []
    for i, raw_line in enumerate(lines):
        norm = normalize_line(raw_line)
        if not norm or len(norm) > MAX_HEADING_LEN:
            continue
        candidate = strip_decoration(norm)
        if candidate and SPECIAL_MARKERS.match(candidate):
            hits.append((i, candidate))
    return hits


def detect_boundaries(text: str) -> tuple[str, list[tuple[int, str]]]:
    """Return (style_name, sorted list of (line_index, heading_text)) for the
    winning heading style, merged with special front/back-matter markers."""
    lines = text.split("\n")
    style_hits = find_matches(lines)
    special_hits = find_special_markers(lines)

    best_style = max(style_hits, key=lambda k: len(style_hits[k]))
    best_count = len(style_hits[best_style])

    if best_count == 0:
        boundaries = special_hits
        best_style = "special-only"
    else:
        # Merge the winning numbered style with special markers, dedup by line.
        merged = {i: t for i, t in style_hits[best_style]}
        for i, t in special_hits:
            merged.setdefault(i, t)
        boundaries = sorted(merged.items())

    return best_style, boundaries


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------


def split_into_chapters(text: str, boundaries: list[tuple[int, str]]) -> tuple[str, list[str]]:
    """Return (preamble, [chapter_text, ...]) using 0-indexed line boundaries."""
    lines = text.split("\n")
    if not boundaries:
        return text, []

    preamble = "\n".join(lines[: boundaries[0][0]]).strip("\n")

    chapters = []
    for idx, (start, _title) in enumerate(boundaries):
        end = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(lines)
        chunk = "\n".join(lines[start:end]).strip("\n") + "\n"
        chapters.append(chunk)
    return preamble, chapters


def write_chapters(output_dir: Path, preamble: str, chapters: list[str], encoding: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []

    # Only keep front matter if it looks like real content (title page, an
    # author's note, etc.) rather than a stray blank line or two.
    if len(preamble.strip()) > 30:
        p = output_dir / "000.txt"
        p.write_text(preamble.strip() + "\n", encoding="utf-8", newline="\n")
        written.append(p)

    width = max(3, len(str(len(chapters))))
    for i, chapter_text in enumerate(chapters, start=1):
        p = output_dir / f"{i:0{width}d}.txt"
        p.write_text(chapter_text, encoding="utf-8", newline="\n")
        written.append(p)
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to the full-novel text file")
    parser.add_argument("output_dir", type=Path, help="Directory to write NNN.txt files into")
    parser.add_argument(
        "--min-chapters",
        type=int,
        default=3,
        help="Warn if fewer chapters than this are detected (default: 3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect and report chapter boundaries without writing any files",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1

    text, encoding = read_text(args.input)
    style, boundaries = detect_boundaries(text)

    print(f"input: {args.input}")
    print(f"detected encoding: {encoding}")
    print(f"detected heading style: {style}")
    print(f"chapters detected: {len(boundaries)}")

    if len(boundaries) < args.min_chapters:
        print(
            f"\nWARNING: only {len(boundaries)} chapter boundaries were found "
            f"(threshold: {args.min_chapters}). This usually means the chapter "
            "heading format in this file wasn't recognized. Inspect a few "
            "heading lines from the source file directly and consider "
            "extending the patterns in split_chapters.py rather than trusting "
            "this output as-is.",
            file=sys.stderr,
        )

    preview_n = min(5, len(boundaries))
    if preview_n:
        print("\nfirst headings found:")
        for i, title in boundaries[:preview_n]:
            print(f"  line {i + 1}: {title}")
        if len(boundaries) > preview_n:
            print(f"  ... and {len(boundaries) - preview_n} more")

    if args.dry_run:
        print("\n(dry run: no files written)")
        return 0

    if not boundaries:
        print("error: no chapter boundaries found, nothing to write", file=sys.stderr)
        return 1

    preamble, chapters = split_into_chapters(text, boundaries)
    written = write_chapters(args.output_dir, preamble, chapters, encoding)
    print(f"\nwrote {len(written)} files to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
