"""
Converts maths notation (LaTeX-ish symbols, superscripts, common operators)
into speakable English text before it is sent to TTS. The on-screen chat text
keeps the original notation; only the audio-bound copy is run through this.

Rule-based and intentionally simple — covers the symbol set that actually
shows up in CBSE Class 9 Maths (algebra, geometry, mensuration, statistics).
Order of rules matters: more specific patterns are replaced before generic ones.
"""
from __future__ import annotations

import re

_SUPERSCRIPT_DIGITS = {
    "²": "2", "³": "3", "¹": "1", "⁰": "0", "⁴": "4", "⁵": "5",
    "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
}

_POWER_WORDS = {"2": "squared", "3": "cubed"}


def _speak_power(base: str, exponent: str) -> str:
    word = _POWER_WORDS.get(exponent, f"to the power {exponent}")
    return f"{base} {word}"


def _replace_superscripts(text: str) -> str:
    # e.g. "x²" -> "x squared", "y⁵" -> "y to the power 5"
    pattern = re.compile(r"([A-Za-z0-9\)])([²³¹⁰⁴⁵⁶⁷⁸⁹]+)")

    def repl(match: re.Match) -> str:
        base, sup = match.group(1), match.group(2)
        digits = "".join(_SUPERSCRIPT_DIGITS.get(ch, "") for ch in sup)
        return _speak_power(base, digits)

    return pattern.sub(repl, text)


def _replace_caret_powers(text: str) -> str:
    # e.g. "x^2" -> "x squared", "x^n" -> "x to the power n"
    pattern = re.compile(r"([A-Za-z0-9\)])\^\{?(-?[A-Za-z0-9]+)\}?")

    def repl(match: re.Match) -> str:
        return _speak_power(match.group(1), match.group(2))

    return pattern.sub(repl, text)


def _replace_roots(text: str) -> str:
    # √2 -> "root 2", √(x+1) -> "root of x plus 1" (parens handled generically below)
    text = re.sub(r"√\(([^)]+)\)", r"root of \1", text)
    text = re.sub(r"√(-?\w+)", r"root \1", text)
    return text


_LATEX_TEXT_WRAPPER = re.compile(r"\\text\{([^}]*)\}")
_LATEX_FRAC = re.compile(r"\\frac\{([^}]*)\}\{([^}]*)\}")
_LATEX_DELIMITERS = re.compile(r"\\[\[\]()]")
_LATEX_COMMANDS = {
    r"\circ": " degrees",
    r"\cdot": " times ",
    r"\times": " times ",
    r"\div": " divided by ",
    r"\pm": " plus or minus ",
    r"\sqrt": "root ",
    r"\angle": "angle ",
    r"\degree": " degrees",
}


def _strip_latex(text: str) -> str:
    # The system prompt instructs the LLM never to use LaTeX, but models can
    # slip into it anyway (e.g. "\[ \text{Angle A} = 70^\circ \]"). Defense in
    # depth: unwrap the common constructs into plain text rather than letting
    # backslashes/braces reach the TTS engine as literal gibberish.
    text = _LATEX_FRAC.sub(r"\1 over \2", text)
    text = _LATEX_TEXT_WRAPPER.sub(r"\1", text)
    text = _LATEX_DELIMITERS.sub("", text)
    for command, spoken in _LATEX_COMMANDS.items():
        text = text.replace(command, spoken)
    # Strip any remaining "\command" tokens and stray braces we don't recognize.
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    text = text.replace("{", "").replace("}", "")
    text = text.replace("$", "")
    return text


_FRACTION_TOKEN = r"[A-Za-z0-9]+(?:\([^)]*\))?"  # e.g. "3", "x", "p(-2)", "g(x+1)"
_ENGLISH_SLASH_IDIOMS = re.compile(
    r"\b(and/or|his/her|he/she|him/her)\b", re.IGNORECASE
)
_IDIOM_PLACEHOLDER = "\x00{}\x00"


def _protect_slash_idioms(text: str) -> tuple[str, list[str]]:
    # Temporarily replace common English slash idioms (and/or, his/her, ...)
    # with a placeholder so neither _replace_fractions nor the final
    # slash-catch-all misreads them as division.
    saved: list[str] = []

    def stash(match: re.Match) -> str:
        saved.append(match.group(0))
        return _IDIOM_PLACEHOLDER.format(len(saved) - 1)

    return _ENGLISH_SLASH_IDIOMS.sub(stash, text), saved


def _restore_slash_idioms(text: str, saved: list[str]) -> str:
    for i, original in enumerate(saved):
        text = text.replace(_IDIOM_PLACEHOLDER.format(i), original)
    return text


