from __future__ import annotations

import re
from bisect import bisect_right

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel

_ENCODING = tiktoken.get_encoding("cl100k_base")
_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(?P<title>.+?)\s*$", re.MULTILINE)


class ChunkMetadata(BaseModel):
    content: str
    source_name: str
    source_url: str
    section_title: str
    chunk_index: int


def _token_length(text: str) -> int:
    return len(_ENCODING.encode(text))


def _extract_headings(content: str) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    for match in _HEADING_PATTERN.finditer(content):
        headings.append((match.start(), match.group("title").strip()))
    return headings


def _detect_section_title(
    chunk_start: int,
    headings: list[tuple[int, str]],
) -> str:
    if not headings:
        return ""

    heading_positions = [position for position, _ in headings]
    heading_index = bisect_right(heading_positions, chunk_start) - 1
    if heading_index < 0:
        return ""
    return headings[heading_index][1]


def chunk_document(
    content: str,
    source_name: str,
    source_url: str,
    section_title: str = "",
) -> list[ChunkMetadata]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=512,
        chunk_overlap=64,
        length_function=_token_length,
        separators=["\n## ", "\n### ", "\n#### ", "\n\n", "\n", " ", ""],
    )

    chunks = splitter.split_text(content)
    headings = _extract_headings(content)
    metadata_chunks: list[ChunkMetadata] = []
    search_start = 0

    for chunk_index, chunk in enumerate(chunks):
        chunk_start = content.find(chunk, search_start)
        if chunk_start == -1:
            chunk_start = content.find(chunk)
        if chunk_start == -1:
            chunk_start = search_start

        detected_section_title = _detect_section_title(chunk_start, headings)
        metadata_chunks.append(
            ChunkMetadata(
                content=chunk,
                source_name=source_name,
                source_url=source_url,
                section_title=detected_section_title or section_title,
                chunk_index=chunk_index,
            )
        )
        search_start = chunk_start + len(chunk)

    return metadata_chunks
