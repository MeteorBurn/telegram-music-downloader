"""Filename cleanup and tag ordering, without filesystem side effects."""

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class NormalizationResult:
    name: str
    changes: Tuple[str, ...]
    warnings: Tuple[str, ...]


@dataclass(frozen=True)
class _Part:
    text: str
    start: int
    end: int
    group: bool = False


_BRACKETS = {"(": ")", "[": "]", "{": "}"}
_SEPARATOR = re.compile(r"\s+[-–—]\s+")
_VERSION_END = re.compile(
    r"(?<!\w)(?:remix|re[- ]?edit|edit|rework|version|mix|dub|bootleg|"
    r"mashup|vip|instrumental|acapella|a cappella|acoustic|live|cover|full|clean|dirty)$",
    re.IGNORECASE,
)
# Keep the original vocabulary. Match whole words and leave bracketed versions
# intact, so Edit cannot cut up Credits and Remix cannot lose its author's name.
_MIX_TYPES = (
    "Original Mix", "Radio Edit", "Extended Mix", "Club Mix", "Dub Mix",
    "Vocal Mix", "Instrumental Mix", "Remix", "VIP Mix", "Bootleg Mix",
    "Mashup", "Radio Mix", "Dance Mix", "Progressive Mix", "Deep Mix",
    "Tech Mix", "Minimal Mix", "Acoustic Mix", "Unplugged Mix", "Live Mix",
    "Studio Mix", "Demo Mix", "Alternative Mix", "Special Mix", "Bonus Mix",
    "Short Mix", "Long Mix", "Full Mix", "Edit", "Version", "Rework",
)
_MIX_TYPE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(tag) for tag in _MIX_TYPES) + r")(?!\w)",
    re.IGNORECASE,
)
# Bare Hz can describe musical tuning (432 Hz), not the file's sample rate.
_PARAMETER = r"(?:(?:16|24|32|64)\s*bits?|\d+(?:[.,]\d+)?\s*(?:kHz|kbps|BPM|dB))"
_TECHNICAL = re.compile(rf"{_PARAMETER}(?:[\s,;/]+{_PARAMETER})*", re.IGNORECASE)
_TECHNICAL_TAIL = re.compile(
    rf"(?<![\w.]){_PARAMETER}(?:[\s,;/]+{_PARAMETER})*\s*$", re.IGNORECASE
)
_WORK_MARKER = re.compile(
    r"\b(?:(?:pre)?master(?:ed|ing)?\d*|mstrd?\d*|mst\d*|final\d*|v\d+|\d{4})\s*$",
    re.IGNORECASE,
)
_VERSION_QUALIFIER = (
    r"(?:original|extended|radio|club|dub|vocal|instrumental|vip|bootleg|dance|"
    r"progressive|deep|tech|minimal|acoustic|unplugged|live|studio|demo|"
    r"alternative|special|bonus|short|long|full(?:\s+length)?|ambient)"
)
_VERSION_QUALIFIERS_TAIL = re.compile(
    r"(?<!\w)(?:original(?:\s+extended)?|extended|radio)\s*$", re.IGNORECASE
)
_GENERIC_VERSION = re.compile(
    r"(?:mix|edit|remix|version|rework)", re.IGNORECASE
)
_MASTER_TOKEN = re.compile(
    r"(?<!\w)#?(?:(?-i:[A-Z]{2,4})master|(?:pre)?master(?:ed|ing)?|mstrd?|mst)"
    r"(?:v?\d+(?:bits?|b)?)?(?!\w)", re.IGNORECASE
)
_WORK_PARAMETER = rf"(?:{_PARAMETER}|\d+(?:[.,]\d+)?k(?:\d+)?|\d+b)"
_WORK_DETAIL = rf"(?:{_WORK_PARAMETER}|\d+(?:[.,-]\d+)*|v\d+|digi(?:tal)?|demo|x|(?-i:[A-Z]{{1,4}}))"
_WORK_DETAILS = re.compile(rf"(?:[\s,;-]+{_WORK_DETAIL})*\s*", re.IGNORECASE)
_WORK_TECH_TAIL = re.compile(
    rf"(?<!\w){_WORK_PARAMETER}(?:[\s,;-]+{_WORK_PARAMETER})*\s*$", re.IGNORECASE
)
_STUDIO_CODE = re.compile(r"(?:[A-Za-z]{1,4}|[A-Za-z]+\d+[A-Za-z\d]*)")
_SOURCE = re.compile(
    r"(?:(?:download(?:ed)? from|source\s*[:=]?|via)\s+)?"
    r"(?:https?://|www\.)(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+"
    r"[a-z]{2,}(?:/[^\s()\[\]{}]*)?/?",
    re.IGNORECASE,
)
_AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".aiff", ".aif", ".m4a", ".ogg", ".opus", ".aac"
}
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_FILENAME = re.compile(
    r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE
)
_CAMELOT = r"(?:1[0-2]|[1-9])[AB]"
_RELEASE_TAG = r"(?:vinyl\s+only|only\s+vinyl|vinyl|flac|web|cdq|promo|cdm|cd|single|ep|lp|album)"
_SERVICE_TOKEN = re.compile(
    rf"(?<![\w.])(?:{_PARAMETER}|{_CAMELOT}|{_RELEASE_TAG})(?![\w.])",
    re.IGNORECASE,
)
_SERVICE_GROUP = re.compile(
    rf"(?:{_PARAMETER}|{_CAMELOT}|{_RELEASE_TAG})"
    rf"(?:[\s,;+/-]+(?:{_PARAMETER}|{_CAMELOT}|{_RELEASE_TAG}))*",
    re.IGNORECASE,
)


