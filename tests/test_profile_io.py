from pathlib import Path

from jobhunter.extraction.profile_extractor import load_profile, save_profile
from jobhunter.models import CandidateProfile, Education


def test_save_then_load_round_trip(tmp_path: Path):
    path = tmp_path / "profile" / "profile.json"
    profile = CandidateProfile(
        education=[Education(institution="TU Munich", degree="BSc", field="Chemistry", graduated="2018")],
        skills=["HPLC", "Python", "GMP"],
    )

    save_profile(profile, path)
    assert path.exists()

    loaded = load_profile(path)
    assert loaded is not None
    assert loaded.skills == ["HPLC", "Python", "GMP"]
    assert loaded.education[0].institution == "TU Munich"


def test_load_profile_missing_file_returns_none(tmp_path: Path):
    assert load_profile(tmp_path / "nope.json") is None
