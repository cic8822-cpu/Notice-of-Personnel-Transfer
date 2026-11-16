HANGUL_FIRST, HANGUL_LAST = 0xAC00, 0xD7A3
JONG_NONE, JONG_RIEUL = 0, 8


def is_hangul_syllable(ch: str) -> bool:
    return len(ch) == 1 and HANGUL_FIRST <= ord(ch) <= HANGUL_LAST


def needs_euro(word: str) -> bool | None:
    """'으로'가 필요하면 True, '로'면 False, 끝글자가 한글 음절이 아니면 None."""
    if not word or not is_hangul_syllable(word[-1]):
        return None
    jong = (ord(word[-1]) - HANGUL_FIRST) % 28
    return jong not in (JONG_NONE, JONG_RIEUL)


def ro_euro(word: str) -> str:
    return "으로" if needs_euro(word) else "로"
