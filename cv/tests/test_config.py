import pytest

from cv_service.config import load_cameras, load_settings, parse_cameras


def test_parses_sources():
    cams = parse_cameras(
        {
            "cameras": [
                {"camera_id": "cam_s3", "site_id": "shelter_3", "source": 0},
                {"camera_id": "cam_s1", "site_id": "shelter_1", "source": "1"},
                {"camera_id": "cam_s2", "site_id": "shelter_2", "source": "rtsp://cam/2", "loop": False},
            ]
        }
    )
    assert [c.source for c in cams] == [0, 1, "rtsp://cam/2"]
    assert cams[2].loop is False
    assert not cams[2].is_file


@pytest.mark.parametrize(
    "data",
    [
        None,
        {"cameras": "nope"},
        {"cameras": [{"camera_id": "a", "site_id": "s"}]},
        {"cameras": [{"camera_id": "a", "site_id": "s", "source": 0}, {"camera_id": "a", "site_id": "t", "source": 1}]},
    ],
)
def test_rejects_bad_config(data):
    with pytest.raises(ValueError):
        parse_cameras(data)


def test_file_paths_resolve_relative_to_config(tmp_path):
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text("cameras:\n  - {camera_id: c, site_id: s, source: videos/a.mp4}\n")
    (cam,) = load_cameras(cfg)
    assert cam.source == str((tmp_path / "videos/a.mp4").resolve())


def test_settings_from_env(tmp_path):
    cfg = tmp_path / "cameras.yaml"
    cfg.write_text("cameras:\n  - {camera_id: c, site_id: s, source: 0}\n")
    s = load_settings({"CV_CONFIG": str(cfg), "CV_PORT": "9000", "CV_PUBLIC_URL": "http://x:9000/", "CV_CORS_ORIGINS": "a, b"})
    assert s.port == 9000
    assert s.public_url == "http://x:9000"
    assert s.cors_origins == ("a", "b")
    assert len(s.cameras) == 1
