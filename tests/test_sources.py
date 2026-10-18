import pytest
from pydantic import ValidationError

from navigator.settings import PROJECT_ROOT
from navigator.sources import SourcesFile, load_sources


def test_real_config_loads():
    sources = load_sources(PROJECT_ROOT / "config" / "sources.yaml")
    assert [s.id for s in sources.sources] == ["artorg", "dcb", "unibe"]
    assert sum(s.max_pages for s in sources.sources) == 340  # artorg 110, dcb 30, unibe 200 (#75)
    assert sources.get("dcb").name == "Diabetes Center Berne"


def _minimal(**overrides):
    source = {"id": "x", "name": "X", "seeds": ["https://x.ch/"], "allow_hosts": ["x.ch"], "max_pages": 5}
    source.update(overrides)
    return {"sources": [source]}


def test_source_needs_host_rule():
    with pytest.raises(ValidationError, match="allow_hosts"):
        SourcesFile.model_validate(_minimal(allow_hosts=[]))


def test_invalid_regex_rejected():
    with pytest.raises(ValidationError):
        SourcesFile.model_validate(_minimal(include_patterns=["(unclosed"]))


def test_duplicate_ids_rejected():
    data = _minimal()
    data["sources"].append(dict(data["sources"][0]))
    with pytest.raises(ValidationError, match="unique"):
        SourcesFile.model_validate(data)


def test_unknown_source_raises():
    with pytest.raises(KeyError):
        SourcesFile.model_validate(_minimal()).get("nope")
