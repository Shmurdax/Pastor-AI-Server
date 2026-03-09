import fitz  # PyMuPDF
import re
import os

# === CONFIG ===
PDF_PATH = r"C:\Users\MC_Mill\Documents\GitHub\Pastor-AI-GUI\Pastor-AI-main\Pastor-Data\The Holy Bible - New King James Version - NKJV (DOC).pdf"
OUTPUT_MD = r"C:\Users\MC_Mill\Documents\GitHub\Pastor-AI-GUI\Pastor-AI-main\converted_markdown\nkjv_bible.md"

# Common Bible book names (uppercase for matching)
BIBLE_BOOKS_UPPER = {b.upper() for b in [
    "GENESIS", "EXODUS", "LEVITICUS", "NUMBERS", "DEUTERONOMY", "JOSHUA", "JUDGES",
    "RUTH", "1 SAMUEL", "2 SAMUEL", "1 KINGS", "2 KINGS", "1 CHRONICLES", "2 CHRONICLES",
    "EZRA", "NEHEMIAH", "ESTHER", "JOB", "PSALMS", "PROVERBS", "ECCLESIASTES", "SONG OF SOLOMON",
    "ISAIAH", "JEREMIAH", "LAMENTATIONS", "EZEKIEL", "DANIEL", "HOSEA", "JOEL", "AMOS",
    "OBADIAH", "JONAH", "MICAH", "NAHUM", "HABAKKUK", "ZEPHANIAH", "HAGGAI", "ZECHARIAH", "MALACHI",
    "MATTHEW", "MARK", "LUKE", "JOHN", "ACTS", "ROMANS", "1 CORINTHIANS", "2 CORINTHIANS",
    "GALATIANS", "EPHESIANS", "PHILIPPIANS", "COLOSSIANS", "1 THESSALONIANS", "2 THESSALONIANS",
    "1 TIMOTHY", "2 TIMOTHY", "TITUS", "PHILEMON", "HEBREWS", "JAMES", "1 PETER", "2 PETER",
    "1 JOHN", "2 JOHN", "3 JOHN", "JUDE", "REVELATION"
]}

def is_book_line(line):
    stripped_upper = line.strip().upper()
    words = stripped_upper.split()
    return any(word in BIBLE_BOOKS_UPPER for word in words) or stripped_upper in BIBLE_BOOKS_UPPER

def process_page_text(text, current_book, current_chapter, current_verse):
    lines = text.splitlines()
    processed = []
    in_verse_block = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_verse_block:
                processed.append("")  # blank for separation
            continue

        # BOOK START → force chapter 1, verse 0
        if is_book_line(stripped):
            current_book = stripped.title()
            current_chapter = 1
            current_verse = 0
            processed.append(f"\n# {current_book}")
            processed.append(f"## {current_chapter}")
            in_verse_block = True
            continue

        # ISOLATED NUMBER → treat as explicit chapter
        isolated_num_match = re.match(r'^\s*([1-9]\d*)\s*$', stripped)
        if isolated_num_match:
            candidate_chap = int(isolated_num_match.group(1))
            if current_chapter == 0 or candidate_chap > current_chapter:
                current_chapter = candidate_chap
                current_verse = 0
                processed.append(f"\n## {current_chapter}")
                in_verse_block = True
                continue

        # EXPLICIT "Chapter X"
        chap_match = re.match(r'^(Chapter|CHAPTER)\s*([1-9]\d*)\s*$', stripped, re.IGNORECASE)
        if chap_match:
            current_chapter = int(chap_match.group(2))
            current_verse = 0
            processed.append(f"\n## {current_chapter}")
            in_verse_block = True
            continue

        # VERSE: number followed by content
        cleaned_stripped = re.sub(r'([a-zA-Z])([1-9]\d*)', r'\1 \2', stripped)
        cleaned_stripped = re.sub(r'([1-9]\d*)([a-zA-Z])', r'\1 \2', cleaned_stripped)

        verse_match = re.match(r'^(\d+)\s*([:.–-]?)\s*(.*)$', cleaned_stripped)
        if verse_match:
            verse_num = int(verse_match.group(1))
            sep = verse_match.group(2)
            verse_text = verse_match.group(3).strip()

            if verse_text and verse_text[0].islower():
                verse_text = verse_text[0].upper() + verse_text[1:]

            # === THE MAGIC FIX ===
            # If the number matches the next chapter, but throws off our verse sequence,
            # it is a fused Chapter Heading + Verse 1!
            if current_chapter > 0 and verse_num == current_chapter + 1 and verse_num != current_verse + 1:
                current_chapter = verse_num
                current_verse = 1
                processed.append(f"\n## {current_chapter}\n")
                if verse_text:
                    processed.append(f"**1** {verse_text}")
                in_verse_block = True
                continue
            # =====================

            # Normal verse
            current_verse = verse_num
            processed.append(f"\n**{verse_num}** {verse_text}")
            in_verse_block = True
            continue

        # CONTINUATION OF PREVIOUS VERSE/LINE
        if in_verse_block and processed:
            last = processed[-1]
            if last.endswith(('. ', '! ', '? ', ': ', '." ', '!" ', '?" ')):
                processed.append(stripped)
            else:
                processed[-1] = last + " " + stripped
        else:
            processed.append(stripped)

    return "\n".join(processed), current_book, current_chapter, current_verse

def main():
    if not os.path.exists(PDF_PATH):
        print(f"PDF not found: {PDF_PATH}")
        return

    print(f"Converting Bible PDF: {PDF_PATH}")
    doc = fitz.open(PDF_PATH)
    full_md = []

    current_book = None
    current_chapter = 0
    current_verse = 0

    for page_num, page in enumerate(doc, 1):
        text = page.get_text("text")
        if not text.strip():
            continue

        md_page, current_book, current_chapter, current_verse = process_page_text(
            text, current_book, current_chapter, current_verse
        )
        
        if md_page:
            full_md.append(md_page)

        if page_num % 100 == 0:
            print(f"Processed {page_num}/{len(doc)} pages...")

    doc.close()

    md_content = "\n".join(full_md)

    # Final global cleanup
    md_content = re.sub(r'[ \t]+', ' ', md_content) 
    md_content = re.sub(r'(?i)Page \d+ of \d+', '', md_content) 
    md_content = re.sub(r'\n{3,}', '\n\n', md_content)

    header = "# The Holy Bible\n## New King James Version (NKJV)\n\n"
    
    with open(OUTPUT_MD, 'w', encoding='utf-8') as f:
        f.write(header + md_content.strip())

    print(f"\nDone! Markdown saved to: {OUTPUT_MD}")

if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUTPUT_MD), exist_ok=True)
    main()