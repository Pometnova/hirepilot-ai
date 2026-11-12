"""Markdown -> Slack mrkdwn. Pure text functions: no Slack calls, no business logic.

Slack does not know markdown headings, tables, **bold** or [text](url). This converts them:
  **bold** / __bold__ -> *bold*       *italic* -> _italic_       # Heading -> *Heading*
  FACTS / AI ASSESSMENT / CAVEATS lines -> bold                   - item -> bullet
  | table | rows |   -> a code block (Slack has no tables)       [text](url) -> <url|text>
  & < > are escaped, code blocks are left as they are, and long answers are split into several messages.
"""
import re

MAX_CHARS = 3500                       # per message; Slack handles more, but long blocks get hard to read
_SECTION = re.compile(r"^(FACTS|AI ASSESSMENT|CAVEATS)\b.*$", re.I)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITALIC = re.compile(r"(?<![\w*])\*(?![\s*])([^*\n]+?)(?<![\s*])\*(?![\w*])")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_RULE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_BOLD_MARK = "\x00"


def escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(line):
    """Inline conversions on one already-escaped line. Inline `code` is protected."""
    parts = re.split(r"(`[^`\n]+`)", line)
    for i in range(0, len(parts), 2):                       # even parts are outside backticks
        p = parts[i]
        p = _BOLD.sub(lambda m: f"{_BOLD_MARK}{m.group(2)}{_BOLD_MARK}", p)
        p = _ITALIC.sub(r"_\1_", p)
        p = p.replace(_BOLD_MARK, "*")
        p = _STRIKE.sub(r"~\1~", p)
        p = _LINK.sub(lambda m: f"<{m.group(2)}|{m.group(1)}>", p)
        parts[i] = p
    return "".join(parts)


def to_mrkdwn(markdown):
    out, table, in_code = [], [], False

    def flush_table():
        if table:
            out.append("```\n" + "\n".join(table) + "\n```")
            table.clear()

    for raw in (markdown or "").replace("\r\n", "\n").split("\n"):
        if raw.strip().startswith("```"):                   # code fence: copy through, no conversion inside
            flush_table()
            in_code = not in_code
            out.append("```")
            continue
        line = escape(raw)
        if in_code:
            out.append(line)
            continue
        if _TABLE_ROW.match(raw):
            table.append(line.strip())
            continue
        flush_table()
        if _RULE.match(raw):
            out.append("")
            continue
        h = _HEADING.match(line)
        if h:
            out.append(f"*{_inline(h.group(1)).replace('*', '')}*")
            continue
        if _SECTION.match(line.strip()) and "*" not in line:
            out.append(f"*{line.strip()}*")
            continue
        b = _BULLET.match(line)
        if b:
            indent = b.group(1)
            out.append(f"{indent}{'•' if len(indent) < 2 else '◦'} {_inline(b.group(2))}")
            continue
        out.append(_inline(line))
    flush_table()
    if in_code:
        out.append("```")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def split_message(text, limit=MAX_CHARS):
    """Split at line boundaries. A code block cut in the middle is closed, and reopened in the next part."""
    if len(text) <= limit:
        return [text]
    parts, cur, in_code = [], "", False
    for line in text.split("\n"):
        while len(line) > limit:                            # one very long line: cut it
            head, line = line[:limit], line[limit:]
            if cur:
                parts.append(cur + ("\n```" if in_code else ""))
                cur = "```\n" if in_code else ""
            parts.append(head)
        extra = len(line) + 1 + (4 if in_code else 0)
        if cur and len(cur) + extra > limit:
            parts.append(cur + ("\n```" if in_code else ""))
            cur = "```\n" if in_code else ""
        cur = f"{cur}\n{line}" if cur else line
        if line.strip().startswith("```"):
            in_code = not in_code
    if cur.strip():
        parts.append(cur)
    return [p for p in parts if p.strip()]
