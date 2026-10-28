"""Local write buffers: coalescing sums, novel-first flush, intervals, exhaustion, back-off, persistence."""
import json

import pytest

from src import api_client
from src.interpretation import linguistic_client
from src.knowledge import remote_sync, write_budget as wb
from src.knowledge import write_buffers as wbuf
from tests.test_write_budget import FakeResp, utc  # noqa: F401  (FakeResp used by the net fixture below)


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Poster:
    """Stands in for api_request_with_retry; records bodies and can fail on demand."""

    def __init__(self):
        self.calls = []
        self.fail = None
        self.resp = None

    def __call__(self, api_base, method, path, data=None, timeout=None, max_retries=0, **kw):
        if self.fail:
            raise self.fail
        self.calls.append((path, data))
        if self.resp is not None:
            return self.resp
        if path.endswith("/batch"):
            return {"inserted": len((data or {}).get("items", [])), "updated": 0}
        return {"results": {}}


def color(k, **kw):
    return {"key": k, "r": 1, "g": 2, "b": 3, "name": k, **kw}


def posted_items(poster):
    out = []
    for _, data in poster.calls:
        for cat, v in data.items():
            if cat == "job_id":
                continue
            if cat == "narrative":
                for aspect, arr in v.items():
                    out += [(cat, i) for i in arr]
            else:
                out += [(cat, i) for i in v]
    return out


# ---------------------------------------------------------------------------------------------------------
# DiscoverySpool
# ---------------------------------------------------------------------------------------------------------
def test_spool_dedupes_and_sums_counts_across_adds():
    s = wbuf.DiscoverySpool("explorer")
    s.add({"static_colors": [color("a"), color("a"), color("b", count_delta=4)]})
    s.add({"static_colors": [color("a", count_delta=2)]})
    p = Poster()
    s.flush("http://api", poster=p)
    sent = {i["key"]: i.get("count_delta", 1) for _, i in posted_items(p)}
    assert sent == {"a": 4, "b": 4}  # a: 1+1+2, b: 4
    assert len(s) == 0


def test_spool_sends_novel_color_sound_motion_first_and_chunks():
    s = wbuf.DiscoverySpool("explorer")
    s.add({
        "narrative": {"mood": [{"key": "m1", "name": "m1"}]},
        "blends": [{"domain": "color", "output": {"x": 1}, "name": "bl"}],
        "motion": [{"key": "mo1"}],
        "static_sound": [{"key": "s1"}],
        "static_colors": [color("c1")],
    })
    p = Poster()
    s.flush("http://api", chunk_size=2, poster=p)
    order = [cat for cat, _ in posted_items(p)]
    assert order == ["static_colors", "static_sound", "motion", "blends", "narrative"]
    assert len(p.calls) == 3  # 2 + 2 + 1


def test_spool_keeps_items_when_the_budget_denies_and_flushes_after_reset():
    s = wbuf.DiscoverySpool("explorer")
    s.add({"static_colors": [color("a"), color("b")]})
    p = Poster()
    p.fail = api_client.WriteBudgetSkipped("out of budget", status_code=503, path="/api/knowledge/discoveries")
    res = s.flush("http://api", poster=p)
    assert res["skipped"] == "budget" and res["deferred"] == 2 and len(s) == 2
    p.fail = None
    res = s.flush("http://api", poster=p)
    assert res["posted"] == 2 and len(s) == 0


def test_spool_keeps_items_on_worker_error_and_survives_restart(tmp_path):
    s = wbuf.DiscoverySpool("explorer")
    s.add({"static_colors": [color("a", count_delta=3)]})
    p = Poster()
    p.fail = api_client.APIError("boom", status_code=500, path="/x")
    assert s.flush("http://api", poster=p)["skipped"] == "error:500"
    s2 = wbuf.DiscoverySpool("explorer")  # new process, same file
    assert len(s2) == 1
    p.fail = None
    s2.flush("http://api", poster=p)
    assert posted_items(p)[0][1]["count_delta"] == 3


