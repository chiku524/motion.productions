"""docker-compose.local.yml wires every Python container to the shared D1 write budget."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PY_SERVICES = {"webjobs", "procedural-render", "explorer", "exploiter", "balanced", "interpret", "sound"}


@pytest.fixture(scope="module")
def services():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / "docker-compose.local.yml").read_text(encoding="utf-8", errors="replace"))["services"]


def test_every_python_container_shares_one_budget_and_ledger_volume(services):
    for name in PY_SERVICES:
        env = services[name]["environment"]
        assert env["D1_BUDGET_NAME"] == name
        assert env["D1_DAILY_WRITE_BUDGET"] == "${D1_DAILY_WRITE_BUDGET:-70000}"
        assert env["WRITE_BUDGET_DIR"] == "/app/knowledge/write_budget"  # on the shared ./knowledge bind mount
        assert env["WRITE_BUFFER_DIR"] == "/app/knowledge/write_buffer"
        assert "./knowledge:/app/knowledge" in services[name]["volumes"]


def test_loops_batch_with_intervals_and_sound_posts_are_capped(services):
    for name in ("explorer", "balanced"):
        assert int(services[name]["environment"]["DISCOVERY_FLUSH_INTERVAL_S"].split(":-")[1].rstrip("}")) >= 60
    assert services["sound"]["environment"]["DISCOVERIES_MAX_ITEMS"].startswith("${SOUND_POST_MAX_ITEMS:-12}")
    assert "INTERPRET_FLUSH_INTERVAL_S" in services["interpret"]["environment"]


def test_colour_survey_containers_keep_sync_and_disjoint_explicit_indexes(services):
    for name, idx in (("explorer", "0"), ("balanced", "1")):
        env = services[name]["environment"]
        assert env["CONTAINER_INDEX"] == idx
        assert env["CONTAINER_COUNT"] == "${COLOR_CONTAINER_COUNT:-2}"
        assert env["COLOR_SYNC"] == "${COLOR_SYNC:-1}"
