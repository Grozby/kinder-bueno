import pytest

from navigator.extract import check_items, parse_items, salvage_rows, split_text
from navigator.llm import LLMError, parse_json_object
from navigator.verify import PageText

PAGE_TEXT = "Odening Lab\nTranslational Cardiology / Electrophysiology\nProf. Dr. Katja Odening\nGroup Leader"


def test_parse_json_object_plain_and_wrapped():
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object('Sure! Here it is:\n```json\n{"a": {"b": 2}}\n```') == {"a": {"b": 2}}
    with pytest.raises(LLMError):
        parse_json_object("no json here")
    with pytest.raises(LLMError):
        parse_json_object("[1, 2]")


def test_parse_items_keeps_good_and_drops_bad_items_individually():
    data = {
        "claims": [
            {"entity_type": "person", "entity_name": "Katja Odening", "field": "role", "value": "Group Leader", "quote": "Group Leader"},
            {"entity_type": "person", "entity_name": "X", "field": "unit_type", "value": "lab", "quote": "q"},  # field not for person
            {"entity_type": "robot", "entity_name": "X", "field": "name", "value": "X", "quote": "X"},          # unknown type
            {"entity_type": "unit", "entity_name": "  ", "field": "name", "value": "X", "quote": "X"},          # blank name
            {"entity_type": "unit", "entity_name": "Odening Lab", "field": "name", "value": None, "quote": "X"},  # null value
        ],
        "relations": [
            {"from_type": "person", "from_name": "Katja Odening", "rel": "member_of", "to_type": "unit", "to_name": "Odening Lab", "quote": "Odening Lab"},
            {"from_type": "unit", "from_name": "Odening Lab", "rel": "member_of", "to_type": "unit", "to_name": "DBMR", "quote": "x"},  # wrong types
        ],
    }
    claims, relations, dropped = parse_items(data)
    assert [c.field for c in claims] == ["role"]
    assert [r.rel for r in relations] == ["member_of"]
    assert dropped == 5


def test_parse_items_accepts_compact_rows():
    claims, relations, dropped = parse_items({
        "claims": [
            ["person", "Katja Odening", "role", "Group Leader", "Prof. Dr. Katja Odening\nGroup Leader"],
            ["person", "Katja Odening", "role"],  # wrong length
        ],
        "relations": [["person", "Katja Odening", "member_of", "unit", "Odening Lab", "Odening Lab"]],
    })
    assert claims[0].entity_name == "Katja Odening" and claims[0].value == "Group Leader"
    assert relations[0].to_name == "Odening Lab"
    assert dropped == 1


def test_parse_items_handles_missing_keys():
    assert parse_items({}) == ([], [], 0)
    assert parse_items({"claims": None}) == ([], [], 0)


def test_check_items_verifies_against_page():
    claims, relations, _ = parse_items({
        "claims": [
            {"entity_type": "unit", "entity_name": "Odening Lab", "field": "expertise", "value": "cardiac electrophysiology",
             "quote": "Translational Cardiology / Electrophysiology"},
            {"entity_type": "unit", "entity_name": "Odening Lab", "field": "expertise", "value": "heart valves",
             "quote": "The lab builds artificial heart valves."},
        ],
        "relations": [
            {"from_type": "person", "from_name": "Katja Odening", "rel": "member_of", "to_type": "unit",
             "to_name": "Odening Lab", "quote": "Prof. Dr. Katja Odening"},
        ],
    })
    checked_claims, checked_relations = check_items(PageText(PAGE_TEXT), claims, relations)
    assert [c.verified for c in checked_claims] == [True, False]
    assert checked_claims[1].fail_reason == "quote not on page"
    assert checked_relations[0].verified


def test_split_text():
    assert split_text("a\nb\nc", max_chars=3) == ["a\nb", "c"]
    assert split_text("short") == ["short"]
    assert split_text("x" * 7, max_chars=3) == ["xxx", "xxx", "x"]
    long = "\n".join(["line"] * 5000)
    parts = split_text(long)
    assert all(len(p) <= 6_000 for p in parts)
    assert "\n".join(parts) == long


def test_salvage_rows_from_cut_off_answer():
    text = ('{"claims": [["person", "Ann Lee", "role", "PhD Student", "Ann Lee\\nPhD Student"], '
            '["person", "Ann Lee", "role", "PhD Student", "Ann Lee\\nPhD Student"], '
            '["unit", "Lab \\"X\\"", "name", "Lab X", "Lab X"]], '
            '"relations": [["person", "Ann Lee", "member_of", "unit", "Lab X", "Ann Lee"], ["person", "Bo')
    data = salvage_rows(text)
    assert data["claims"] == [
        ["person", "Ann Lee", "role", "PhD Student", "Ann Lee\nPhD Student"],  # duplicate removed
        ["unit", 'Lab "X"', "name", "Lab X", "Lab X"],
    ]
    assert data["relations"] == [["person", "Ann Lee", "member_of", "unit", "Lab X", "Ann Lee"]]


def test_relation_row_inside_claims_is_routed():
    claims, relations, dropped = parse_items({
        "claims": [["person", "Katja Odening", "member_of", "unit", "Odening Lab", "Katja Odening"]],
    })
    assert (len(claims), len(relations), dropped) == (0, 1, 0)