def _replace_fractions(text: str) -> str:
    # "a/b" -> "a over b", including function-call operands like "p(-2)/g(-2)".
    pattern = re.compile(rf"(?<![\w)])({_FRACTION_TOKEN})\s*/\s*({_FRACTION_TOKEN})(?![\w(])")
    return pattern.sub(r"\1 over \2", text)


def _replace_remaining_slashes(text: str) -> str:
    # Any "/" left after _replace_fractions (e.g. inside longer expressions,
    # ranges, or anything the fraction pattern didn't catch) — read as
    # "divided by" so it's never spoken as a literal slash by the TTS engine.
    return re.sub(r"\s*/\s*", " divided by ", text)


_SYMBOL_REPLACEMENTS: list[tuple[str, str]] = [
    ("≠", " is not equal to "),
    ("≤", " is less than or equal to "),
    ("≥", " is greater than or equal to "),
    ("=", " equals "),
    ("≈", " is approximately "),
    ("±", " plus or minus "),
    ("×", " times "),
    ("÷", " divided by "),
    ("∠", "angle "),
    ("°", " degrees"),
    ("△", "triangle "),
    ("Δ", "triangle "),
    ("∥", " is parallel to "),
    ("⊥", " is perpendicular to "),
    ("≅", " is congruent to "),
    ("∼", " is similar to "),
    ("π", "pi"),
    ("∞", "infinity"),
    ("%", " percent"),
    ("+", " plus "),
    ("−", " minus "),  # unicode minus
]


def _replace_minus_operator(text: str) -> str:
    # "3x - 4" -> "... minus 4". Only treat '-' as a maths operator when it is
    # surrounded by spaces (with a digit/variable right after), so hyphenated
    # English words like "step-by-step" or "well-known" are left untouched.
    return re.sub(r"(?<=\S)\s+-\s+(?=[A-Za-z0-9])", " minus ", text)


# Common Tanglish words whose natural/correct spelling (used on-screen) gets
# mispronounced by Sarvam's TTS. Mapped to a respelling that sounds right when
# spoken, WITHOUT changing what the student reads in the chat transcript —
# only the audio-bound copy goes through this. Add new entries here as
# mispronunciations are found; matching is case-insensitive and whole-word only.
_TANGLISH_TTS_RESPELLINGS: dict[str, str] = {
    "sari": "seari",
}
_TANGLISH_RESPELL_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _TANGLISH_TTS_RESPELLINGS) + r")\b",
    re.IGNORECASE,
)


def _respell_for_tanglish_pronunciation(text: str) -> str:
    def repl(match: re.Match) -> str:
        original = match.group(0)
        replacement = _TANGLISH_TTS_RESPELLINGS[original.lower()]
        return replacement.capitalize() if original[0].isupper() else replacement

    return _TANGLISH_RESPELL_PATTERN.sub(repl, text)


