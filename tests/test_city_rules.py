"""A city must be a city: country names are refused, known cities get their usual spelling."""
import pytest

from app.utils.countries import CITY_NOT_COUNTRY, is_country_word, normalize_city


@pytest.mark.parametrize("value", ["Saudi Arabia", "saudi arabia", "KSA", "K.S.A.", "Saudi", "UAE", "U.A.E",
                                   "United Arab Emirates", "Qatar", "oman", "India", "  Bahrain  "])
def test_country_names_are_refused(value):
    with pytest.raises(ValueError, match="not the country"):
        normalize_city(value)


def test_known_cities_get_usual_spelling():
    assert normalize_city("riyadh") == "Riyadh"
    assert normalize_city("  ABU   dhabi ") == "Abu Dhabi"
    assert normalize_city("Kuwait") == "Kuwait City"  # people write the country for the capital
    assert normalize_city("Some Small Town") == "Some Small Town"  # any other city is fine
    assert normalize_city("") is None and normalize_city(None) is None


def test_not_a_name():
    for bad in ("1", "12345", "-", "x"):
        with pytest.raises(ValueError):
            normalize_city(bad)


def test_helpers():
    assert is_country_word("Saudi Arabia") and not is_country_word("Dubai")
    assert "Riyadh" in CITY_NOT_COUNTRY
