import datetime as dt

from . import config, storage
from .defaults import DEFAULT_LANG


def _load_lang_from_config() -> str:
    return config.get_config("lang", DEFAULT_LANG)


_LANG: str = DEFAULT_LANG


def set_language(lang: str) -> None:
    global _LANG
    _LANG = lang or DEFAULT_LANG


def save_language(lang: str) -> None:
    lang = lang or DEFAULT_LANG
    config.set_config("lang", lang)
    set_language(lang)


def instructions_line() -> str:
    texts = {
        "en": "",
    }
    return texts.get(_LANG, texts["en"])


def started_at_line(start_time: dt.datetime) -> str:
    return f"Started at {start_time.strftime('%H:%M:%S')}"


def saved_session_line(formatted_duration: str) -> str:
    templates = {
        "en": f"Saved session: {formatted_duration}",
    }
    return templates.get(_LANG, templates["en"])


def cancelled_line() -> str:
    texts = {
        "en": "Session cancelled; nothing saved.",
    }
    return texts.get(_LANG, texts["en"])


def interrupted_line(elapsed_seconds: int) -> str:
    elapsed = storage.format_hms(elapsed_seconds)
    templates = {
        "en": f"Interrupted. Fokused for {elapsed}.\n"
        f"Use hiper postfokus --duration {elapsed} --title TITLE "
        "if you want to save the session.",
    }
    return templates.get(_LANG, templates["en"])


def paused_line(current_time: dt.datetime, elapsed_seconds: int) -> str:
    templates = {
        "en": "---------------------------------\n"
        f"Paused at {current_time.strftime('%H:%M:%S')}.\n"
        f"Fokused in total for {storage.format_hms(elapsed_seconds)}.\n"
        "---------------------------------",
    }
    return templates.get(_LANG, templates["en"])


def command_prompt() -> str:
    prompts = {
        "en": ":> ",
    }
    return prompts.get(_LANG, prompts["en"])


def saved_path_line(path: str) -> str:
    templates = {
        "en": f"Saved to: {path}",
    }
    return templates.get(_LANG, templates["en"])


def stats_header(title_filter: str | None = None) -> str:
    if title_filter:
        templates = {"en": f"Statistics {title_filter}"}
        return templates.get(_LANG, templates["en"])
    templates = {"en": "Statistics"}
    return templates.get(_LANG, templates["en"])


def stats_line(key: str, value: str) -> str:
    return f"{key}: {value}"


def resuming_line(pause_duration_formatted: str, resume_time: dt.datetime) -> str:
    templates = {
        "en": f"Paused for {pause_duration_formatted}, "
        f"resuming at {resume_time.strftime('%H:%M:%S')}",
    }
    return templates.get(_LANG, templates["en"])


def invalid_X(msg: str, X: str) -> str:
    templates = {
        "en": f"Invalid {X}: {msg}",
    }
    return templates.get(_LANG, templates["en"])


def language_set(lang: str) -> str:
    templates = {
        "en": f"Language set to: {lang}",
    }
    return templates.get(_LANG, templates["en"])


# To add translations:
# - Create entries for your language code (e.g., "tr") alongside "en" in the
#   dictionaries above (templates/texts/prompts).