_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_TEENS = [
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
_TENS = [
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
]


def _two_digit_words(n: int) -> str:
    if n < 10:
        return _ONES[n]
    if n < 20:
        return _TEENS[n - 10]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")


def _three_digit_words(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    if hundreds == 0:
        return _two_digit_words(rest)
    head = f"{_ONES[hundreds]} hundred"
    return f"{head} {_two_digit_words(rest)}" if rest else head


def _int_to_casual_words(n: int) -> str:
    # Casual/spoken style for a maths-tutor voice: e.g. 180 -> "one eighty"
    # (like reading a number aloud informally), not "one hundred and eighty".
    # Falls back to formal hundreds/thousands grouping outside the common
    # 2-3 digit range that CBSE Class 9 angle/length/score values fall in.
    if n == 0:
        return "zero"
    if n < 0:
        return f"minus {_int_to_casual_words(-n)}"
    if n < 100:
        return _two_digit_words(n)
    if 100 <= n < 1000:
        hundreds, rest = divmod(n, 100)
        if rest == 0:
            return f"{_ONES[hundreds]} hundred"
        if rest < 10:
            return f"{_ONES[hundreds]} oh {_ONES[rest]}"
        return f"{_ONES[hundreds]} {_two_digit_words(rest)}"
    if 1000 <= n < 100000:
        thousands, rest = divmod(n, 1000)
        thousands_words = _three_digit_words(thousands)
        return f"{thousands_words} thousand" + (f" {_three_digit_words(rest)}" if rest else "")
    return str(n)  # outside the range this tutor's content ever needs


_NUMBER_TOKEN = re.compile(r"-?\d+(\.\d+)?")


def _replace_numbers_with_words(text: str) -> str:
    # Convert digits to casual spoken English number-words so a non-English
    # TTS voice (e.g. ta-IN) reads "180" as the English word "one eighty"
    # instead of attempting a native-language numeral reading.
    def repl(match: re.Match) -> str:
        token = match.group(0)
        if "." in token:
            whole, _, frac = token.partition(".")
            whole_words = _int_to_casual_words(int(whole)) if whole not in ("", "-") else ""
            frac_words = " ".join(_ONES[int(d)] if d != "0" else "zero" for d in frac)
            sign = "minus " if whole.startswith("-") else ""
            whole_words = whole_words.removeprefix("minus ") if sign else whole_words
            words = f"{sign}{whole_words} point {frac_words}".strip()
        else:
            words = _int_to_casual_words(int(token))

        # Keep a trailing space when the number is glued directly to a
        # following letter (e.g. "5x" -> "five x", not "fivex").
        end = match.end()
        if end < len(text) and text[end].isalpha():
            words += " "
        return words

    return _NUMBER_TOKEN.sub(repl, text)


def to_speech_text(
    text: str, spell_out_numbers: bool = False, respell_tanglish: bool = False
) -> str:
    """
    Convert a chunk of LLM output text into a TTS-friendly version.

    spell_out_numbers: set True when the TTS voice's target language is not
    English (e.g. Sarvam ta-IN) — that voice would otherwise read digits as
    native-language numerals instead of English number words. Leave False for
    an English-target voice (e.g. en-IN), which already reads "180" correctly
    on its own.

    respell_tanglish: set True when the TTS voice is in Tamil mode (ta-IN) to
    apply known phonetic respellings (e.g. "Sari" -> "Seari") so Tanglish
    words are actually pronounced correctly — without changing the on-screen
    chat text, which keeps the natural spelling.
    """
    out = text.replace(r"^\circ", " degrees")  # "180^\circ" before generic caret-power handling
    out = _strip_latex(out)
    out, saved_idioms = _protect_slash_idioms(out)
    out = _replace_roots(out)
    out = _replace_superscripts(out)
    out = _replace_caret_powers(out)
    out = _replace_fractions(out)
    out = _replace_minus_operator(out)
    out = _replace_remaining_slashes(out)
    out = _restore_slash_idioms(out, saved_idioms)

    for symbol, spoken in _SYMBOL_REPLACEMENTS:
        out = out.replace(symbol, spoken)

    if spell_out_numbers:
        out = _replace_numbers_with_words(out)
    if respell_tanglish:
        out = _respell_for_tanglish_pronunciation(out)

    # Collapse repeated whitespace introduced by replacements.
    out = re.sub(r"\s+", " ", out).strip()
    return out


_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_MARKDOWN_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MARKDOWN_BULLET = re.compile(r"^[-*]\s+")
_TARGET_CHUNK_CHARS = 70  # Sarvam TTS scales ~35ms/char, so 70 chars ≈ 2-3s per chunk
_MIN_CHUNK_CHARS = 25  # avoid firing a TTS call for a tiny 1-2 word leftover


def _strip_markdown_for_speech(text: str) -> str:
    # "**Step 1:**" -> "Step 1:" — bold markers should never be read aloud
    # literally ("asterisk asterisk Step 1...").
    text = _MARKDOWN_BOLD.sub(r"\1", text)
    text = _MARKDOWN_BULLET.sub("", text)
    return text


def split_into_speech_chunks(text: str, target_chars: int = _TARGET_CHUNK_CHARS) -> list[str]:
    """
    Split a (possibly long, multi-step) reply into smaller pieces so each one
    can be sent to TTS and start playing quickly, instead of waiting for the
    entire reply's audio to be synthesized in one slow call. Sentences (and
    short markdown lines like "**Step 1:**") are packed together up to
    ~target_chars per chunk, so we get a handful of chunks rather than one
    slow request or dozens of tiny ones.
    """
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    sentences: list[str] = []
    for line in lines:
        line = _strip_markdown_for_speech(line)
        sentences.extend(s.strip() for s in _SENTENCE_BOUNDARY.split(line) if s.strip())

    chunks: list[str] = []
    buffer = ""
    for sentence in sentences:
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence
        if buffer and len(candidate) > target_chars and len(buffer) >= _MIN_CHUNK_CHARS:
            chunks.append(buffer)
            buffer = sentence
        else:
            buffer = candidate

    if buffer:
        chunks.append(buffer)
    return chunks or [text.strip()]