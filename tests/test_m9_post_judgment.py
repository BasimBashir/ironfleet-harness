# tests/test_m9_post_judgment.py — platform (harness-core) M9 golden cases:
# appeal window, enforcement options, settlement tracking, .ics + court-format
# export, and the new deadline kinds in lifecycle.deadlines.register.
# Golden dates pinned 2026-11-09 from the plugin calendar (plugin is source of
# truth): appeal 20 working days 2026-11-05 -> 2026-12-03, 2026-12-07 ->
# 2027-01-13 (CA 1993 s 2 Christmas closure), 2026-03-02 -> 2026-03-30;
# settlement 30 calendar days 2026-03-02 -> 2026-04-01.
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from harness.lifecycle import deadlines, dossier
from harness.module_e import export_calendar, export_court, post_judgment as pj
from harness.module_e.vendored.jurisdiction_loader import JurisdictionLoader
from harness.workflow.db import connect

MATTER = "m9-matter"


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "platform.db")
    yield c
    c.close()


# ------------------------------------------------------------- appeal kernel

def test_appeal_window_is_20_working_days_from_the_pack():
    cfg = JurisdictionLoader.load("nz")
    out = pj.appeal_window("2026-11-05")
    assert out["days"] == cfg.appeal_days == 20
    assert out["day_type"] == "working"
    assert out["rule_ref"] == "High Court Rules 2016 r 20.4(2)(b)"
    assert out["due"] == "2026-12-03"          # golden, pinned 2026-11-09
    assert out["jurisdiction"] == "nz"


def test_appeal_window_crosses_nz_christmas_closure():
    assert pj.appeal_window("2026-12-07")["due"] == "2027-01-13"


def test_appeal_window_march_monday_golden():
    assert pj.appeal_window("2026-03-02")["due"] == "2026-03-30"


def test_appeal_window_refuses_a_caller_supplied_due():
    with pytest.raises(RuntimeError):
        pj.appeal_window("2026-11-05", due="2027-01-01")


# --------------------------------------------------------- enforcement pack

def test_enforcement_options_come_from_the_pack_not_code():
    cfg = JurisdictionLoader.load("nz")
    out = pj.enforcement_options()
    assert [o["code"] for o in out["options"]] == [o["code"] for o in cfg.enforcement_options]
    assert out["rule_ref"] == "High Court Rules 2016 r 17.3(1)"
    codes = {o["code"] for o in out["options"]}
    assert {"attachment_order", "charging_order", "sale_order",
            "possession_order", "arrest_order", "sequestration_order"} <= codes


def test_enforcement_respects_payment_period_before_issue():
    with pytest.raises(RuntimeError):
        pj.enforcement_issue_date("2026-11-05", process="charging_order",
                                  payment_period_ends="2026-12-01")
    out = pj.enforcement_issue_date("2026-12-01", process="charging_order",
                                    payment_period_ends="2026-12-01")
    assert out["issue_date"] == "2026-12-01"
    assert out["rule_ref"] == "High Court Rules 2016 r 17.3(3)"


def test_enforcement_rejects_unknown_process_loudly():
    with pytest.raises(RuntimeError):
        pj.enforcement_issue_date("2026-12-01", process="vibes",
                                  payment_period_ends="2026-12-01")


# ------------------------------------------------------- settlement tracking

def test_settlement_milestone_is_calendar_days_from_pack():
    cfg = JurisdictionLoader.load("nz")
    out = pj.settlement_milestone("2026-03-02", days=30)
    assert out["day_type"] == cfg.settlement_milestone_day_type == "calendar"
    assert out["due"] == "2026-04-01"          # golden, pinned 2026-11-09
    assert out["rule_ref"] == cfg.settlement_milestone_ref


def test_settlement_milestone_refuses_due():
    with pytest.raises(RuntimeError):
        pj.settlement_milestone("2026-03-02", days=30, due="2026-04-15")


