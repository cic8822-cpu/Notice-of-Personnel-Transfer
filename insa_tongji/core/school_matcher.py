import re
from collections import defaultdict
from dataclasses import dataclass

from .normalizer import clean, compact

LEVEL_SUFFIXES = (("초등학교", "초"), ("중학교", "중"), ("고등학교", "고"), ("유치원", "유"))
PAREN_RE = re.compile(r"[(\[（][^)\]）]*[)\]）]")
REGION_LEN = 2
REGION_SHARE = 0.5
MIN_FUZZY_LEN = 3
MAX_SUGGESTIONS = 5
CONFIRMED = {"exact", "alias", "auto", "selected", "manual"}


@dataclass(frozen=True)
class MatchResult:
    status: str
    value: str = ""
    candidates: tuple[str, ...] = ()
    basis: str = ""

    @property
    def confirmed(self) -> bool:
        return self.status in CONFIRMED


def detect_region_prefix(schools: list[str]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for name in schools:
        if len(name) > REGION_LEN:
            counts[name[:REGION_LEN]] += 1
    if not counts:
        return ""
    prefix, hits = max(counts.items(), key=lambda kv: kv[1])
    return prefix if hits / len(schools) >= REGION_SHARE else ""


def drop_prefix(text: str, prefix: str) -> str:
    return text[len(prefix) :] if prefix and text.startswith(prefix) and len(text) > len(prefix) else text


LEVEL_TOKENS = {token for pair in LEVEL_SUFFIXES for token in pair}


def school_keys(name: str, prefix: str = "") -> set[str]:
    keys = {name}
    leveled = False
    for full, short in LEVEL_SUFFIXES:
        if name.endswith(full):
            keys.add(name[: -len(full)] + short)
            leveled = True
    if leveled:
        keys |= {drop_prefix(key, prefix) for key in keys}
    return keys - LEVEL_TOKENS


def school_base(name: str, prefix: str = "") -> str:
    base = name
    for full, _ in LEVEL_SUFFIXES:
        if base.endswith(full):
            base = base[: -len(full)]
            break
    return drop_prefix(base, prefix)


def edit_distance(a: str, b: str, limit: int = 2) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def normalize_school_text(raw) -> str:
    return compact(PAREN_RE.sub("", clean(raw)))


class SchoolMatcher:
    def __init__(self, schools: list[str], aliases: dict[str, str] | None = None, region_prefix: str | None = None):
        self.schools = list(dict.fromkeys(s for s in (compact(x) for x in schools) if s))
        self.region_prefix = detect_region_prefix(self.schools) if region_prefix is None else compact(region_prefix)
        self._school_set = set(self.schools)
        self.aliases = {}
        for key, value in (aliases or {}).items():
            k, v = compact(key), compact(value)
            if k and v in self._school_set:
                self.aliases[k] = v
        self._keys: dict[str, set[str]] = defaultdict(set)
        self._bases: dict[str, set[str]] = defaultdict(set)
        self._school_keys: dict[str, set[str]] = {}
        for school in self.schools:
            self._school_keys[school] = school_keys(school, self.region_prefix)
            for key in self._school_keys[school]:
                self._keys[key].add(school)
            self._bases[school_base(school, self.region_prefix)].add(school)
        self.collisions = {k: sorted(v) for k, v in self._keys.items() if len(v) > 1}

    def match(self, raw) -> MatchResult:
        full = compact(clean(raw))
        if full in self._school_set:
            return MatchResult("exact", full, basis="S1")
        result = self._match_text(normalize_school_text(raw))
        if result.confirmed and full != result.value and full not in self.aliases and PAREN_RE.search(clean(raw)):
            return MatchResult("suggest", candidates=(result.value,), basis="S4:괄호")
        return result

    def _match_text(self, text: str) -> MatchResult:
        if not text:
            return MatchResult("unregistered", basis="S5")
        if text in self._school_set:
            return MatchResult("exact", text, basis="S1")
        if text in self.aliases:
            return MatchResult("alias", self.aliases[text], basis="S2")
        hits = self._keys.get(text, set())
        if len(hits) == 1:
            return MatchResult("auto", next(iter(hits)), basis="S3")
        if len(hits) > 1:
            return MatchResult("ambiguous", candidates=tuple(sorted(hits)), basis="S3")
        bases = self._bases.get(text, set())
        if len(bases) > 1:
            return MatchResult("ambiguous", candidates=tuple(sorted(bases)), basis="S3")
        suggestions = self.suggest(text, bases)
        if suggestions:
            return MatchResult("suggest", candidates=suggestions, basis="S4")
        return MatchResult("unregistered", basis="S5")

    def suggest(self, text: str, seed: set[str] | None = None) -> tuple[str, ...]:
        scored: dict[str, int] = {s: 0 for s in (seed or set())}
        if len(text) >= MIN_FUZZY_LEN:
            for school, keys in self._school_keys.items():
                best = None
                for key in keys:
                    if len(key) >= MIN_FUZZY_LEN and (key in text or text in key):
                        best = 1
                    dist = edit_distance(text, key)
                    if dist <= 1:
                        best = min(best, dist) if best is not None else dist
                if best is not None:
                    scored[school] = min(scored.get(school, best), best)
        ordered = sorted(scored, key=lambda s: (scored[s], s))
        return tuple(ordered[:MAX_SUGGESTIONS])

    def choose(self, raw) -> MatchResult:
        text = normalize_school_text(raw)
        if not text:
            return MatchResult("unregistered", basis="S5")
        if text in self._school_set:
            return MatchResult("selected", text, basis="USER")
        return MatchResult("manual", text, basis="USER")
