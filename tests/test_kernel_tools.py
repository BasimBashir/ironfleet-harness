import pytest
from harness.module_e.kernel_tools import statutory_demand, without_prejudice

VALID = {"amount": "5000.00", "debtor_company": "Debtor Co Ltd",
         "creditor": "Creditor Ltd", "debt_details": "Invoice INV-001, overdue 90 days",
         "service_date": "2026-03-02", "trust_tier": "T2"}

# ── statutory_demand (s 289 Companies Act 1993) ──────────────────────────────

def test_valid_demand_returns_no_issues_and_a_deadline():
    r = statutory_demand(VALID)
    assert r["is_valid"] is True
    assert r["issues"] == []
    assert r["compliance_deadline"] is not None
    assert r["compliance_period_days"] == 15            # s 241(4)(a) statutory minimum
    assert r["compliance_period_day_type"] == "working"  # nz pack day_type

def test_demand_below_the_prescribed_minimum_is_invalid():
    r = statutory_demand({**VALID, "amount": "500.00"})
    assert r["is_valid"] is False
    assert any("prescribed minimum" in i for i in r["issues"])

def test_amounts_use_exact_decimal_not_float():
    # _to_decimal + Decimal ROUND_HALF_UP, never binary float rounding
    r = statutory_demand({**VALID, "amount": "1000.005"})
    assert r["amount"] == 1000.01

def test_missing_debtor_creditor_and_details_each_produce_an_issue():
    r = statutory_demand({**VALID, "debtor_company": "", "creditor": "",
                          "debt_details": ""})
    assert r["is_valid"] is False
    assert len(r["issues"]) == 3

def test_placeholder_names_are_rejected():
    r = statutory_demand({**VALID, "creditor": "unknown creditor"})
    assert r["is_valid"] is False
    assert any("placeholder" in i for i in r["issues"])

def test_compliance_period_below_the_statutory_minimum_is_flagged():
    r = statutory_demand({**VALID, "compliance_period": 10})
    assert r["is_valid"] is False
    assert any("statutory minimum" in i for i in r["issues"])

def test_missing_required_args_fail_loud():
    # CHARACTERISATION (adjusted): the brief expected TypeError, and the wrapper docstring
    # claims TypeError. Observed: KeyError — `args["debtor_company"]` indexes the dict before
    # the kernel ever sees a missing positional. It still fails loudly, which is what the test
    # is really pinning; the exception type is a finding for the Task 10 dispatcher to handle.
    with pytest.raises(KeyError):
        statutory_demand({"amount": "5000.00"})       # required key omitted

# ── without_prejudice (correspondence classification) ────────────────────────

def test_wp_header_classifies_without_prejudice():
    r = without_prejudice({"content": "WITHOUT PREJUDICE\n\nWe propose settling at 60 cents.",
                           "trust_tier": "T2"})
    # CHARACTERISATION (adjusted): the brief's API note claims status "OK"; the vendored
    # detector's classified path actually returns "SUCCESS" (ERROR / FLAGGED / SUCCESS).
    assert r["status"] == "SUCCESS"
    assert r["result"]["wp_status"] == "WP"
    assert r["result"] is not None

def test_open_correspondence_is_not_flagged():
    r = without_prejudice({"content": "We deny liability in full and will see you in court.",
                           "trust_tier": "T2"})
    # CHARACTERISATION (adjusted): "OK" -> "SUCCESS", as above. The brief suspected this
    # fixture might trip the settlement-context FLAG path; it does not — "in full and" alone
    # is not an indicator ("in full and final settlement" is the full phrase), so this
    # classifies OPEN at confidence 0.99, above the 0.90 OPEN gate.
    assert r["status"] == "SUCCESS"
    assert r["result"]["wp_status"] == "OPEN"

def test_missing_required_field_is_an_error_not_a_guess():
    for payload in [{"content": "x"}, {"trust_tier": "T2"}]:
        r = without_prejudice(payload)
        assert r["status"] == "ERROR"
        assert r["error"]["type"] == "MALFORMED_INPUT"

def test_t0_content_requires_an_operator_override():
    r = without_prejudice({"content": "WITHOUT PREJUDICE offer.", "trust_tier": "T0"})
    assert r["status"] == "ERROR"
    assert "[T0-CONTENT-BLOCKED]" in r["flags"]

def test_conflicting_wp_and_wpsatc_signals_are_flagged_for_review():
    r = without_prejudice({"content": "WITHOUT PREJUDICE\nWITHOUT PREJUDICE SAVE AS TO COSTS",
                           "trust_tier": "T2"})
    assert r["status"] == "FLAGGED"
    assert "[WP-STATUS-UNCERTAIN" in " ".join(r["flags"])

def test_wpsatc_is_distinguished_from_plain_wp():
    r = without_prejudice({"content": "WITHOUT PREJUDICE SAVE AS TO COSTS — offer 40c.",
                           "trust_tier": "T2"})
    # CHARACTERISATION (adjusted): "OK" -> "SUCCESS", as above. The brief suspected this
    # fixture might FLAG; it does not — the WPSATC header wins and `_WP_HEADER`'s negative
    # lookahead (?!\s+SAVE AS TO COSTS) suppresses the plain-WP header match, so there is no
    # WP/WPSATC conflict. Classification: WPSATC at 0.9, no flags.
    assert r["status"] == "SUCCESS"
    assert r["result"]["wp_status"] == "WPSATC"
