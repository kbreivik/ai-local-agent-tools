"""v2.38.0 — analysis_templates module — schema + param validation."""
import pytest
from api import analysis_templates as at


def test_every_template_has_required_fields():
    for tid, tpl in at.TEMPLATES.items():
        assert "title" in tpl and tpl["title"], f"{tid}: missing title"
        assert "description" in tpl and tpl["description"], f"{tid}: missing description"
        assert "sql" in tpl and "%(row_cap)s" in tpl["sql"], (
            f"{tid}: SQL must use named %(row_cap)s parameter for LIMIT"
        )
        assert "params" in tpl and isinstance(tpl["params"], list), f"{tid}: params not a list"
        assert "row_cap" in tpl and 1 <= tpl["row_cap"] <= 10_000, f"{tid}: row_cap out of range"


def test_no_template_uses_positional_placeholders():
    """%s is ambiguous with multiple params — force named %(name)s."""
    import re
    POSITIONAL = re.compile(r"(?<!%)%s\b")  # %s not preceded by another %
    for tid, tpl in at.TEMPLATES.items():
        # Ignore the percent literal in INTERVAL '...' strings
        assert not POSITIONAL.search(tpl["sql"]), (
            f"{tid}: SQL contains bare %s — use %(name)s instead"
        )


def test_list_templates_omits_sql():
    """list_templates() must not leak raw SQL to the client."""
    for t in at.list_templates():
        assert "sql" not in t


def test_validate_params_required_missing():
    tpl = at.get_template("operation_full_context")
    with pytest.raises(ValueError):
        at.validate_params(tpl, {})


def test_validate_params_uuid_bad():
    tpl = at.get_template("operation_full_context")
    with pytest.raises(ValueError):
        at.validate_params(tpl, {"operation_id": "not-a-uuid"})


def test_validate_params_uuid_ok():
    tpl = at.get_template("operation_full_context")
    out = at.validate_params(tpl, {"operation_id": "9a23e276-1234-1234-1234-123456789012"})
    assert out["operation_id"] == "9a23e276-1234-1234-1234-123456789012"
    assert out["row_cap"] == 1


def test_validate_params_int_defaults_and_bounds():
    tpl = at.get_template("recent_failures")
    # All defaults
    out = at.validate_params(tpl, {})
    assert out["hours"] == 24
    assert out["agent_type"] == "any"
    # Custom value in range
    out2 = at.validate_params(tpl, {"hours": 5})
    assert out2["hours"] == 5
    # Out of range
    with pytest.raises(ValueError):
        at.validate_params(tpl, {"hours": 0})
    with pytest.raises(ValueError):
        at.validate_params(tpl, {"hours": 10_000})


def test_validate_params_row_cap_clamped():
    tpl = at.get_template("recent_failures")
    out = at.validate_params(tpl, {"hours": 24})
    assert out["row_cap"] == tpl["row_cap"]
    assert 1 <= out["row_cap"] <= 10_000


def test_validate_params_drops_unknown_keys():
    tpl = at.get_template("recent_failures")
    out = at.validate_params(tpl, {"hours": 5, "rogue": "DROP TABLE"})
    assert "rogue" not in out