def test_spool_flush_interval_and_max_items_trigger():
    clock = Clock()
    s = wbuf.DiscoverySpool("sound", flush_interval=600, flush_max_items=5, clock=clock)
    p = Poster()
    s.add({"static_sound": [{"key": "a"}]})
    assert s.flush("http://api", poster=p)["skipped"] == "not_due" and not p.calls
    clock.t += 601
    assert s.flush("http://api", poster=p)["posted"] == 1
    s.add({"static_sound": [{"key": f"k{i}"} for i in range(5)]})  # hits max items: due even inside the interval
    assert s.flush("http://api", poster=p)["posted"] == 5
    s.add({"static_sound": [{"key": "z"}]})
    assert s.flush("http://api", poster=p, force=True)["posted"] == 1


def test_spool_truncated_response_keeps_the_unprocessed_tail():
    s = wbuf.DiscoverySpool("explorer")
    s.add({"static_colors": [color("a"), color("b"), color("c")]})
    p = Poster()
    p.resp = {"results": {"static_colors": 1}, "truncated": True, "items_processed": 1}
    res = s.flush("http://api", poster=p)
    assert res["posted"] == 1 and len(s) == 2


def test_spool_cap_drops_lowest_priority_first():
    s = wbuf.DiscoverySpool("explorer", max_spool_items=3)
    s.add({"static_colors": [color("c1"), color("c2")], "narrative": {"mood": [{"key": "n1"}, {"key": "n2"}]}})
    cats = sorted(e["cat"] for e in s._entries.values())
    assert cats == ["narrative", "static_colors", "static_colors"]


def test_spool_job_id_rides_only_on_the_last_chunk_of_a_full_drain():
    s = wbuf.DiscoverySpool("explorer")
    s.add({"static_colors": [color("a"), color("b"), color("c")]})
    p = Poster()
    res = s.flush("http://api", job_id="job-1", chunk_size=2, poster=p)
    assert [("job_id" in d) for _, d in p.calls] == [False, True] and res["job_id_sent"]


# ---------------------------------------------------------------------------------------------------------
# post_discoveries / post_linguistic_growth wiring
# ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def net(monkeypatch):
    calls = []
    state = {"resp": FakeResp(200, {"results": {}})}

    def fake_request(method, url, data=None, headers=None, timeout=None):
        calls.append((method, url, json.loads(data) if data else None))
        return state["resp"]

    monkeypatch.setattr(api_client.requests, "request", fake_request)
    monkeypatch.setattr(api_client.time, "sleep", lambda s: None)
    monkeypatch.setattr(remote_sync, "DISCOVERIES_CHUNK_PAUSE_SECONDS", 0.0)
    monkeypatch.setenv("DISCOVERIES_CHUNK_PAUSE_SECONDS", "0")
    monkeypatch.setenv("D1_BUDGET_NAME", "sound")
    wb.reset_budget()
    wbuf.reset_buffers()
    api_client.reset_free_tier_cooldown()
    yield calls, state
    api_client.reset_free_tier_cooldown()
    wbuf.reset_buffers()


def test_post_discoveries_exhausted_keeps_working_locally_and_flushes_after_reset(net, monkeypatch):
    calls, _ = net
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "100")
    monkeypatch.setenv("D1_BUDGET_WEIGHTS", "sound=100")
    clock = Clock(utc(2026, 10, 27, 23, 59))
    wb.reset_budget(wb.WriteBudget(name="sound", clock=clock))
    body = lambda n: {"static_sound": [{"key": f"{n}-{i}"} for i in range(3)]}  # 15 rows per POST
    sent = deferred = 0
    for n in range(10):
        res = remote_sync.post_discoveries("http://api", body(n))  # never raises on denial
        deferred = res["deferred"]
    sent = len(calls)
    assert sent == 6 and deferred == 12  # 6 x 15 = 90 rows posted; 4 batches of 3 items stay buffered
    assert wb.get_budget().used() == 90
    clock.t = utc(2026, 10, 28, 0, 0, 5)  # new UTC day: the buffered items go out within the new allowance
    res = remote_sync.post_discoveries("http://api", {})
    assert res.get("deferred", 0) < 12 and len(calls) > sent


