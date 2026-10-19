import pytest

from navigator.ingest.verify import PageText, is_sentence, names_topic, norm, normalise_with_map, verify_claim, verify_relation

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


TEAM_PAGE = PageText("Team Bally Lab\nName / Titel\nDr. med. Lia Bally\nFunktion\nGroup Leader")
LAB_PAGE = PageText("Odening Lab\nTranslational Cardiology / Electrophysiology\n"
                    "Our research is focused on advancing the mechanistic understanding of cardiac arrhythmias.")


@pytest.mark.parametrize("quote", ["Team Bally Lab", "Group Leader", "Name / Titel"])
def test_topic_quoted_by_a_heading_that_does_not_name_it_is_rejected(quote):
    """#149: on a team page 8B copied the prompt example's topics and quoted a heading as evidence."""
    m = verify_claim(TEAM_PAGE, "Bally Lab", "expertise", "cardiac electrophysiology", quote)
    assert not m.ok and m.reason == "topic not named in a heading-only quote"


def test_topic_with_a_sentence_or_a_heading_that_names_it_is_kept():
    sentence = "Our research is focused on advancing the mechanistic understanding of cardiac arrhythmias."
    assert verify_claim(LAB_PAGE, "Odening Lab", "expertise", "arrhythmia mechanisms", sentence).ok
    assert verify_claim(LAB_PAGE, "Odening Lab", "expertise", "cardiac electrophysiology",
                        "Translational Cardiology / Electrophysiology").ok
    assert verify_claim(LAB_PAGE, "Odening Lab", "description", "research on cardiac arrhythmias", sentence).ok


def test_short_topic_without_content_words_is_not_judged_by_the_heading_rule():
    page = PageText("AIMI Lab\nAI\nWe build models.")
    assert verify_claim(page, "AIMI Lab", "expertise", "AI", "AI").ok


NAME_BLOCK = "Team\nEnzmann Lab\nName / Titel\nProf. Dr. Volker Enzmann\nFunktion\nGroup Leader"


def test_name_block_is_not_prose():
    """#159: a multi-line name block has 8+ words in total, and "Prof. Dr." looks like sentence punctuation."""
    assert not is_sentence(NAME_BLOCK)
    assert not is_sentence("Prof. Dr. med. Alicia Rovó")
    assert is_sentence("Our research is focused on advancing the mechanistic understanding of cardiac arrhythmias.")
    assert is_sentence("We build sensors for wearables.")


def test_topic_quoted_by_a_name_block_is_rejected():
    """#159: the head's name was the one word of the value in the quote."""
    page = PageText(NAME_BLOCK)
    m = verify_claim(page, "Enzmann Lab", "description",
                     "Research group led by Prof. Dr. Volker Enzmann focusing on cardiac electrophysiology", NAME_BLOCK)
    assert not m.ok and m.reason == "description needs a sentence quote"
    assert not verify_claim(page, "Prof. Dr. Volker Enzmann", "expertise", "cardiac arrhythmia", NAME_BLOCK).ok


def test_names_topic_needs_half_of_the_content_words():
    assert names_topic("cardiac electrophysiology", "Translational Cardiology / Electrophysiology")
    assert names_topic("heart valve mechanics", "Heart Valves")
    assert not names_topic("glucose sensor validation studies", "Sensor Lab")


def test_description_needs_a_sentence_even_when_the_heading_names_it():
    page = PageText("Cardiovascular Engineering\nWe study heart valves and blood flow in the aorta.")
    m = verify_claim(page, "Cardiovascular Engineering", "description", "research in cardiovascular engineering",
                     "Cardiovascular Engineering")
    assert not m.ok and m.reason == "description needs a sentence quote"
    assert verify_claim(page, "Cardiovascular Engineering", "expertise", "cardiovascular engineering",
                        "Cardiovascular Engineering").ok
