import re
import json

_SENTENCE_RE = re.compile(r"(?<=[.!?。])\s+")
_HEADING_RE = re.compile(r"^#{1,6}\s+\S")


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_RE.split(text)
    return [p for p in parts if p.strip()]


def split_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    strategy: str = "sliding-window",
) -> list[str]:
    if strategy == "heading-aware":
        return _split_heading_aware(text, chunk_size=chunk_size, overlap=overlap)
    if strategy == "log-window":
        return _split_lines(text, max_lines=40, overlap_lines=5)
    if strategy == "table-row":
        return _split_table_rows(text, chunk_size=chunk_size)
    if strategy == "json-object":
        return _split_json_objects(text, chunk_size=chunk_size, overlap=overlap)
    return _split_sliding_window(text, chunk_size=chunk_size, overlap=overlap)


def _split_sliding_window(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    if not text.strip():
        return []

    paragraphs = text.split("\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) + 1 <= chunk_size:
            current_chunk += ("\n" + para) if current_chunk else para
        else:
            if current_chunk:
                chunks.append(current_chunk)
            if len(para) > chunk_size:
                sentences = _split_sentences(para)
                if len(sentences) > 1:
                    buf = ""
                    for sent in sentences:
                        if len(buf) + len(sent) + 1 <= chunk_size:
                            buf += (" " + sent) if buf else sent
                        else:
                            if buf:
                                chunks.append(buf)
                            buf = sent
                    current_chunk = buf if buf else ""
                else:
                    words = para
                    while len(words) > chunk_size:
                        split_point = words[:chunk_size].rfind(" ")
                        if split_point == -1:
                            split_point = chunk_size
                        chunks.append(words[:split_point])
                        words = words[max(0, split_point - overlap):]
                    current_chunk = words
            else:
                # Start new chunk with overlap from previous
                if chunks:
                    prev = chunks[-1]
                    overlap_text = prev[-overlap:] if len(prev) > overlap else prev
                    current_chunk = overlap_text + "\n" + para
                else:
                    current_chunk = para

    if current_chunk.strip():
        chunks.append(current_chunk)

    return [c for c in chunks if c.strip()]


def _split_heading_aware(text: str, chunk_size: int, overlap: int) -> list[str]:
    sections: list[str] = []
    current: list[str] = []

    for line in text.splitlines():
        if _HEADING_RE.match(line.strip()) and current:
            sections.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)

    if current:
        sections.append("\n".join(current).strip())

    if not any(_HEADING_RE.match(section.splitlines()[0].strip()) for section in sections if section):
        return _split_sliding_window(text, chunk_size=chunk_size, overlap=overlap)

    chunks: list[str] = []
    for section in sections:
        if not section.strip():
            continue
        if len(section) <= chunk_size:
            chunks.append(section)
        else:
            chunks.extend(_split_sliding_window(section, chunk_size=chunk_size, overlap=overlap))
    return chunks


def _split_lines(text: str, max_lines: int, overlap_lines: int) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(lines):
        end = min(len(lines), start + max_lines)
        chunks.append("\n".join(lines[start:end]))
        if end == len(lines):
            break
        start = max(0, end - overlap_lines)
    return chunks


def _split_table_rows(text: str, chunk_size: int) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    header = lines[0]
    chunks: list[str] = []
    current = header
    for row in lines[1:]:
        candidate = f"{current}\n{row}" if current else row
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current.strip():
                chunks.append(current)
            current = f"{header}\n{row}" if row != header else row
    if current.strip():
        chunks.append(current)
    return chunks


def _split_json_objects(text: str, chunk_size: int, overlap: int) -> list[str]:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return _split_sliding_window(text, chunk_size=chunk_size, overlap=overlap)

    if isinstance(parsed, list):
        chunks = [json.dumps(item, ensure_ascii=False, indent=2) for item in parsed]
    elif isinstance(parsed, dict):
        chunks = [
            json.dumps({key: value}, ensure_ascii=False, indent=2)
            for key, value in parsed.items()
        ]
    else:
        chunks = [json.dumps(parsed, ensure_ascii=False, indent=2)]

    result: list[str] = []
    for chunk in chunks:
        if len(chunk) <= chunk_size:
            result.append(chunk)
        else:
            result.extend(_split_sliding_window(chunk, chunk_size=chunk_size, overlap=overlap))
    return result
