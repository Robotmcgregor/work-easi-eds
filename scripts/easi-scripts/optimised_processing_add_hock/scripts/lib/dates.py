from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date, datetime
import re
from dateutil.relativedelta import relativedelta


def normalise_yyyymmdd(value) -> str:
    """Return an 8-digit YYYYMMDD string from common date representations.

    Accepts:
    - int/np.int64 like 20220101
    - datetime/date
    - strings like "20220101", "2022-01-01", "2022-01-01 00:00:00"
    """
    if value is None:
        raise ValueError("date is None")

    if isinstance(value, (datetime, _date)):
        return value.strftime('%Y%m%d')

    if isinstance(value, int):
        return f"{value:08d}"

    # numpy scalar ints aren't instances of int on some versions
    try:
        if hasattr(value, 'dtype') and str(getattr(value, 'dtype', '')).startswith('int'):
            return f"{int(value):08d}"
    except Exception:
        pass

    s = str(value).strip()
    if re.fullmatch(r"\d{8}", s):
        return s

    m = re.match(r"^(\d{4})[-/](\d{2})[-/](\d{2})", s)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"

    digits = re.sub(r"\D", "", s)
    if len(digits) >= 8:
        return digits[:8]

    raise ValueError(f"Could not normalise date to YYYYMMDD from: {value!r}")


def yyyymmdd_to_date(d: str) -> datetime:
    d = d.strip()
    if '-' in d:
        return datetime.strptime(d, '%Y-%m-%d')
    return datetime.strptime(d, '%Y%m%d')


def date_to_yyyymmdd(dt: datetime) -> str:
    return dt.strftime('%Y%m%d')


def shift_months_yyyymmdd(d: str, months: int) -> str:
    """Shift a YYYYMMDD/ISO date by N calendar months (keeps day-of-month where possible)."""
    dt = yyyymmdd_to_date(d)
    return date_to_yyyymmdd(dt + relativedelta(months=months))


@dataclass(frozen=True)
class SeasonalWindow:
    """Seasonal window expressed as MMDD bounds (inclusive), allowing wrap over new year."""

    window_start_mmdd: str  # e.g. '0817'
    window_end_mmdd: str    # e.g. '0417'

    @staticmethod
    def from_start_end(start_yyyymmdd: str, end_yyyymmdd: str, expand_months: int = 2) -> 'SeasonalWindow':
        s2 = shift_months_yyyymmdd(start_yyyymmdd, -expand_months)
        e2 = shift_months_yyyymmdd(end_yyyymmdd, +expand_months)
        return SeasonalWindow(window_start_mmdd=s2[4:], window_end_mmdd=e2[4:])

    def in_window(self, yyyymmdd: str) -> bool:
        mmdd = yyyymmdd[4:]
        ws = self.window_start_mmdd
        we = self.window_end_mmdd
        if ws <= we:
            return ws <= mmdd <= we
        # wraps across new year (e.g. Aug->Apr)
        return (mmdd >= ws) or (mmdd <= we)

    def months_hint(self) -> str:
        """Human hint for logs."""
        ws_m = int(self.window_start_mmdd[:2])
        we_m = int(self.window_end_mmdd[:2])
        if ws_m <= we_m:
            return f"{ws_m:02d}..{we_m:02d}"
        return f"{ws_m:02d}..12,01..{we_m:02d}"
