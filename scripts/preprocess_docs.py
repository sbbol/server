"""
Преобразование документов базы знаний в чистый Markdown.

Использование:
    python scripts/preprocess_docs.py

Читает файлы из data/ (txt, xml), очищает шум, сохраняет в data/processed/.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "processed"

NOISE_PATTERNS = [
    (r"\t+", " "),
    (r" {3,}", " "),
    (r"\n{4,}", "\n\n"),
    (r"^\s*$\n", ""),
    (r"[ \t]+\n", "\n"),
]


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for pattern, replacement in NOISE_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def txt_to_md(content: str, title: str) -> str:
    cleaned = clean_text(content)
    return f"# {title}\n\n{cleaned}\n"


def xml_to_md(content: str, title: str) -> str:
    """Извлекает текстовое содержимое из XML (ISO-платежи и т.д.)."""
    try:
        root = ET.fromstring(content)
        texts = []
        for elem in root.iter():
            if elem.text and elem.text.strip():
                texts.append(elem.text.strip())
            if elem.tail and elem.tail.strip():
                texts.append(elem.tail.strip())
        body = clean_text("\n".join(texts))
    except ET.ParseError:
        body = clean_text(content)
    return f"# {title}\n\n> Источник: XML-документ\n\n{body}\n"


def process_file(src: Path, dst: Path) -> None:
    title = src.stem.strip()
    content = src.read_text(encoding="utf-8", errors="replace")

    if src.suffix.lower() == ".xml":
        md = xml_to_md(content, title)
    else:
        md = txt_to_md(content, title)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(md, encoding="utf-8")
    print(f"  ✓ {src.relative_to(DATA_DIR)} → {dst.relative_to(DATA_DIR)}")


def main() -> None:
    print("Преобразование документов в Markdown...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    extensions = {".txt", ".xml", ".md"}
    count = 0

    for src in sorted(DATA_DIR.rglob("*")):
        if not src.is_file():
            continue
        if src.suffix.lower() not in extensions:
            continue
        if "processed" in src.parts:
            continue

        rel = src.relative_to(DATA_DIR)
        dst = OUTPUT_DIR / rel.with_suffix(".md")
        process_file(src, dst)
        count += 1

    print(f"\nГотово: обработано {count} файлов → {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