def remove_message_id(text: str) -> str:
    """Remove the original __digits convention, including stacked download IDs."""
    return re.sub(r"(?:_{2,}\d+)+$", "", text)


def fix_underscores_with_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip()


def fix_residual_characters(text: str) -> str:
    text = text.strip("-–— \t\r\n")
    # Remove an isolated separator dot, not punctuation belonging to a word.
    return re.sub(r"^(?:\.\s+)+|(?:\s+\.)+$", "", text).strip()


def _split_groups(text: str) -> Tuple[List[_Part], bool]:
    """Keep top-level spans intact; malformed nesting makes the parse unusable."""
    parts: List[_Part] = []
    stack: List[str] = []
    cursor = 0
    start = 0
    for index, char in enumerate(text):
        if char in _BRACKETS:
            if not stack:
                start = index
            stack.append(_BRACKETS[char])
        elif char in _BRACKETS.values():
            if not stack or stack.pop() != char:
                return [_Part(text, 0, len(text))], False
            if not stack:
                if start > cursor:
                    parts.append(_Part(text[cursor:start], cursor, start))
                parts.append(_Part(text[start:index + 1], start, index + 1, True))
                cursor = index + 1
    if stack:
        return [_Part(text, 0, len(text))], False
    if cursor < len(text):
        parts.append(_Part(text[cursor:], cursor, len(text)))
    return parts, True


def _spacing(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"([([{])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]}])", r"\1", text)
    text = re.sub(r"([^\s([{])(?=[([{])", r"\1 ", text)
    return re.sub(r"(?<=[)\]}])(?=[^\s)\]}])", " ", text)


