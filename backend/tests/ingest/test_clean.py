from pathlib import Path

import pytest

from navigator.ingest.clean import clean_html, decode_email_href

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.mark.parametrize(
    "href, expected",
    [
        ("mailto:Jane.Doe@unibe.ch", "jane.doe@unibe.ch"),
        ("mailto:jane%40unibe.ch?subject=Hi", "jane@unibe.ch"),
        ("javascript:void(location.href='mailto:'+String.fromCharCode(106,64,117,46,99,104))", "j@u.ch"),
        ("mailto:?body=https://www.artorg.unibe.ch", None),  # share link, not an email
        ("https://www.unibe.ch", None),
    ],
)
def test_decode_email_href(href, expected):
    assert decode_email_href(href) == expected


def test_dcb_team_names_and_emails_survive():
    page = clean_html(_fixture("dcb_team.html"), "https://www.dcberne.com/en/team/")
    # Names next to their role and their email (the "Mail" link text is replaced inline).
    assert "CEO\nDerek Brandt\nderek.brandt@dcberne.com" in page.text
    assert "Dr. Martina Rothenbühler" in page.text
    assert "\nMail\n" not in page.text
    assert "greta.ehlers@dcberne.com" in page.emails
    assert "https://www.dcberne.com/en/projects/" in page.links


def test_artorg_obfuscated_emails_are_decoded():
    page = clean_html(
        _fixture("artorg_members.html"),
        "https://www.artorg.unibe.ch/research/msl/group_members/index_eng.html",
    )
    assert "brice-olivier.demory@unibe.ch" in page.emails
    assert "Prof. Dr. Brice-Olivier Demory" in page.text
    assert "Gaëlle Nivlet" in page.text  # trafilatura dropped this one
    assert "javascript" not in page.text


def test_navigation_is_removed_but_links_are_kept():
    page = clean_html(
        _fixture("artorg_person.html"),
        "https://www.artorg.unibe.ch/research/msl/group_members/persons/prof_dr_demory_brice_olivier/index_eng.html",
    )
    assert page.text.startswith("Prof. Dr. Brice-Olivier Demory")
    assert "Medical Sensing Laboratory" in page.text
    assert any(link.endswith("/research/msl/index_eng.html") for link in page.links)
    assert all("#" not in link for link in page.links)


def test_emails_outside_main_content_are_appended():
    html = """<html><head><title> Lab </title></head><body>
      <main><p>Glucose sensing group</p></main>
      <footer><a href="mailto:lab@unibe.ch">Contact</a></footer></body></html>"""
    page = clean_html(html, "https://x.unibe.ch/")
    assert page.title == "Lab"
    assert page.text == "Glucose sensing group\n\nContact emails on this page:\n- lab@unibe.ch"


def test_relative_links_are_resolved():
    html = '<body><main><a href="./research/index_eng.html#top">R</a><a href="//www.unibe.ch/x">U</a></main></body>'
    page = clean_html(html, "https://www.artorg.unibe.ch/index_eng.html")
    assert page.links == [
        "https://www.artorg.unibe.ch/research/index_eng.html",
        "https://www.unibe.ch/x",
    ]
