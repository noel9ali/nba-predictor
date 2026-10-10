"""Parser for the official NBA injury report PDF (both the hourly-era and 15-minute-era layouts).

The report is a table: Game Date | Game Time | Matchup | Team | Player Name | Current Status | Reason.
Date, time, matchup and team print only on the first row of a group and carry forward (also across pages).
Reasons wrap onto lines just above and below their player row. Column positions come from the header row
on the first page; we work on word positions (pdfplumber.extract_words) because extract_text drops spaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import config

COLUMNS = ("game_date", "game_time", "matchup", "team", "player", "status", "reason")
_TITLE_RE = re.compile(r"Injury\s*Report:\s*(\d{2}/\d{2}/\d{2,4})\s+(\d{1,2}:\d{2})\s*([AP]M)", re.I)
_PAGE_RE = re.compile(r"^Page\s*\d+\s*of\s*\d+$", re.I)
_NYS = "NOT YET SUBMITTED"
_COL_TOLERANCE = 4.0     # data words can start a little left of their header word
_LINE_TOLERANCE = 2.0


class InjuryReportParseError(ValueError):
    pass


@dataclass
class ParsedReport:
    report_time_et: datetime | None              # naive ET wall time from the header
    rows: list[dict] = field(default_factory=list)
    not_submitted: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _header_columns(words: list[dict]) -> tuple[dict[str, float], float] | None:
    by_text: dict[str, list[dict]] = {}
    for w in words:
        by_text.setdefault(w["text"].strip().lower(), []).append(w)
    if "matchup" not in by_text or "reason" not in by_text:
        return None
    m = by_text["matchup"][0]
    top = m["top"]
    same_line = [w for w in words if abs(w["top"] - top) <= _LINE_TOLERANCE]

    def x_of(*names):
        for w in sorted(same_line, key=lambda w: w["x0"]):
            t = w["text"].strip().lower()
            if any(t == n or t.startswith(n) for n in names):
                return w["x0"]
        return None

    games = sorted([w for w in same_line if w["text"].strip().lower().startswith("game")], key=lambda w: w["x0"])
    cols = {
        "game_date": 0.0,
        "game_time": games[1]["x0"] if len(games) > 1 else None,
        "matchup": m["x0"],
        "team": x_of("team"),
        "player": x_of("player"),
        "status": x_of("current"),
        "reason": x_of("reason"),
    }
    if any(v is None for v in cols.values()):
        return None
    bottom = max(w["bottom"] for w in same_line)
    return cols, bottom


def _column_of(x0: float, cols: dict[str, float]) -> str:
    chosen = COLUMNS[0]
    for name in COLUMNS:
        if x0 >= cols[name] - _COL_TOLERANCE:
            chosen = name
    return chosen


def _group_lines(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= _LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
    return lines


def parse_title(text: str) -> datetime | None:
    m = _TITLE_RE.search(text)
    if not m:
        return None
    d, t, ampm = m.groups()
    fmt = "%m/%d/%y" if len(d.split("/")[-1]) == 2 else "%m/%d/%Y"
    day = datetime.strptime(d, fmt).date()
    clock = datetime.strptime(f"{t} {ampm.upper()}", "%I:%M %p").time()
    return datetime.combine(day, clock)


def parse_pages(pages_words: list[list[dict]]) -> ParsedReport:
    """Parse a report from per-page word lists (dicts with text, x0, x1, top, bottom)."""
    report = ParsedReport(report_time_et=None)
    cols = None
    anchors: list[dict] = []
    for page_no, words in enumerate(pages_words):
        title_words = [w for w in words if w["top"] < 80 or "report" in w["text"].lower()]
        if report.report_time_et is None:
            for line in _group_lines(title_words):
                parsed = parse_title(" ".join(w["text"] for w in line))
                if parsed:
                    report.report_time_et = parsed
                    break
        start_below = None
        header = _header_columns(words)
        if header:
            if cols is None:
                cols = header[0]
            start_below = header[1]
        if cols is None:
            report.warnings.append(f"page {page_no + 1}: no header row before data; page skipped")
            continue
        page_anchors: list[dict] = []
        fragments: list[tuple[float, str, float, str]] = []
        for line in _group_lines(words):
            text = " ".join(w["text"] for w in line).strip()
            top = line[0]["top"]
            if start_below is not None and top <= start_below:
                continue
            if _TITLE_RE.search(text) or _PAGE_RE.match(text.replace(" ", " ")) or re.match(r"^Page\s*\d+\s*of\s*\d+", text, re.I):
                continue
            cells: dict[str, list[dict]] = {}
            for w in line:
                cells.setdefault(_column_of(w["x0"], cols), []).append(w)
            joined = {k: " ".join(w["text"] for w in sorted(v, key=lambda w: w["x0"])).strip() for k, v in cells.items()}
            is_nys = _NYS in " ".join(joined.values()).upper().replace("  ", " ")
            if joined.get("status") or (is_nys and not joined.get("player")):
                anchor = {"page": page_no, "top": top, "nys": bool(is_nys and not joined.get("status")),
                          "cells": {k: [(top, v)] for k, v in joined.items()}}
                page_anchors.append(anchor)
            else:
                for k, v in joined.items():
                    fragments.append((top, k, line[0]["x0"], v))
        if not page_anchors:
            if fragments:
                report.warnings.append(f"page {page_no + 1}: {len(fragments)} text fragments without a player row")
            continue
        for top, col, _x, text in fragments:
            nearest = min(page_anchors, key=lambda a: (abs(a["top"] - top), a["top"] < top))
            nearest["cells"].setdefault(col, []).append((top, text))
        anchors.extend(page_anchors)

    if cols is None:
        raise InjuryReportParseError("no header row found (layout changed?)")

    current = {"game_date": None, "game_time": None, "matchup": None, "team": None}
    for a in anchors:
        cell = {k: " ".join(t for _top, t in sorted(v)) .strip() for k, v in a["cells"].items()}
        if cell.get("matchup"):
            current.update(game_date=current["game_date"], matchup=cell["matchup"].replace(" ", ""), team=None)
        if cell.get("game_date"):
            current["game_date"] = cell["game_date"]
        if cell.get("game_time"):
            current["game_time"] = cell["game_time"]
        if cell.get("team"):
            current["team"] = cell["team"]
        if a["nys"]:
            report.not_submitted.append(dict(current))
            continue
        player = cell.get("player", "")
        if not player:
            report.warnings.append(f"row without player name: {cell}")
            continue
        row = dict(current)
        row.update(player=player, status=cell.get("status", ""), reason=cell.get("reason") or None)
        report.rows.append(row)
    return report


def parse_pdf(path: str) -> ParsedReport:
    import pdfplumber  # pipeline-only dependency

    pages_words = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages_words.append(page.extract_words(x_tolerance=1.5, keep_blank_chars=False))
    return parse_pages(pages_words)


def parse_game_date(text: str | None) -> date | None:
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Slot names (URL timestamps, ET)
# ---------------------------------------------------------------------------

def _ampm(hour24: int) -> tuple[int, str]:
    suffix = "AM" if hour24 < 12 else "PM"
    hour12 = hour24 % 12 or 12
    return hour12, suffix


def slot_names(dt_et: datetime) -> list[str]:
    """URL slot names to try for an ET wall time; both formats around the late-2025 switch."""
    hour12, suffix = _ampm(dt_et.hour)
    d = dt_et.date().isoformat()
    hourly = f"{d}_{hour12:02d}{suffix}"
    quarter = f"{d}_{hour12:02d}_{dt_et.minute // 15 * 15:02d}{suffix}"
    switch = date.fromisoformat(config.INJURY_15MIN_SLOTS_FROM)
    if dt_et.date() >= switch + timedelta(days=5):
        return [quarter]
    if dt_et.date() < switch - timedelta(days=2):
        return [hourly] if dt_et.minute == 0 else []
    names = [quarter]
    if dt_et.minute == 0:
        names.append(hourly)
    return names


def slot_time_from_name(name: str) -> datetime | None:
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(\d{2})(?:_(\d{2}))?([AP]M)$", name)
    if not m:
        return None
    d, hh, mm, ampm = m.groups()
    clock = datetime.strptime(f"{hh}:{mm or '00'} {ampm}", "%I:%M %p").time()
    return datetime.combine(date.fromisoformat(d), clock)
