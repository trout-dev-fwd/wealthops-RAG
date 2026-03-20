"""Parse tiptap JSON bodies into chunk dicts for the knowledge DB.

Supports two formats found in the WealthOps Circle.so posts:

  Format A (newer, ~March 2026): h2/h3 headings + paragraph content
  Format B (older, ~Oct 2025 - Jan 2026): bulletList + listItem paragraphs
"""

import re

# H2 headings that are structural (no content chunk)
_STRUCTURAL_H2 = frozenset({"Discussion Topics", "Key Search Terms"})

# (Speaker Name): at start of paragraph segment
_SPEAKER_A_RE = re.compile(r'\(([^)]+)\):', re.UNICODE)

# Timestamp prefix on h3 headings: "01:08 Some Topic" or "1:01:41 Some Topic"
_TS_PREFIX_RE = re.compile(r'^(\d+:\d+(?::\d+)?)\s+(.+)$')

# Inline timestamp text inside a link node: "00:02:59" or "01:23"
_TS_INLINE_RE = re.compile(r'^\d{1,2}:\d{2}(?::\d{2})?$')

# Proper names at sentence boundaries in Format B content text.
# Matches: start-of-string (with optional whitespace), or after [.!?] + whitespace,
# or after ")." + whitespace (timestamp reference close).
# Pattern: two words, first has 1+ lowercase letters (e.g. "Christopher"),
# second may be single capital (e.g. "H" in "Ken H").
_NAME_B_RE = re.compile(
    r'(?:^\s*|[.!?]\s+|\)\.\s+)([A-Z][a-z]+ [A-Z][a-z]*)',
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _text_content(nodes):
    """Concatenate plain text from a flat list of inline nodes."""
    return "".join(n.get("text", "") for n in nodes if n.get("type") == "text")


def _heading_text(node):
    return _text_content(node.get("content", []))


def _strip_ts_prefix(text):
    """Return (timestamp_str_or_None, clean_heading_text)."""
    m = _TS_PREFIX_RE.match(text.strip())
    if m:
        return m.group(1), m.group(2).strip()
    return None, text.strip()


def _para_text_a(para_node):
    """Full text of a Format A paragraph (all inline nodes concatenated)."""
    return _text_content(para_node.get("content", []))


def _para_text_b(para_node):
    """Content text for Format B: skip the first bold node (heading) and link nodes."""
    parts = []
    first_bold_skipped = False
    for node in para_node.get("content", []):
        if node.get("type") != "text":
            continue
        marks = {m.get("type") for m in node.get("marks", [])}
        if "bold" in marks and not first_bold_skipped:
            first_bold_skipped = True
            continue
        if "link" in marks:
            continue
        parts.append(node.get("text", ""))
    return "".join(parts)


def _bold_heading_b(para_node):
    """First bold text node in a Format B paragraph → topic heading."""
    for node in para_node.get("content", []):
        if node.get("type") == "text":
            marks = {m.get("type") for m in node.get("marks", [])}
            if "bold" in marks:
                text = node.get("text", "").strip()
                if text:
                    return text
    return None


def _timestamps_b(para_node):
    """Timestamps from link-marked text nodes (e.g. '00:02:59')."""
    ts = []
    for node in para_node.get("content", []):
        if node.get("type") != "text":
            continue
        marks = {m.get("type") for m in node.get("marks", [])}
        if "link" in marks:
            text = node.get("text", "").strip()
            if _TS_INLINE_RE.match(text):
                ts.append(text)
    return ts


def _speakers_a(para_nodes):
    """Extract speakers from Format A paragraphs.

    Primary: (Name): pattern in paragraph text.
    Fallback: bold text nodes whose name isn't already a substring of a primary match.
    """
    named = []
    bold = []
    for para in para_nodes:
        full = _para_text_a(para)
        for name in _SPEAKER_A_RE.findall(full):
            name = name.strip()
            if name and name not in named:
                named.append(name)
        for node in para.get("content", []):
            if node.get("type") == "text":
                marks = {m.get("type") for m in node.get("marks", [])}
                if "bold" in marks and "link" not in marks:
                    name = node.get("text", "").strip()
                    if name and name not in bold:
                        bold.append(name)

    result = list(named)
    for b in bold:
        if not any(b in full_name for full_name in named):
            if b not in result:
                result.append(b)
    return result


def _speakers_b(content_text):
    """Extract speaker names from Format B content using sentence-boundary heuristic."""
    speakers = []
    for m in _NAME_B_RE.finditer(content_text):
        name = m.group(1).strip()
        if name and name not in speakers:
            speakers.append(name)
    return speakers


# ---------------------------------------------------------------------------
# Format parsers
# ---------------------------------------------------------------------------

def _parse_format_a(nodes, call_title, call_url):
    chunks = []
    cur_heading = None
    cur_timestamp = None
    cur_paras = []
    skip_zone = False  # True after "Key Search Terms" h2

    def _flush():
        if cur_heading is None:
            return
        content = "\n\n".join(
            _para_text_a(p) for p in cur_paras
        )
        chunks.append({
            "topic_heading": cur_heading,
            "content": content,
            "speakers": _speakers_a(cur_paras),
            "timestamps": [cur_timestamp] if cur_timestamp else [],
        })

    for node in nodes:
        ntype = node.get("type")

        if ntype == "file":
            continue

        if ntype == "heading":
            level = node.get("attrs", {}).get("level", 0)
            text = _heading_text(node)

            if level == 2:
                _flush()
                cur_heading = None
                cur_paras = []
                cur_timestamp = None
                if text == "Key Search Terms":
                    skip_zone = True
                continue

            if level == 3 and not skip_zone:
                _flush()
                ts, heading = _strip_ts_prefix(text)
                cur_heading = heading
                cur_timestamp = ts
                cur_paras = []
                continue

        if ntype == "paragraph" and cur_heading is not None and not skip_zone:
            if _para_text_a(node).strip():
                cur_paras.append(node)

    _flush()
    return chunks


def _parse_format_b(nodes, call_title, call_url):
    chunks = []

    for node in nodes:
        if node.get("type") != "bulletList":
            continue

        for item in node.get("content", []):
            if item.get("type") != "listItem":
                continue

            para = next(
                (c for c in item.get("content", []) if c.get("type") == "paragraph"),
                None,
            )
            if para is None:
                continue

            heading = _bold_heading_b(para)
            content = _para_text_b(para).strip()

            if not heading:
                heading = content[:60].rstrip() if content else "Untitled"

            if not content:
                continue

            chunks.append({
                "topic_heading": heading,
                "content": content,
                "speakers": _speakers_b(content),
                "timestamps": _timestamps_b(para),
            })

    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_tiptap_to_chunks(tiptap_body: dict, call_title: str, call_url: str) -> list:
    """Parse a tiptap doc dict into chunk dicts.

    Args:
        tiptap_body: The tiptap doc dict (``{"type": "doc", "content": [...]}``)
        call_title:  Human-readable title of the call (stored with each chunk)
        call_url:    URL of the call recording post

    Returns:
        List of dicts, each with keys:
            topic_heading (str), content (str),
            speakers (list[str]), timestamps (list[str])
    """
    nodes = tiptap_body.get("content", [])

    has_bullet_list = any(n.get("type") == "bulletList" for n in nodes)
    if has_bullet_list:
        return _parse_format_b(nodes, call_title, call_url)
    return _parse_format_a(nodes, call_title, call_url)
