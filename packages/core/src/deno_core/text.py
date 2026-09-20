"""Text hygiene shared by API inputs and scraped content."""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated

from pydantic import AfterValidator

# C0/C1 control characters except tab, newline and carriage return, plus lone
# UTF-16 surrogates (valid in JSON escapes, unencodable as UTF-8). NUL in
# particular can't be stored in Postgres text columns.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff]")


def clean_text(value: str) -> str:
    """NFC-normalise, drop control characters, and strip surrounding whitespace."""
    return _CONTROL.sub("", unicodedata.normalize("NFC", value)).strip()


CleanText = Annotated[str, AfterValidator(clean_text)]
