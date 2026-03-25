import re
from typing import List


def remove_message_id(text: str) -> str:
    return re.sub(r"_{2,}\d+$", " ", text)


def fix_extra_spaces(text: str) -> str:
    return re.sub(r"\s{2,}", " ", text).strip()


def fix_spaces_in_brackets(text: str) -> str:
    text = re.sub(r"(\[|\()\s+", r"\1", text)
    text = re.sub(r"\s+(\]|\))", r"\1", text)
    return text


def fix_missing_spaces_around_brackets(text: str) -> str:
    text = re.sub(r"(?<!\s)(?=\[|\()", " ", text)
    text = re.sub(r"(?<=\]|\))(?=\S)", " ", text)
    return text.strip()


def fix_underscores_with_spaces(text: str) -> str:
    return re.sub(r"\s{2,}", " ", text.replace("_", " ")).strip()


def capitalize_words(text: str) -> str:
    return " ".join(word.capitalize() for word in text.split())


def wrap_and_move_mix_types(file_name: str) -> str:
    mix_types = [
        "Original Mix",
        "Radio Edit",
        "Extended Mix",
        "Club Mix",
        "Dub Mix",
        "Vocal Mix",
        "Instrumental Mix",
        "Remix",
        "VIP Mix",
        "Bootleg Mix",
        "Mashup",
        "Radio Mix",
        "Dance Mix",
        "Progressive Mix",
        "Deep Mix",
        "Tech Mix",
        "Minimal Mix",
        "Acoustic Mix",
        "Unplugged Mix",
        "Live Mix",
        "Studio Mix",
        "Demo Mix",
        "Alternative Mix",
        "Special Mix",
        "Bonus Mix",
        "Short Mix",
        "Long Mix",
        "Full Mix",
        "Edit",
        "Version",
        "Rework",
    ]
    found_mixes: List[str] = []
    for mix_type in mix_types:
        pattern = rf"(?<!\[|\()({re.escape(mix_type)})(?!\]|\))"
        matches = re.findall(pattern, file_name, re.IGNORECASE)
        for match in matches:
            found_mixes.append(f"({capitalize_words(match)})")
        file_name = re.sub(pattern, "", file_name, flags=re.IGNORECASE)
    if found_mixes:
        file_name = re.sub(r"\s{2,}", " ", file_name).strip()
        return f"{file_name} {' '.join(found_mixes)}".strip()
    return file_name


def move_square_bracket_content_to_end(text: str) -> str:
    matches = re.findall(r"\[[^\]]+\]", text)
    text_wo_brackets = re.sub(r"\[[^\]]+\]", "", text)
    text_wo_brackets = fix_extra_spaces(text_wo_brackets)
    return fix_extra_spaces(text_wo_brackets + " " + " ".join(matches))


def move_vinyl_track_numbers_to_start(text: str) -> str:
    match = re.search(r"(?:\s|^)([A-D][0-9]{1,2})(?:\s|$)", text)
    if match:
        number = match.group(1)
        text = re.sub(r"(?:\s|^)" + re.escape(number) + r"(?:\s|$)", " ", text)
        text = fix_extra_spaces(text)
        text = f"{number} {text}"
    return text


def remove_vinyl_tags(text: str) -> str:
    text = re.sub(r"\b(?:vinyl\s+only|only\s+vinyl)\b", "", text, flags=re.IGNORECASE)
    return re.sub(r"\b(?:Vinyl|LP|EP|Single)\b", "", text, flags=re.IGNORECASE)


def remove_musical_keys(text: str) -> str:
    camelot = [f"{i}{k}" for i in range(1, 13) for k in ["A", "B"]]
    for key in camelot:
        text = re.sub(rf"(\s|\[|\()({key})(\s|\]|\))", " ", text, flags=re.IGNORECASE)
    return fix_extra_spaces(text)


def remove_audio_tags(text: str) -> str:
    tags = [
        r"320\s?kbps",
        r"192\s?kbps",
        r"256\s?kbps",
        r"48000\s?khz",
        r"44000\s?khz",
        r"flac",
        r"web",
        r"cdq",
        r"promo",
        r"cdm",
        r"cd",
        r"single",
        r"ep",
        r"lp",
        r"album",
        r"full",
        r"clean",
        r"dirty",
        r"instrumental",
        r"acapella",
        r"bootleg",
        r"cover",
    ]
    for tag in tags:
        text = re.sub(rf"\b{tag}\b", "", text, flags=re.IGNORECASE)
    return fix_extra_spaces(text)


def remove_empty_brackets(text: str) -> str:
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\[\s*\]", "", text)
    return fix_extra_spaces(text)


def fix_residual_characters(text: str) -> str:
    text = re.sub(r"[-–—.\s]+$", "", text)
    text = re.sub(r"^[-–—.\s]+", "", text)
    return fix_extra_spaces(text)


def normalize_track_name(file_name: str) -> str:
    name = file_name
    name = remove_message_id(name)
    name = fix_extra_spaces(name)
    name = fix_spaces_in_brackets(name)
    name = fix_missing_spaces_around_brackets(name)
    name = fix_underscores_with_spaces(name)
    name = wrap_and_move_mix_types(name)
    name = move_square_bracket_content_to_end(name)
    name = move_vinyl_track_numbers_to_start(name)
    name = remove_vinyl_tags(name)
    name = remove_musical_keys(name)
    name = remove_audio_tags(name)
    name = remove_empty_brackets(name)
    name = fix_residual_characters(name)
    return name
