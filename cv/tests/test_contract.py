"""The JSON we serve must match the TypeScript contracts in the root CLAUDE.md, field for field."""

import re
from pathlib import Path

import pytest

from cv_service.schemas import CameraFeed, PeopleCount

SPEC = Path(__file__).resolve().parents[2] / "CLAUDE.md"


def ts_fields(interface: str) -> tuple[set[str], set[str]]:
    """(all fields, optional fields) of an interface in the spec."""
    body = re.search(rf"export interface {interface} \{{(.*?)\n\}}", SPEC.read_text(), re.S)
    assert body, f"{interface} not found in {SPEC}"
    fields = re.findall(r"^\s{2}(\w+)(\??):", body.group(1), re.M)
    return {name for name, _ in fields}, {name for name, opt in fields if opt}


@pytest.mark.parametrize("model,interface", [(PeopleCount, "PeopleCount"), (CameraFeed, "CameraFeed")])
def test_fields_match_spec(model, interface):
    fields, optional = ts_fields(interface)
    assert set(model.model_fields) == fields
    assert {n for n, f in model.model_fields.items() if not f.is_required()} == optional
