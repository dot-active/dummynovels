---
name: split-novel-chapters
description: Split a full novel text file (e.g. fullstory.txt) into one numbered file per chapter (001.txt, 002.txt, ...). Use this whenever the user wants to split, divide, break up, or chapterize a novel/story/book text file by chapter — in Chinese ("按章节拆分小说", "分章", "把这本小说切成一章一章的", 第一回/第一章/卷一 style headings) or English ("split this novel by chapter", "Chapter 1" style headings). Also use it when the user mentions a fullstory.txt-like file alongside a chapters/ directory of NNN.txt files, since that is exactly the input/output shape this skill produces. The heading style does not need to be known in advance — detect it automatically.
---

# Split Novel Into Chapters

Splits one large novel text file into a sequence of small per-chapter files
(`001.txt`, `002.txt`, ...), auto-detecting whatever chapter-heading
convention the source file actually uses instead of assuming one style.
Real novels vary a lot here — Chinese classical fiction numbers chapters as
"回" (hui), modern Chinese fiction usually uses "章" (zhang) or plain "卷"
(juan, volume), and English novels use "Chapter N" in several sub-flavors
(digits, spelled-out numbers, ALL CAPS, with or without a colon+title). The
same file can also contain special non-numbered sections — 序章/楔子
(prologue), 番外 (extra/side story), 尾声/结局 (epilogue), 后记 (afterword)
— that should still become their own chapter file even though they don't
fit the numbered pattern.

## Why a script instead of doing this by hand

Do not manually scan the text and copy chapter boundaries — for a novel
that can be hundreds of chapters and tens of thousands of lines, a person
(or a model) eyeballing it will miscount or miss a boundary. Use
`scripts/split_chapters.py`: it reads the whole file, tries several
heading-style patterns, picks whichever style actually recurs consistently
in *this* file, and slices on exact line boundaries so no text is
paraphrased, dropped, or duplicated in the split.

## Usage

```bash
python3 scripts/split_chapters.py <input.txt> <output_dir> [--min-chapters N] [--dry-run]
```

1. **Always run with `--dry-run` first.** It prints the detected encoding,
   the winning heading style, the chapter count, and a preview of the first
   few detected headings — without writing anything. Read that output.
2. **Sanity-check the count and preview against what the user expects**, if
   they mentioned a chapter count or you can otherwise estimate it (e.g. a
   table of contents, a description elsewhere in the project). If the
   preview headings look like real chapter titles and the count looks
   plausible, proceed without `--dry-run` to actually write the files.
3. **If chapters detected is low** (the script warns when it's below
   `--min-chapters`, default 3), don't just accept it — read a few raw
   lines from the source file yourself (e.g. lines around where you'd
   expect a chapter break) to see what the actual heading format is. It's
   often something slightly outside the built-in patterns (see "Extending
   detection" below).
4. Output files are zero-padded to fit the chapter count (e.g. `001.txt`
   for <1000 chapters, `0001.txt` if there happen to be 1000+). If there's
   substantial front matter before the first detected chapter (a title
   page, foreword, etc. — more than a stray blank line), it's saved as
   `000.txt` so nothing from the source file is silently discarded.

## What counts as a chapter boundary

The script tries these heading styles and uses whichever one has the most
matches in the file (ties/near-misses are exactly why `--dry-run` matters —
skim the preview rather than trusting counts blindly):

- `第X回` — hui (e.g. 封神演義-style classical fiction)
- `第X章` — zhang, the most common modern Chinese chapter marker
- `卷X` or `第X卷` — juan/volume (some story collections chapter at the
  volume level rather than per-story, e.g. 聊齋志異)
- `第X节/篇/集/部`
- `Chapter N` — English, case-insensitive, with digits, spelled-out
  numbers ("Chapter One"), or roman numerals, with or without a trailing
  colon and title
- `X` in the chapter marker can be Arabic digits or Chinese numerals
  (一二三四五六七八九十百千萬, including compounds like 一百二十三)

Regardless of which numbered style wins, these special markers always
count as their own chapter boundary, since they're common in both
classical and web-fiction structures: 序章/楔子/引子/序言/前言 (prologue),
尾声/尾聲/终章/終章/结局/結局 (epilogue), 后记/後記/后序/後序 (afterword),
番外/番外篇 (side story, optionally numbered).

Heading lines are matched at the start of a line (after stripping leading
Markdown decoration like `#`, `##`, `*`, `-`, so `## 第一章 标题` and
`第一章 标题` both work), and are capped at 60 characters — real chapter
headings are short, so this avoids mistaking a narrative sentence that
merely happens to start with "第一章" for an actual heading.

## Encoding

The script tries `utf-8-sig` (handles a UTF-8 BOM transparently), plain
`utf-8`, then `gb18030` (superset of GBK), `big5`, and `shift_jis`, in that
order, and reports which one it used. Output files are always written as
plain UTF-8, regardless of the source encoding, for consistency.

## Extending detection

If a file uses a heading style genuinely outside the patterns above (e.g. a
custom bracket format, or a language other than Chinese/English), don't
hand-roll a one-off split — add a new entry to the `STYLES` dict in
`scripts/split_chapters.py` (or to `SPECIAL_MARKERS` for a non-numbered
section type) following the existing pattern, then rerun. That keeps the
detection reusable for the next novel with the same format instead of a
throwaway fix.