def test_post_discoveries_backs_off_for_900s_on_x_degraded(net, monkeypatch):
    calls, state = net
    monkeypatch.setenv("D1_DAILY_WRITE_BUDGET", "70000")
    clock = Clock(utc(2026, 10, 27, 12))
    wb.reset_budget(wb.WriteBudget(name="sound", clock=clock))
    state["resp"] = FakeResp(503, {"error": "free_tier_limit"}, {"X-Degraded": "free_tier_limit", "Retry-After": "900"})
    r1 = remote_sync.post_discoveries("http://api", {"static_sound": [{"key": "a"}]})
    assert r1["deferred"] == 1 and len(calls) == 1
    assert wb.get_budget().backoff_remaining() == pytest.approx(900, abs=2)
    state["resp"] = FakeResp(200, {"results": {}})
    remote_sync.post_discoveries("http://api", {"static_sound": [{"key": "b"}]})
    assert len(calls) == 1  # nothing is sent during the back-off
    clock.t += 901
    api_client.reset_free_tier_cooldown()  # the in-process cooldown uses wall time; simulate it expiring too
    res = remote_sync.post_discoveries("http://api", {})
    assert res["deferred"] == 0 and len(calls) == 2
    assert {i["key"] for i in calls[-1][2]["static_sound"]} == {"a", "b"}


def test_buffers_can_be_switched_off(net, monkeypatch):
    calls, _ = net
    monkeypatch.setenv("WRITE_BUFFERS", "0")
    remote_sync.post_discoveries("http://api", {"static_sound": [{"key": "a"}]})
    assert len(calls) == 1
    assert not (wbuf.buffer_dir() / "sound.discoveries.json").exists()


# ---------------------------------------------------------------------------------------------------------
# LinguisticCoalescer
# ---------------------------------------------------------------------------------------------------------
def ling(span, domain="color", count=None, canonical="dark"):
    d = {"span": span, "canonical": canonical, "domain": domain}
    if count:
        d["count"] = count
    return d


def test_linguistic_bumps_are_summed_into_one_batched_upsert_per_interval():
    clock = Clock()
    c = wbuf.LinguisticCoalescer("interpret", flush_interval=900, flush_max_items=40, clock=clock)
    p = Poster()
    for _ in range(50):
        c.add([ling("dusk"), ling("Dusk ", count=2), ling("glow", domain="light")])
        assert c.flush("http://api", poster=p)["queued"] == 2  # nothing leaves inside the interval
    assert not p.calls
    clock.t += 901
    res = c.flush("http://api", poster=p)
    assert len(p.calls) == 1 and res["queued"] == 0
    items = {(i["domain"], i["span"].strip().lower()): i["count"] for i in p.calls[0][1]["items"]}
    assert items == {("color", "dusk"): 150, ("light", "glow"): 50}


def test_linguistic_flushes_at_max_items_and_sends_unseen_spans_first():
    c = wbuf.LinguisticCoalescer("interpret", flush_interval=900, flush_max_items=3)
    p = Poster()
    c._seen.add("color|old")
    c.add([ling("old", count=50), ling("new1"), ling("new2")])
    c.flush("http://api", poster=p)
    spans = [i["span"] for i in p.calls[0][1]["items"]]
    assert spans[-1] == "old" and set(spans[:2]) == {"new1", "new2"}


def test_linguistic_denied_by_budget_stays_queued_and_persists():
    c = wbuf.LinguisticCoalescer("interpret", flush_interval=0)
    p = Poster()
    p.fail = api_client.WriteBudgetSkipped("no", status_code=503, path="/api/linguistic-registry/batch")
    c.add([ling("dusk", count=3)])
    assert c.flush("http://api", poster=p)["skipped"] == "budget"
    assert len(wbuf.LinguisticCoalescer("interpret")) == 1


