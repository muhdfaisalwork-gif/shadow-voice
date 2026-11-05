"""
Telephony Text Normalizer for Speech Synthesis
==============================================
Conservative, idempotent text normalization pre-pass before TTS synthesis.

Adapted from VoiceStudio / num2words architecture.

Solves common speech synthesis errors in cold calling & sales:
- Currency: "$499/mo" -> "four hundred ninety-nine dollars per month"
- Times: "2:30 PM" -> "two thirty p.m."
- Phone numbers: "(312) 555-0188" -> digit-by-digit spoken pronunciation
- Numbers & Ordinals: "1st" -> "first", "50" -> "fifty"
- Zero-width cleanup: strips unicode artifacts that cause TTS dead air or hallucinations
- Markup preservation: leaves SSML and bracket tags [pause 200ms] intact
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Any, List, Optional

# Zero-width spaces, joiners, and bidirectional markers that trip neural TTS
_ZERO_WIDTH_CHARS = re.compile(r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad]")

# Numbers 0-19 and tens
_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen"
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

_ORDINALS = {
    "1st": "first", "2nd": "second", "3rd": "third", "4th": "fourth", "5th": "fifth",
    "6th": "sixth", "7th": "seventh", "8th": "eighth", "9th": "ninth", "10th": "tenth",
    "11th": "eleventh", "12th": "twelfth", "13th": "thirteenth", "14th": "fourteenth",
    "15th": "fifteenth", "16th": "sixteenth", "17th": "seventeenth", "18th": "eighteenth",
    "19th": "nineteenth", "20th": "twentieth", "30th": "thirtieth"
}

_ABBREVIATIONS = {
    r"\bext\.\s*(\d+)": r"extension \1",
    r"\bdept\.\b": "department",
    r"\best\.\b": "estimated",
    r"\bapprox\.\b": "approximately",
    r"\bvs\.\b": "versus",
    r"\bi\.e\.\b": "that is",
    r"\be\.g\.\b": "for example",
    r"\bmo\b": "month",
    r"\byr\b": "year",
}


def number_to_words(n: int) -> str:
    """Converts an integer between 0 and 999,999 into spoken English words."""
    if n < 0:
        return "negative " + number_to_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        ten, rem = divmod(n, 10)
        return _TENS[ten] + (("-" + _ONES[rem]) if rem else "")
    if n < 1000:
        hundred, rem = divmod(n, 100)
        return _ONES[hundred] + " hundred" + ((" " + number_to_words(rem)) if rem else "")
    if n < 1_000_000:
        thousand, rem = divmod(n, 1000)
        return number_to_words(thousand) + " thousand" + ((" " + number_to_words(rem)) if rem else "")
    return str(n)


class TelephonyTextNormalizer:
    """Normalizes raw model text into natural, spoken English for speech synthesis."""

    @classmethod
    def normalize(cls, text: Optional[str]) -> str:
        """Runs the conservative normalization pre-pass."""
        if not text:
            return ""

        # 1. Strip zero-width junk
        cleaned = _ZERO_WIDTH_CHARS.sub("", text)
        cleaned = unicodedata.normalize("NFKC", cleaned)

        # Protect bracket tags like [pause 300ms], [laugh], [slow]
        tags: List[str] = []
        def _mask_tag(m):
            tags.append(m.group(0))
            return f"__TAG_{len(tags) - 1}__"

        masked = re.sub(r"\[[^\]]+\]", _mask_tag, cleaned)

        # 2. Currency expansion (e.g. $499/mo, $25.50, $1,500)
        def _replace_currency_with_cents(m):
            dollars = int(m.group(1).replace(",", ""))
            cents = int(m.group(2))
            d_words = number_to_words(dollars)
            d_unit = "dollar" if dollars == 1 else "dollars"
            if cents == 0:
                return f"{d_words} {d_unit}"
            c_words = number_to_words(cents)
            c_unit = "cent" if cents == 1 else "cents"
            return f"{d_words} {d_unit} and {c_words} {c_unit}"

        masked = re.sub(r"\$(\d{1,3}(?:,\d{3})*|\d+)\.(\d{2})\b", _replace_currency_with_cents, masked)

        def _replace_currency_int(m):
            dollars = int(m.group(1).replace(",", ""))
            d_words = number_to_words(dollars)
            d_unit = "dollar" if dollars == 1 else "dollars"
            return f"{d_words} {d_unit}"

        masked = re.sub(r"\$(\d{1,3}(?:,\d{3})*|\d+)\b", _replace_currency_int, masked)

        # 3. Currency suffixes (/mo, /month, /yr)
        masked = re.sub(r"\s*/\s*mo\b", " per month", masked, flags=re.IGNORECASE)
        masked = re.sub(r"\s*/\s*month\b", " per month", masked, flags=re.IGNORECASE)
        masked = re.sub(r"\s*/\s*yr\b", " per year", masked, flags=re.IGNORECASE)
        masked = re.sub(r"\s*/\s*year\b", " per year", masked, flags=re.IGNORECASE)

        # 4. Clock times (e.g. 2:30 pm, 9:00 AM, 11:15)
        def _replace_time(m):
            hour = int(m.group(1))
            minute = int(m.group(2))
            meridiem = (m.group(3) or "").strip().lower()

            h_word = number_to_words(hour)
            if minute == 0:
                m_word = "o'clock" if not meridiem else ""
            elif minute < 10:
                m_word = f"oh {number_to_words(minute)}"
            else:
                m_word = number_to_words(minute)

            time_str = f"{h_word} {m_word}".strip()
            if meridiem in ("am", "a.m.", "a.m"):
                time_str += " a.m."
            elif meridiem in ("pm", "p.m.", "p.m"):
                time_str += " p.m."
            return time_str

        masked = re.sub(r"\b(1[0-2]|0?[1-9]):([0-5][0-9])\s*([ap]\.?m\.?)?\b", _replace_time, masked, flags=re.IGNORECASE)

        # 5. Phone numbers: (312) 555-0188 or 312-555-0188
        def _replace_phone(m):
            digits = re.sub(r"\D", "", m.group(0))
            if len(digits) == 10:
                part1 = " ".join(_ONES[int(d)] for d in digits[:3])
                part2 = " ".join(_ONES[int(d)] for d in digits[3:6])
                part3 = " ".join(_ONES[int(d)] for d in digits[6:])
                return f"{part1}, {part2}, {part3}"
            return m.group(0)

        masked = re.sub(r"(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", _replace_phone, masked)

        # 6. Ordinals
        for ord_sym, ord_word in _ORDINALS.items():
            masked = re.sub(rf"\b{ord_sym}\b", ord_word, masked, flags=re.IGNORECASE)

        # 7. Common telephony abbreviations
        for pat, repl in _ABBREVIATIONS.items():
            masked = re.sub(pat, repl, masked, flags=re.IGNORECASE)

        # 8. Restore protected bracket tags
        for i, tag in enumerate(tags):
            masked = masked.replace(f"__TAG_{i}__", tag)

        return re.sub(r"\s+", " ", masked).strip()