def remove_audio_tags(text: str) -> str:
    """Clean release/audio/key markers without cutting words or musical versions."""
    parts, balanced = _split_groups(text)
    if not balanced:
        return text
    has_separator = any(_SEPARATOR.search(p.text) for p in parts if not p.group)
    field_count = _effective_field_count(parts)
    passed_artist = not has_separator
    output: List[str] = []

    def clean(value: str) -> str:
        def replace(match: re.Match) -> str:
            token = match[0]
            # Numeric parameters are removed only by the structural suffix/
            # whole-group rules. "32bit Odyssey" can be the actual title.
            if re.fullmatch(_PARAMETER, token, re.IGNORECASE):
                return token
            if token.casefold() in {"web", "vinyl", "single", "album"}:
                following = value[match.end():].lstrip()
                if following and not (
                    following[0].isdigit() or _SERVICE_TOKEN.match(following)
                    or _WORK_MARKER.fullmatch(following.split()[0])
                ):
                    return token
            # Lowercase/title-case words such as Web or Vinyl may be part of a
            # title or label. An isolated group/field is handled separately.
            if (
                token.isupper() or re.fullmatch(_CAMELOT, token, re.IGNORECASE)
                or token.casefold() in {"flac", "cdq", "cdm", "promo"}
                or " " in token
            ):
                return " "
            return token

        return _SERVICE_TOKEN.sub(replace, value)

    for part in parts:
        value = part.text
        if part.group:
            content = value[1:-1].strip()
            if _SERVICE_GROUP.fullmatch(content):
                continue
            # Preserve the whole remixer/version, including names such as
            # Vinyl Speed Adjust, and unknown mixed bracket contents.
            if not _version(content) and not any(c in content for c in "()[]{}"):
                content = clean(content)
                value = value[0] + content.strip() + value[-1]
        else:
            fields = re.split(r"(\s+[-–—]\s+)", value)
            for index in range(0, len(fields), 2):
                field = fields[index]
                if passed_artist:
                    cleaned = clean(field)
                    if _SERVICE_GROUP.fullmatch(field.strip()):
                        cleaned = ""
                    # A title consisting only of a known word/key remains a
                    # title; standalone extra metadata fields can be removed.
                    prefix = "".join(output) + "".join(fields[:index])
                    if cleaned.strip() or field_count >= 3 or _content_before_suffix(prefix):
                        fields[index] = cleaned
                if index + 1 < len(fields):
                    passed_artist = True
            value = "".join(fields)
        output.append(value)
    result = "".join(output)
    if result != text:
        result = re.sub(r"\s+[-–—](?:\s+[-–—])+\s+", " - ", result)
    return result


def wrap_and_move_mix_types(text: str) -> str:
    """Move complete version groups and the original known mix phrases to the end."""
    parts, balanced = _split_groups(text)
    if not balanced:
        return text
    output: List[str] = []
    versions: List[str] = []
    for part in parts:
        if part.group:
            if part.text.startswith("(") and _version(part.text[1:-1]):
                versions.append(part.text)
            else:
                output.append(part.text)
            continue

        def move(match: re.Match) -> str:
            # A single keyword in the middle of a title is ambiguous (Edit For
            # Afters). At its end retain the old wrapping/moving behavior.
            if " " not in match[0] and part.text[match.end():].strip():
                return match[0]
            prefix = part.text[:match.start()]
            if _SEPARATOR.search(part.text) and not _SEPARATOR.search(prefix):
                return match[0]
            if not _content_before_suffix("".join(output) + prefix):
                return match[0]
            versions.append("(" + match[0] + ")")
            return " "

        output.append(_MIX_TYPE.sub(move, part.text))
    body = fix_residual_characters(" ".join(output)) if versions else " ".join(output)
    return " ".join([body] + versions)


def move_square_bracket_content_to_end(text: str) -> str:
    parts, balanced = _split_groups(text)
    if not balanced:
        return text
    labels = [p.text for p in parts if p.group and p.text.startswith("[")]
    body = [p.text for p in parts if not (p.group and p.text.startswith("["))]
    prefix = fix_residual_characters(" ".join(body)) if labels else " ".join(body)
    return " ".join([prefix] + labels)


def move_vinyl_track_numbers_to_start(text: str) -> str:
    parts, balanced = _split_groups(text)
    if not balanced:
        return text
    for part in parts:
        if part.group:
            continue
        match = re.search(
            r"(?<!\w)([A-D][0-9]{1,2})(?:[.)](?=\s|$)|(?=\s|$))", part.text
        )
        if match:
            start, end = part.start + match.start(), part.start + match.end()
            # Album exports may number the same track twice: "04 B2. Title".
            # Drop the ordinal only at a field boundary, retaining the vinyl ID.
            prefix = part.text[:match.start()]
            ordinal = re.search(r"(?<!\w)\d{1,3}[.)]?\s+$", prefix)
            if ordinal:
                before = prefix[:ordinal.start()]
                if not before.strip() or re.search(r"\s+[-–—]\s+$", before):
                    start = part.start + ordinal.start()
            remaining = text[:start] + text[end:]
            if start == 0:
                remaining = remaining.lstrip(" -–—")
            remaining = re.sub(r"\s+[-–—](?:\s+[-–—])+\s+", " - ", remaining)
            if any(not field.strip() for field in _SEPARATOR.split(remaining)):
                return text
            return match[1] + " " + remaining.strip()
    return text


