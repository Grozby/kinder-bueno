from navigator.verify import PageText, norm, normalise_with_map, verify_claim, verify_relation

PAGE = PageText(
    "Group Members\n"
    "Prof. Dr. Dominik  Obrist\n"
    "Funktion\n"
    "Professor for Cardiovascular Engineering\n"
    "Mail\n"
    "dominik.obrist@unibe.ch\n"
    "The lab studies “heart valve” dynamics – with new imaging methods."
)


def test_norm():
    assert norm("  A “B”\n\n– c  ") == 'a "b" - c'


def test_normalise_map_points_to_original_chars():
    normed, origin = normalise_with_map("Ab\n\n  C")
    assert normed == "ab c"
    assert origin == [0, 1, 2, 6]


def test_exact_match():
    m = verify_claim(PAGE, "Dominik Obrist", "role", "Professor for Cardiovascular Engineering",
                     "Professor for Cardiovascular Engineering")
    assert m.ok and not m.fuzzy
    assert m.quote == "Professor for Cardiovascular Engineering"


def test_whitespace_and_line_breaks_match_and_return_original_text():
    m = verify_claim(PAGE, "Dominik Obrist", "name", "Dominik Obrist", "Prof. Dr. Dominik Obrist")
    assert m.ok
    assert m.quote == "Prof. Dr. Dominik  Obrist"  # exact page text, double space kept


def test_curly_quotes_and_dashes():
    m = verify_claim(PAGE, "Dominik Obrist", "expertise", "heart valve dynamics",
                     'The lab studies "heart valve" dynamics - with new imaging methods.')
    assert m.ok
    assert m.quote == "The lab studies “heart valve” dynamics – with new imaging methods."


def test_case_difference():
    assert verify_claim(PAGE, "dominik obrist", "email", "DOMINIK.OBRIST@unibe.ch", "Dominik.Obrist@unibe.ch").ok


def test_fuzzy_fallback_fixes_small_copy_errors():
    m = verify_claim(PAGE, "Dominik Obrist", "expertise", "heart valve dynamics",
                     'The lab studies "heart valve" dynamics with new imaging methods.')  # dash dropped
    assert m.ok and m.fuzzy
    assert m.quote == "The lab studies “heart valve” dynamics – with new imaging methods."  # exact page text


def test_fuzzy_fallback_rejects_paraphrase():
    m = verify_claim(PAGE, "Dominik Obrist", "expertise", "heart valve dynamics",
                     "The lab investigates heart valve dynamics using novel imaging methods.")
    assert not m.ok


def test_invented_quote_rejected():
    m = verify_claim(PAGE, "Dominik Obrist", "expertise", "surgical robotics",
                     "Dominik Obrist develops robots for minimally invasive surgery.")
    assert not m.ok
    assert m.reason == "quote not on page"


def test_role_not_on_page_rejected():
    m = verify_claim(PAGE, "Dominik Obrist", "role", "Head of Surgery", "Professor for Cardiovascular Engineering")
    assert not m.ok
    assert m.reason == "role value not in quote"


TEAM = PageText("Core Team\nCFO/COO/HRM\nLorenz Burkhalter\nlorenz.burkhalter@dcberne.com\n"
                "HR Specialist\nIvona Weinaug\nivona.weinaug@dcberne.com\n" + "Filler text. " * 30 +
                "\nCEO\nDerek Brandt")


def test_reordered_role_quote_is_rebuilt_from_the_page():
    m = verify_claim(TEAM, "Lorenz Burkhalter", "role", "CFO/COO/HRM", "Lorenz Burkhalter\nCFO/COO/HRM")
    assert m.ok and m.rebuilt
    assert m.quote == "CFO/COO/HRM\nLorenz Burkhalter"  # exact page text, page order


def test_rebuild_picks_the_nearest_value():
    m = verify_claim(TEAM, "Ivona Weinaug", "email", "ivona.weinaug@dcberne.com", "wrong")
    assert m.quote == "Ivona Weinaug\nivona.weinaug@dcberne.com"


def test_rebuild_rejects_values_far_from_the_name():
    # "CEO" belongs to Derek Brandt, far away from Lorenz Burkhalter on the page
    assert not verify_claim(TEAM, "Lorenz Burkhalter", "role", "CEO", "Lorenz Burkhalter\nCEO").ok


def test_name_claim_uses_the_name_on_the_page():
    m = verify_claim(TEAM, "Derek Brandt", "name", "Derek Brandt", "In the following ongoing projects")
    assert m.ok and m.quote == "Derek Brandt"


def test_entity_must_be_on_page():
    m = verify_claim(PAGE, "Anna Muster", "role", "Professor", "Professor for Cardiovascular Engineering")
    assert not m.ok
    assert m.reason == "entity name not on page"


def test_expertise_value_may_paraphrase():
    # Topic phrases are summaries; the quote must be on the page, the value need not be in it.
    assert verify_claim(PAGE, "Dominik Obrist", "expertise", "cardiovascular engineering",
                        "Professor for Cardiovascular Engineering").ok


def test_short_quotes_are_not_fuzzy_matched():
    assert not PAGE.find_quote("Mail x").ok


def test_relation():
    quote = "Professor for Cardiovascular Engineering"
    assert verify_relation(PAGE, "Dominik Obrist", "Cardiovascular Engineering", quote).ok
    assert not verify_relation(PAGE, "Dominik Obrist", "Image-Guided Therapy", quote).ok