def test_settlement_track_registers_each_milestone_as_a_deadline(con):
    out = pj.settlement_track(con, MATTER, ["deposit 30 days", "balance on completion"],
                              service_date="2026-03-02",
                              milestones=[{"what": "deposit", "days": 30},
                                          {"what": "balance", "days": 60}])
    assert [r["due"] for r in out["rows"]] == ["2026-04-01", "2026-05-01"]
    assert all(r["row"]["source"] == "kernel" and r["row"]["kind"] == "settlement"
               for r in out["rows"])
    got = dossier.read(con, MATTER, "deadlines")["deadlines"]
    assert [g["what"] for g in got] == ["deposit", "balance"]


# ------------------------------------------------------- deadline kinds (M9)

def test_deadline_register_accepts_appeal_and_settlement_kinds(con):
    ap = deadlines.register(con, MATTER, "notice of appeal", "2026-11-05",
                            kind="appeal")
    assert ap["due"] == "2026-12-03"
    assert ap["row"]["kind"] == "appeal"
    st = deadlines.register(con, MATTER, "deposit", "2026-03-02",
                            kind="settlement", days=30)
    assert st["due"] == "2026-04-01"
    assert st["row"]["kind"] == "settlement"


def test_deadline_register_still_refuses_model_due_with_new_kinds(con):
    with pytest.raises(RuntimeError):
        deadlines.register(con, MATTER, "x", "2026-11-05", kind="appeal",
                           due="2027-01-01")


# ------------------------------------------------------------------ .ics export

def test_ics_export_writes_vevents_for_open_deadlines(con, tmp_path):
    deadlines.register(con, MATTER, "notice of appeal", "2026-11-05",
                       kind="appeal", missed_consequence="right of appeal lost")
    out = export_calendar.export_ics(con, MATTER, str(tmp_path / "deadlines.ics"),
                                     base_dir=tmp_path)
    text = Path(out["path"]).read_text(encoding="utf-8")
    assert text.startswith("BEGIN:VCALENDAR")
    assert "BEGIN:VEVENT" in text and "END:VEVENT" in text
    assert "DTSTART;VALUE=DATE:20261203" in text
    assert "SUMMARY:notice of appeal" in text
    assert "right of appeal lost" in text
    assert "END:VCALENDAR" in text
    assert out["events"] == 1


def test_ics_export_refuses_a_path_outside_the_base(con, tmp_path):
    with pytest.raises(RuntimeError):
        export_calendar.export_ics(con, MATTER,
                                   str(tmp_path / ".." / "escape.ics"),
                                   base_dir=tmp_path)


# ------------------------------------------------------- court-format export

def test_docx_export_is_a_valid_zip_with_the_matter_text(con, tmp_path):
    dossier.append(con, MATTER, "facts",
                   {"op": "set", "field": "judgment", "value": "$126,000"})
    out = export_court.export_court_pack(con, MATTER, str(tmp_path / "pack.docx"),
                                         fmt="docx", base_dir=tmp_path)
    z = zipfile.ZipFile(out["path"])
    doc = z.read("word/document.xml").decode("utf-8")
    assert "[Content_Types].xml" in z.namelist()
    assert "$126,000" in doc
    assert "<w:p" in doc                       # at least one paragraph


def test_pdf_export_starts_pdf_and_carries_text(con, tmp_path):
    out = export_court.export_court_pack(con, MATTER, str(tmp_path / "pack.pdf"),
                                         fmt="pdf", base_dir=tmp_path)
    raw = Path(out["path"]).read_bytes()
    assert raw.startswith(b"%PDF-1.4")
    assert b"BT" in raw and b"ET" in raw        # a text block
    assert b"%%EOF" in raw


def test_export_refuses_format_and_escape(con, tmp_path):
    with pytest.raises(RuntimeError):
        export_court.export_court_pack(con, MATTER, str(tmp_path / "x.pptx"),
                                       fmt="pptx", base_dir=tmp_path)
    with pytest.raises(RuntimeError):
        export_court.export_court_pack(con, MATTER,
                                       str(tmp_path / ".." / "escape.pdf"),
                                       fmt="pdf", base_dir=tmp_path)
