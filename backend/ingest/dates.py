"""Date handling. Every format found in the export has one rule here.

Raw format                              -> stored as
--------------------------------------------------------------------------------------
JSON  'YYYY-MM-DDTHH:MM:SS'             -> ISO + New York offset      (rule 'iso')
CSV   'YYYY-MM-DD HH:MM'                -> ISO + New York offset      (rule 'iso')
CSV   'DD/MM/YYYY HH:MM'  (24-hour)     -> ISO + New York offset      (rule 'ddmm_24h', inferred, audit P07)
CSV   'MM/DD/YYYY H:MM AM|PM'           -> ISO + New York offset      (rule 'mmdd_ampm', inferred, audit P07)
'YYYY-MM-DD' (date only)                -> plain date, no offset      (no time of day exists, none is invented)
email 'Date:' (RFC 2822, -0400)         -> converted to New York time, ISO + offset
empty                                   -> NULL
anything else                           -> ValueError (the build stops; nothing is guessed)
"""
import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from backend import config
from .normalize import nn

NY = ZoneInfo(config.TIMEZONE)

_LOCAL = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$")
_SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4}) (\d{1,2}):(\d{2})(?: ?([AaPp][Mm]))?$")


def iso_ny(naive: datetime) -> str:
    """Attach the New York offset (DST-aware) and format as ISO 8601."""
    return naive.replace(tzinfo=NY).isoformat(timespec="seconds")


def json_datetime(value):
    """JSON datetime field -> ISO with offset, or None if empty."""
    s = nn(value)
    if s is None:
        return None
    if not _LOCAL.match(s):
        raise ValueError(f"unexpected datetime format: {s!r}")
    return iso_ny(datetime.fromisoformat(s.replace(" ", "T")))


def plain_date(value):
    """Date-only field -> 'YYYY-MM-DD' (validated), or None if empty."""
    s = nn(value)
    return None if s is None else date.fromisoformat(s).isoformat()


def event_datetime(raw):
    """stage_events.csv date -> (iso_with_offset | None, rule | None)."""
    s = nn(raw)
    if s is None:
        return None, None
    if _LOCAL.match(s):
        return iso_ny(datetime.fromisoformat(s.replace(" ", "T"))), "iso"
    m = _SLASH.match(s)
    if not m:
        raise ValueError(f"unexpected date format: {s!r}")
    a, b, year, hour, minute, ampm = m.groups()
    if ampm:                                   # 12-hour clock -> MM/DD/YYYY
        rule, month, day = "mmdd_ampm", int(a), int(b)
        hour = int(hour) % 12 + (12 if ampm.lower() == "pm" else 0)
    else:                                      # 24-hour clock -> DD/MM/YYYY
        rule, day, month = "ddmm_24h", int(a), int(b)
        hour = int(hour)
    return iso_ny(datetime(int(year), month, day, hour, int(minute))), rule


def email_datetime(header):
    """Email 'Date:' header -> ISO in New York time."""
    return parsedate_to_datetime(str(header)).astimezone(NY).isoformat(timespec="seconds")


def parse_iso(s):
    """Stored ISO string -> datetime (aware, or midnight for a plain date)."""
    return datetime.fromisoformat(s)


def date_of(s):
    """Calendar date (New York) of a stored ISO string or plain date."""
    return datetime.fromisoformat(s).date()
