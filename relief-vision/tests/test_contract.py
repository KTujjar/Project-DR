"""PeopleCount / CameraFeed must match the dashboard's TypeScript contracts (root CLAUDE.md), field for field."""
import pytest

from reliefvision.dashboard import CameraFeed, PeopleCount

# From the shared spec: `interface PeopleCount` and `interface CameraFeed` (optional fields marked `?`).
SPEC = {
    "PeopleCount": ({"site_id", "camera_id", "timestamp", "people_count", "confidence"}, set()),
    "CameraFeed": ({"camera_id", "site_id", "stream_url", "snapshot_url", "online", "last_frame_at"},
                   {"stream_url", "snapshot_url"}),
}


@pytest.mark.parametrize("model", [PeopleCount, CameraFeed])
def test_fields_match_spec(model):
    fields, optional = SPEC[model.__name__]
    assert set(model.model_fields) == fields
    assert {n for n, f in model.model_fields.items() if not f.is_required()} == optional
