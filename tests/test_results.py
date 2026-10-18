"""build_results on the fixture graph (tests/conftest.py). Needs Postgres."""

from navigator.results import build_results


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
    evidence = {e.claim_id: e for e in alice.evidence}
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
