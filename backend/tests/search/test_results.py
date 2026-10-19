"""build_results on the fixture graph (tests/conftest.py). Needs Postgres."""

from navigator.search.results import build_results


def by_name(results):
    return {r.name: r for r in results}


def test_unsupported_and_unverified_claims_are_hidden(test_conn, graph):
    results = build_results(test_conn, [(graph["alice"], 1.0), (graph["carol"], 1.0)])
    alice = by_name(results)["Alice Muster"]
    assert alice.expertise == ["continuous glucose monitoring", "diabetes technology"]
    assert graph["alice_robotics"] not in {e.claim_id for e in alice.evidence}
    assert "surgical robotics" not in {e.value for e in alice.evidence}


def test_entity_without_shown_claims_is_skipped(test_conn, graph):
    results = build_results(test_conn, [(graph["carol"], 5.0)])
    assert results == []


def test_rank_order_and_scores_are_kept(test_conn, graph):
    ranked = [(graph["bob"], 3.0), (graph["carol"], 2.0), (graph["alice"], 1.0), (graph["lab"], 0.5)]
    results = build_results(test_conn, ranked)
    assert [(r.name, r.score) for r in results] == [("Bob Beispiel", 3.0), ("Alice Muster", 1.0), ("Diabetes Lab", 0.5)]


def test_relations_fill_affiliations_projects_infrastructure(test_conn, graph):
    results = by_name(build_results(test_conn, [(graph["alice"], 1), (graph["bob"], 1), (graph["lab"], 1)]))
    assert results["Alice Muster"].affiliations == ["Diabetes Lab"]  # unverified member_of hidden
    assert results["Alice Muster"].projects == ["Artificial Pancreas"]
    assert results["Bob Beispiel"].affiliations == ["ARTORG Center"]  # unsupported member_of hidden
    assert results["Diabetes Lab"].affiliations == ["ARTORG Center"]  # part_of
    assert results["Diabetes Lab"].infrastructure == ["Cleanroom"]


def test_role_and_contact(test_conn, graph):
    alice = build_results(test_conn, [(graph["alice"], 1.0)])[0]
    assert alice.type == "person"
    assert alice.role == ["Professor"]
    assert alice.contact == ["alice@example.org", "+41 31 000 00 00"]


def test_evidence_carries_claim_id_url_and_verdict(test_conn, graph):
    alice = build_results(test_conn, [(graph["alice"], 1.0)])[0]
    evidence = {e.claim_id: e for e in alice.evidence if e.via_unit is None}
    assert len(evidence) == 5
    partial = evidence[graph["alice_diabetes"]]
    assert (partial.field, partial.url) == ("expertise", "https://artorg.example/lab")
    assert (partial.judge_verdict, partial.judge_reason) == ("partial", "broader")
    assert evidence[graph["alice_email"]].url == "https://artorg.example/alice"
    assert alice.sources == ["https://artorg.example/alice", "https://artorg.example/lab"]


def test_why_default_and_override(test_conn, graph):
    alice, bob = build_results(test_conn, [(graph["alice"], 2.0), (graph["bob"], 1.0)], why={graph["bob"]: "Custom."})
    assert alice.why == "Matches on: continuous glucose monitoring, diabetes technology"
    assert bob.why == "Custom."


def test_person_gets_unit_topics_labelled_as_the_units(test_conn, graph):
    alice, bob, lab = build_results(test_conn, [(graph["alice"], 3), (graph["bob"], 2), (graph["lab"], 1)])
    assert alice.unit_topics == ["insulin pumps"]
    assert "insulin pumps" not in alice.expertise  # never copied into personal expertise
    row = next(e for e in alice.evidence if e.via_unit)
    assert (row.claim_id, row.field, row.via_unit) == (graph["lab_expertise"], "unit_expertise", "Diabetes Lab")
    assert row.url == "https://artorg.example/lab"
    assert bob.unit_topics == []  # his link to the lab is judged unsupported; the center has no topics
    assert lab.unit_topics == []  # only persons get unit topics


def test_why_falls_back_to_unit_topics(test_conn, graph):
    dana = test_conn.execute(
        "INSERT INTO entity (type, name, norm_key) VALUES ('person', 'Dana Probe', 'dana') RETURNING id"
    ).fetchone()[0]
    test_conn.execute(
        "INSERT INTO claim (entity_id, field, value, quote, page_id, verified) VALUES (%s, 'role', 'PhD Student', 'q', %s, true)",
        (dana, graph["p2"]),
    )
    test_conn.execute(
        "INSERT INTO relation (from_id, rel, to_id, quote, page_id, verified) VALUES (%s, 'listed_in', %s, 'Dana Probe', %s, true)",
        (dana, graph["lab"], graph["p2"]),
    )
    (result,) = build_results(test_conn, [(dana, 1.0)])
    assert result.expertise == []
    assert result.unit_topics == ["insulin pumps"]
    assert result.why == "In Diabetes Lab, which works on: insulin pumps"


def test_unit_topics_are_capped_deduplicated_and_prefer_the_listed_lab(test_conn, graph):
    def add(sql, *args):
        return test_conn.execute(sql + " RETURNING id", args).fetchone()[0]

    erin = add("INSERT INTO entity (type, name, norm_key) VALUES ('person', 'Erin Test', 'erin')")
    add("INSERT INTO claim (entity_id, field, value, quote, page_id, verified) VALUES (%s, 'role', 'Postdoc', 'q', %s, true)",
        erin, graph["p2"])
    for i in range(8):  # the umbrella center has many topics, one of them twice
        value = "topic 1" if i == 7 else f"topic {i}"
        add("INSERT INTO claim (entity_id, field, value, quote, page_id, verified) VALUES (%s, 'expertise', %s, 'q', %s, true)",
            graph["center"], value, graph["p2"])
    for rel, unit in (("member_of", "center"), ("listed_in", "lab")):
        add("INSERT INTO relation (from_id, rel, to_id, quote, page_id, verified) VALUES (%s, %s, %s, 'q', %s, true)",
            erin, rel, graph[unit], graph["p2"])
    (result,) = build_results(test_conn, [(erin, 1.0)])
    via = [e.via_unit for e in result.evidence if e.via_unit]
    assert via[0] == "Diabetes Lab"  # the listed lab first, though member_of was added first
    assert via.count("ARTORG Center") == 5  # capped, duplicates removed
    assert result.unit_topics[:2] == ["insulin pumps", "topic 0"]
