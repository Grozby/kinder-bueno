import pytest

from navigator.extract import Claim, check_items, is_person_name, parse_items, reverify, salvage_rows, split_text
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


@pytest.mark.parametrize("name, ok", [
    ("Prof. Dr. Stavroula Mougiakakou", True),
    ("Dr. Martina Rothenbühler", True),
    ("Gaëlle Nivlet", True),
    ("Alumni", False),
    ("Phone2", False),
    ("Karkampouna", False),          # lone surname: cannot be told apart
    ("PhD Students", False),         # "phd" is a title, "students" a label
    ("Senior Scientific Staff", True),  # 3 words, not all labels: kept (no false negatives on rare names)
    ("Group Head", False),
    ("Room 3.14 Team", False),
])
def test_is_person_name(name, ok):
    assert is_person_name(name) is ok


def test_label_people_are_rejected_in_claims_and_relations():
    page = PageText("Group Members\nAlumni\nPhone2\n+41 31 684 14 00\nDr. Lucas Patty\nResearch Associate")
    claims, relations, _ = parse_items({
        "claims": [["person", "Alumni", "role", "Alumni", "Alumni"],
                   ["person", "Dr. Lucas Patty", "role", "Research Associate", "Dr. Lucas Patty\nResearch Associate"]],
        "relations": [["person", "Phone2", "member_of", "unit", "Group Members", "Phone2"]],
    })
    checked_claims, checked_relations = check_items(page, claims, relations)
    assert [(c.verified, c.fail_reason) for c in checked_claims] == [(False, "not a person name"), (True, None)]
    assert checked_relations[0].fail_reason == "not a person name"


def test_reverify_rechecks_stored_rows_without_llm():
    text = "Alumni\nCEO\nDerek Brandt"
    rows = [
        ("claim", 1, "Team", text, "person", "Alumni", "role", "Alumni", "Alumni"),
        ("claim", 2, "Team", text, "person", "Derek Brandt", "role", "CEO", "Derek Brandt\nCEO"),  # rebuilt
        ("relation", 7, "Team", text, "person", "Derek Brandt", "member_of", "unit", "Team", "Derek Brandt"),
    ]
    claim_updates, relation_updates = reverify(rows)
    assert claim_updates == [(False, "Alumni", "not a person name", 1), (True, "CEO\nDerek Brandt", None, 2)]
    assert relation_updates == [(True, "Derek Brandt", None, 7)]


def test_copied_example_topics_on_a_team_page_do_not_pass_the_checks():
    """#149: a team page has no research text; topics quoted by its headings fail verification."""
    page = PageText("Team Schroeder Lab\nName / Titel\nProf. Dr. Anna Schroeder\nFunktion\nGroup Leader")
    copied = [Claim(entity_type="unit", entity_name="Schroeder Lab", field="expertise", value=v, quote="Schroeder Lab")
              for v in ("cardiac arrhythmia", "cardiac electrophysiology")]
    checked, _ = check_items(page, copied, [])
    assert [c.verified for c in checked] == [False, False]
