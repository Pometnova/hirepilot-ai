"""Small helpers: empty -> NULL, matching keys, raw file reading, CV text, hashing.
Raw files are only ever opened for reading."""
import hashlib
import json
import re
from pathlib import Path

from backend import config

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
PHONE_RE = re.compile(r"\+?\d[\d\- ()]{8,}\d")


def nn(value):
    """Empty or whitespace-only -> None. Other values are returned unchanged."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def norm_email(s):
    """Lowercase and strip '+tag'. For matching only."""
    s = s.strip().lower()
    local, _, domain = s.partition("@")
    return local.split("+")[0] + "@" + domain


def norm_phone(s):
    return re.sub(r"\D", "", s)


def norm_name(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def read_json(name):
    with open(config.RAW_DIR / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def insert(con, table, row):
    cols = ", ".join(row)
    marks = ", ".join("?" * len(row))
    con.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))


def extract_cv_text(path: Path):
    """Return (format, text | None, status, error | None). Never raises on a bad file."""
    fmt = path.suffix.lower().lstrip(".")
    if fmt not in ("pdf", "docx", "txt"):
        raise ValueError(f"unsupported CV format: {path.name}")
    try:
        if fmt == "pdf":
            import pypdf
            text = "\n".join((pg.extract_text() or "") for pg in pypdf.PdfReader(str(path)).pages)
        elif fmt == "docx":
            import docx
            text = "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
        else:
            text = path.read_text(encoding="utf-8")
    except Exception as e:  # recorded, not hidden
        return fmt, None, "failed", f"{type(e).__name__}: {e}"
    if not text.strip():
        return fmt, None, "empty", "no text extracted"
    return fmt, text, "ok", None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def raw_file_hashes() -> dict:
    """{relative path: sha256} for every file under data/raw/."""
    root = config.RAW_DIR
    return {str(p.relative_to(config.ROOT)): sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file()}


def raw_checksum() -> str:
    """sha256 of the '<hash>  <path>' lines, sorted by path in plain byte order.
    NOT the same number as the audit's shell value: the shell sorts by locale (it ignores
    punctuation), this sorts by bytes. Both are stable for unchanged files."""
    lines = [f"{h}  {p}" for p, h in sorted(raw_file_hashes().items(), key=lambda kv: kv[0])]
    return hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()