def test_post_linguistic_growth_routes_through_the_coalescer(net, monkeypatch):
    calls, state = net
    monkeypatch.setenv("LINGUISTIC_FLUSH_INTERVAL_S", "900")
    wbuf.reset_buffers()
    for _ in range(5):
        res = linguistic_client.post_linguistic_growth("http://api", [ling("dusk")])
    assert res["queued"] == 1 and not calls
    assert wbuf.get_linguistic_coalescer().flush("http://api", force=True)["queued"] == 0
    assert calls[0][2]["items"][0]["count"] == 5


# ---------------------------------------------------------------------------------------------------------
# InterpretationOutbox
# ---------------------------------------------------------------------------------------------------------
def instr(**kw):
    return {"duration": 6.0, "colors": ["red"], **kw}


def test_interpretation_only_novel_prompt_and_shape_become_rows(tmp_path):
    o = wbuf.InterpretationOutbox("interpret", flush_interval=600, flush_max_items=10)
    assert o.record("a red sun", instr(), "generate") == "queued"
    assert o.record("A red sun", instr(), "generate") == "dropped"          # same prompt: no row, no log
    assert o.record("a crimson sun", instr(), "generate") == "local"        # new prompt, same instruction shape
    assert o.record("a blue sea", instr(colors=["blue"]), "generate") == "queued"
    assert len(o) == 2
    lines = [json.loads(x) for x in o.jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert [l["prompt"] for l in lines] == ["a crimson sun"]
    assert o.seen("a red sun") and not o.seen("never seen")


def test_interpretation_outbox_flushes_in_batches_on_interval_and_survives_restart():
    clock = Clock()
    o = wbuf.InterpretationOutbox("interpret", flush_interval=600, flush_max_items=10, clock=clock)
    p = Poster()
    for i in range(3):
        o.record(f"prompt {i}", instr(colors=[f"c{i}"]))
    assert o.flush("http://api", poster=p)["queued"] == 3 and not p.calls
    o2 = wbuf.InterpretationOutbox("interpret", flush_interval=600, flush_max_items=10, clock=clock)
    assert len(o2) == 3 and o2.seen("prompt 1")
    clock.t += 601
    res = o2.flush("http://api", poster=p)
    assert res["inserted"] == 3 and len(p.calls) == 1 and p.calls[0][0] == "/api/interpretations/batch"


def test_interpretation_outbox_budget_denial_keeps_the_batch():
    o = wbuf.InterpretationOutbox("interpret", flush_interval=0)
    o.record("p1", instr())
    p = Poster()
    p.fail = api_client.WriteBudgetSkipped("no", status_code=503, path="/api/interpretations/batch")
    assert o.flush("http://api", poster=p)["skipped"] == "budget" and len(o) == 1


def test_interpretation_signature_ignores_free_text_and_float_noise():
    a = wbuf.instruction_signature({"duration": 6.0001, "prompt": "x", "colors": ["red"]})
    b = wbuf.instruction_signature({"duration": 6.0, "prompt": "y", "colors": ["red"]})
    assert a == b


# ---------------------------------------------------------------------------------------------------------
# idle_when_exhausted
# ---------------------------------------------------------------------------------------------------------
def test_idle_when_exhausted_is_off_by_default_and_waits_out_backoff_when_enabled(monkeypatch):
    monkeypatch.setenv("D1_BUDGET_NAME", "sound")
    clock = Clock(utc(2026, 10, 27, 12))
    b = wb.WriteBudget(name="sound", clock=clock)
    wb.reset_budget(b)
    b.start_backoff(900, "test")
    assert wbuf.idle_when_exhausted() == 0.0
    monkeypatch.setenv("WRITE_BUDGET_SLEEP_WHEN_EXHAUSTED_S", "300")
    assert wbuf.idle_when_exhausted() == 300.0
    b.clear_backoff()
    assert wbuf.idle_when_exhausted() == 0.0
    assert b.reserve(b.allowance())
    assert wbuf.idle_when_exhausted() == 300.0