def _version(text: str) -> bool:
    return bool(_VERSION_END.search(text.strip()))


def _content_before_suffix(text: str) -> bool:
    # Do not turn "Artist - 128 BPM" into an artist with no title.
    return bool(text.strip()) and not re.search(r"(?:^|\s)[-–—]\s*$", text)


def _repair_terminal_bracket(text: str) -> str:
    match = re.search(r"([([])([^()[\]{}]+)([)\]])$", text)
    if not match or _BRACKETS[match[1]] == match[3]:
        return text
    prefix = text[:match.start()]
    if not _split_groups(prefix)[1] or not _content_before_suffix(prefix):
        return text
    content = match[2].strip()
    if _version(content) or _TECHNICAL.fullmatch(content):
        return text[:-1] + _BRACKETS[match[1]]
    return text


def _clean_unicode(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\u00a0", " ").lstrip("\ufeff")

    def latin_neighbor(char: str) -> bool:
        return bool(char) and (
            "LATIN" in unicodedata.name(char, "")
            or char.isascii() and char.isdigit()
            or char in "'’´"
        )

    # ZWSP between Latin letters/apostrophes is a common export artifact.
    # Retain joiners, direction marks and word boundaries in other scripts.
    return re.sub(
        "\u200b+",
        lambda m: "" if latin_neighbor(text[m.start() - 1:m.start()])
        and latin_neighbor(text[m.end():m.end() + 1]) else m[0],
        text,
    )


def _remove_repeated_extension(text: str, extension: str) -> str:
    extension = extension.casefold()
    if extension not in _AUDIO_EXTENSIONS:
        return text
    aliases = {".aif", ".aiff"} if extension in {".aif", ".aiff"} else {extension}
    pattern = "(?:" + "|".join(re.escape(item) for item in sorted(aliases)) + ")+$"
    return re.sub(pattern, "", text, flags=re.IGNORECASE)


def _effective_field_count(parts: List[_Part]) -> int:
    """Discount a leading position or repeated artist, without editing either."""
    fields = [""]
    for part in parts:
        if part.group:
            fields[-1] += part.text
        else:
            segments = _SEPARATOR.split(part.text)
            fields[-1] += segments[0]
            fields.extend(segments[1:])
    fields = [field.strip() for field in fields]
    if fields and re.fullmatch(r"(?:\d+[.)]?|[A-Z]\d{1,2})", fields[0]):
        fields = fields[1:]
    if len(fields) > 1 and fields[0].casefold() == fields[1].casefold():
        fields = fields[1:]
    return len(fields) if all(fields) else 0


def _clean_work_tail(text: str, *, isolated: bool = False) -> str:
    """Recognize a mastering marker and its adjacent technical payload as a unit."""
    for marker in _MASTER_TOKEN.finditer(text):
        tail = text[marker.end():]
        if not _WORK_DETAILS.fullmatch(tail):
            continue
        prefix = text[:marker.start()].rstrip()
        if isolated:
            tokens = re.split(r"[\s,;-]+", prefix) if prefix else []
            if all(
                (_STUDIO_CODE.fullmatch(token) or re.fullmatch(_WORK_DETAIL, token, re.IGNORECASE))
                and not re.fullmatch(_VERSION_QUALIFIER, token, re.IGNORECASE)
                for token in tokens
            ):
                return ""
            # Unknown words may describe a version or name a person.
            return text
        if marker[0].casefold() in {"master", "mastered", "mastering"}:
            if not marker[0].isupper() and not any(c.isdigit() for c in tail):
                continue
        # An engineer's short code is removable with a technical payload, not
        # on its own: the preceding word can instead be the remix author's name.
        code = re.search(r"(?<!\w)([A-Z]{2,4})\s*$", prefix)
        if code and any(c.isdigit() for c in tail):
            prefix = prefix[:code.start()].rstrip()
        technical = _WORK_TECH_TAIL.search(prefix)
        if technical:
            prefix = prefix[:technical.start()].rstrip()
        return prefix
    return text


def _join_version_qualifiers(text: str) -> str:
    # Repair explicit split labels such as Original Extended (Version).
    # Complete groups and ambiguous title words (Full, Long, Deep) stay intact.
    parts, balanced = _split_groups(text)
    if not balanced:
        return text
    output: List[str] = []
    for part in parts:
        if (
            part.group and part.text.startswith("(") and output
            and _GENERIC_VERSION.fullmatch(part.text[1:-1].strip())
        ):
            match = _VERSION_QUALIFIERS_TAIL.search(output[-1])
            if match:
                prefix = output[-1][:match.start()]
                if _content_before_suffix("".join(output[:-1]) + prefix):
                    output[-1] = prefix
                    output.append(
                        part.text[0] + match[0].strip() + " "
                        + part.text[1:-1].strip() + part.text[-1]
                    )
                    continue
        output.append(part.text)
    return "".join(output)


def _clean_parts(text: str, changes: List[str], warnings: List[str]) -> str:
    parts, balanced = _split_groups(text)
    if not balanced:
        warnings.append("unbalanced_brackets")
        return text
    last_text = max(
        (i for i, part in enumerate(parts) if not part.group and part.text.strip()),
        default=-1,
    )
    output: List[str] = []
    previous_version: Optional[str] = None
    separator_count = 0
    field_count = _effective_field_count(parts)
    for index, part in enumerate(parts):
        value = part.text
        if part.group:
            content = value[1:-1].strip()
            if not re.sub(r"[\s()[\]{}]", "", content):
                changes.append("empty_brackets")
                continue
            prefix = "".join(output)
            if index > last_text and _content_before_suffix(prefix):
                working = _clean_work_tail(content, isolated=True)
                if working != content:
                    changes.append("mastering_suffix")
                    if not working:
                        continue
                    content = working
                    value = value[0] + working + value[-1]
                if _TECHNICAL.fullmatch(content):
                    changes.append("technical_group")
                    continue
                if _SOURCE.fullmatch(content):
                    changes.append("source_suffix")
                    continue
                if _version(content) and previous_version == value:
                    changes.append("repeated_version")
                    continue
            if _TECHNICAL_TAIL.search(content) and not _TECHNICAL.fullmatch(content):
                warnings.append("ambiguous_technical_tail")
            previous_version = value if _version(content) else None
        else:
            if value.strip():
                previous_version = None
            separators = list(_SEPARATOR.finditer(value))
            separator_count += len(separators)
            # Two separators avoid treating "Artist - Remix" as a version.
            if index == last_text and separators and separator_count >= 2:
                boundary = separators[-1]
                tail = value[boundary.end():].strip()
                track_prefix = re.match(r"^(?:\d+[.)]?|[A-D]\d{1,2})\s+", tail)
                partial_separator = re.search(r"\s[-–—]\S|\S[-–—]\s", tail)
                if _version(tail):
                    if field_count >= 3 and not track_prefix and not partial_separator:
                        value = value[:boundary.start()] + " (" + tail + ") "
                        changes.append("version_suffix")
                    else:
                        warnings.append("ambiguous_version_suffix")
                elif _SOURCE.fullmatch(tail):
                    value = value[:boundary.start()]
                    changes.append("source_suffix")
            if index == last_text:
                working = _clean_work_tail(value, isolated=bool(output) and not value.strip().startswith("-"))
                if working != value and _content_before_suffix("".join(output) + working):
                    value = working
                    changes.append("mastering_suffix")
                copy_suffix = re.search(r"\s*[-–—]\s+copy\s*$", value, re.IGNORECASE)
                if copy_suffix and (separator_count >= 2 or _content_before_suffix("".join(output))):
                    value = value[:copy_suffix.start()]
                    changes.append("copy_suffix")
                match = _TECHNICAL_TAIL.search(value)
                if match:
                    prefix = value[:match.start()].rstrip()
                    clean_prefix = re.sub(r"\s+[-–—]$", "", prefix)
                    whole_prefix = "".join(output) + prefix
                    if _WORK_MARKER.search("".join(output) + clean_prefix):
                        warnings.append("ambiguous_technical_tail")
                    elif _content_before_suffix(whole_prefix) or (
                        clean_prefix != prefix and separator_count >= 2
                    ):
                        value = clean_prefix
                        changes.append("technical_suffix")
        output.append(value)
    return "".join(output)


def analyze_track_name(
    stem: str, *, extension: str = "", message_id: Optional[int] = None
) -> NormalizationResult:
    """Clean service markers and order name parts, retaining meaningful text.

    extension is the real suffix (including its dot), never inferred from the
    stem. Both old __digits suffixes and the current message ID are cleaned.
    Reasons are stable identifiers; no filesystem or metadata I/O takes place.
    """
    changes: List[str] = []
    warnings: List[str] = []
    name = stem

    # Removing a suffix can expose another one (e.g. .wav [24bit]). Each pass
    # removes recognized fragments or wraps a previously bare version once.
    # A fixed point prevents a later call from peeling off additional text.
    while True:
        previous = name
        cleaned = _clean_unicode(name)
        if cleaned != name:
            changes.append("unicode")
            name = cleaned
        if name != name.strip():
            changes.append("spacing")
            name = name.strip()
        cleaned = remove_message_id(name)
        if cleaned != name:
            changes.append("message_id")
            name = cleaned
        cleaned = _remove_repeated_extension(name, extension)
        if cleaned != name:
            changes.append("repeated_extension")
            name = cleaned
        cleaned = remove_message_id(name)
        if cleaned != name:
            changes.append("message_id")
            name = cleaned
        cleaned = fix_underscores_with_spaces(name)
        if cleaned != name:
            changes.append("underscores")
            name = cleaned
        cleaned = _repair_terminal_bracket(name)
        if cleaned != name:
            changes.append("bracket_pair")
            name = cleaned
        cleaned = (
            _spacing(name) if _split_groups(name)[1]
            else re.sub(r"\s+", " ", name).strip()
        )
        if cleaned != name:
            changes.append("spacing")
            name = cleaned
        cleaned = _clean_parts(name, changes, warnings)
        cleaned = _spacing(cleaned) if _split_groups(cleaned)[1] else cleaned.strip()
        if cleaned != name:
            # Finish exposed suffixes before moving old mix markers: removing
            # kbps can reveal a whole "Artist - Track - Author Remix" field.
            name = cleaned
            continue
        for reason, transform in (
            ("audio_tags", remove_audio_tags),
            ("mix_position", wrap_and_move_mix_types),
            ("version_qualifiers", _join_version_qualifiers),
            ("label_position", move_square_bracket_content_to_end),
            ("vinyl_position", move_vinyl_track_numbers_to_start),
            ("residual_characters", fix_residual_characters),
        ):
            cleaned = transform(name)
            if _spacing(cleaned) != _spacing(name):
                changes.append(reason)
            name = cleaned
        name = _spacing(name) if _split_groups(name)[1] else name.strip()
        if name == previous:
            break

    if any(unicodedata.category(char) == "Cf" for char in name):
        warnings.append("preserved_format_character")
    if (
        not name or name in {".", ".."} or _INVALID_FILENAME.search(name)
        or _RESERVED_FILENAME.match(name)
        or len((name + extension).encode("utf-16-le")) > 510
    ):
        warnings.append("unsafe_result")
        name = stem
        changes = []
    return NormalizationResult(
        name, tuple(dict.fromkeys(changes)), tuple(dict.fromkeys(warnings))
    )


def normalize_track_name(file_name: str) -> str:
    """Compatibility entry point for callers without extension/message context."""
    return analyze_track_name(file_name).name
