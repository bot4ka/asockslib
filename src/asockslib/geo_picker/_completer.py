"""Fuzzy-match completer and validators for prompt_toolkit.

Provides the autocompletion and input validation used by
:class:`~asockslib.geo_picker.GeoPicker` interactive prompts.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.validation import ValidationError, Validator

if TYPE_CHECKING:
    from collections.abc import Iterable

    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.document import Document

_RE_GEO_NAME = re.compile(r"^[\w\s\-.'()/]+$", re.UNICODE)


class FuzzyMatchCompleter(Completer):
    """Completer that shows all choices on empty input.

    On non-empty input performs case-insensitive substring matching.
    """

    def __init__(self, choices: list[str], ignore_case: bool = True) -> None:
        self.choices = choices
        self.ignore_case = ignore_case

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        """Yield completions matching current input."""
        text = document.text_before_cursor
        if self.ignore_case:
            text = text.lower()

        for choice in self.choices:
            compare = choice.lower() if self.ignore_case else choice
            if text in compare:
                yield Completion(
                    choice,
                    start_position=-len(document.text_before_cursor),
                )


def make_choice_validator(
    choices: list[str],
    error_msg: str,
    error_chars: str,
) -> Validator:
    """Create a choice validator for prompt_toolkit.

    Only values present in *choices* (case-insensitive) are accepted.
    """
    lower_lookup: dict[str, str] = {c.strip().lower(): c for c in choices}

    class _ChoiceValidator(Validator):
        def validate(self, document: Document) -> None:
            t = document.text.strip()
            if t in choices:
                return
            if t.lower() in lower_lookup:
                return
            if t and not _RE_GEO_NAME.match(t):
                raise ValidationError(message=error_chars)
            raise ValidationError(message=error_msg)

    return _ChoiceValidator()


def pt_style() -> PTStyle:
    """Color scheme for prompt_toolkit prompts."""
    return PTStyle.from_dict(
        {
            "qmark": "fg:ansicyan bold",
            "question": "fg:ansiwhite bold",
            "answer": "fg:ansigreen bold",
            "completion-menu": "bg:ansiblack fg:ansiwhite",
            "completion-menu.completion": "",
            "completion-menu.completion.current": "bg:ansicyan fg:ansiblack",
            "scrollbar.background": "bg:ansibrightblack",
            "scrollbar.button": "bg:ansicyan",
        }
    )
