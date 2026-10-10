"""Player name normalization and matching (injury report now, prop odds later).

`normalize_name` is the single normalizer used everywhere (and for seeding `player_aliases` in phase 1).
`NameResolver` resolves a raw provider name to an nba_api player_id. It is built from candidate rows
(`name`, `player_id`, optional `team_id`, optional `is_active`), which today come from a locally
cached nba_api CommonAllPlayers list and later from the `player_aliases` table, without changing callers.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_SPECIAL_FOLDS = str.maketrans({
    "ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "æ": "ae", "Æ": "AE",
    "ß": "ss", "ı": "i", "œ": "oe", "Œ": "OE", "þ": "th",
})


def fold_accents(text: str) -> str:
    text = text.translate(_SPECIAL_FOLDS)
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def to_first_last(name: str) -> str:
    """'Moore Jr., Wendell' -> 'Wendell Moore Jr.'; names without a comma are returned unchanged."""
    name = " ".join(str(name).split())
    if "," not in name:
        return name
    last, first = name.rsplit(",", 1)
    first, last = first.strip(), last.strip().rstrip(",").strip()
    if not first:
        return last
    return f"{first} {last}"


def normalize_name(name: str | None) -> str:
    """Lowercase, 'Last, First' -> 'first last', accents folded, punctuation and Jr./III suffixes removed."""
    if name is None:
        return ""
    text = fold_accents(to_first_last(str(name))).lower()
    text = re.sub(r"[.'`’]", "", text)        # T.J. -> tj, De'Andre -> deandre
    text = re.sub(r"[^a-z0-9]+", " ", text)         # hyphens, commas, anything else -> space
    tokens = [t for t in text.split() if t]
    while len(tokens) > 1 and tokens[-1] in SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def compact_key(name: str | None) -> str:
    return normalize_name(name).replace(" ", "")


@dataclass(frozen=True)
class Candidate:
    name: str
    player_id: int
    team_id: int | None = None
    is_active: bool = True


@dataclass(frozen=True)
class Match:
    player_id: int | None
    method: str          # 'exact', 'compact', 'initial_team', 'ambiguous', 'unmatched'


class NameResolver:
    def __init__(self, candidates: Iterable[Candidate]):
        self._by_key: dict[str, list[Candidate]] = defaultdict(list)
        self._by_compact: dict[str, list[Candidate]] = defaultdict(list)
        self._by_team: dict[int, list[Candidate]] = defaultdict(list)
        for cand in candidates:
            key = normalize_name(cand.name)
            if not key:
                continue
            self._by_key[key].append(cand)
            self._by_compact[key.replace(" ", "")].append(cand)
            if cand.team_id is not None:
                self._by_team[int(cand.team_id)].append(cand)

    @classmethod
    def from_rows(cls, rows: Iterable[dict], *, name_col="name", id_col="player_id",
                  team_col="team_id", active_col="is_active") -> "NameResolver":
        cands = []
        for row in rows:
            team = row.get(team_col)
            try:
                team = int(team) if team not in (None, "", 0) else None
            except (TypeError, ValueError):
                team = None
            cands.append(Candidate(str(row[name_col]), int(row[id_col]), team,
                                   bool(row.get(active_col, True))))
        return cls(cands)

    @staticmethod
    def _pick(cands: list[Candidate], team_id: int | None) -> int | None:
        ids = {c.player_id for c in cands}
        if len(ids) == 1:
            return next(iter(ids))
        if team_id is not None:
            on_team = {c.player_id for c in cands if c.team_id == team_id}
            if len(on_team) == 1:
                return next(iter(on_team))
        active = {c.player_id for c in cands if c.is_active}
        if len(active) == 1:
            return next(iter(active))
        return None

    def resolve(self, raw_name: str, team_id: int | None = None) -> Match:
        key = normalize_name(raw_name)
        if not key:
            return Match(None, "unmatched")
        for table, method, k in ((self._by_key, "exact", key),
                                 (self._by_compact, "compact", key.replace(" ", ""))):
            cands = table.get(k)
            if cands:
                pid = self._pick(cands, team_id)
                return Match(pid, method) if pid is not None else Match(None, "ambiguous")
        # Last resort: same team, same last name, same first initial, unique.
        if team_id is not None and " " in key:
            first, last = key.split(" ", 1)
            hits = {c.player_id for c in self._by_team.get(int(team_id), [])
                    if normalize_name(c.name).endswith(" " + last)
                    and normalize_name(c.name)[:1] == first[:1]}
            if len(hits) == 1:
                return Match(next(iter(hits)), "initial_team")
        return Match(None, "unmatched")
