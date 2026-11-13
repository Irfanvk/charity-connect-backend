"""Countries a member can live in: the same list as the app's phone country codes.

Keep in sync with PHONE_COUNTRIES in CharityConnect src/lib/phone-utils.js.
"""
import re

# ISO code -> (name, dial code digits)
COUNTRIES: dict[str, tuple[str, str]] = {
    "SA": ("Saudi Arabia", "966"),
    "AE": ("United Arab Emirates", "971"),
    "KW": ("Kuwait", "965"),
    "OM": ("Oman", "968"),
    "QA": ("Qatar", "974"),
    "BH": ("Bahrain", "973"),
    "IN": ("India", "91"),
    "CA": ("Canada", "1"),
    "US": ("United States", "1"),
    "GB": ("United Kingdom", "44"),
    "AU": ("Australia", "61"),
    "IQ": ("Iraq", "964"),
    "AZ": ("Azerbaijan", "994"),
    "MA": ("Morocco", "212"),
    "ZA": ("South Africa", "27"),
}

CITY_MAX_LENGTH = 100
NOT_SET = "none"  # filter value for members who have not entered a country yet


def normalize_country(value: str | None) -> str | None:
    """Return the ISO code, or raise ValueError for a country not on the list. Empty -> None."""
    code = str(value or "").strip().upper()
    if not code:
        return None
    if code not in COUNTRIES:
        raise ValueError("Please choose your country from the list.")
    return code


def normalize_city(value: str | None) -> str | None:
    city = " ".join(str(value or "").split())
    if not city:
        return None
    if len(city) > CITY_MAX_LENGTH:
        raise ValueError(f"City must be at most {CITY_MAX_LENGTH} characters.")
    return city


def dial_code_digits(value: str | None) -> str | None:
    """'+971', '971' or 'AE' -> '971'. Unknown -> None."""
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.upper() in COUNTRIES:
        return COUNTRIES[raw.upper()][1]
    digits = re.sub(r"\D", "", raw)
    return digits if digits in {d for _, d in COUNTRIES.values()} else None


def country_from_phone(phone: str | None) -> str | None:
    """Best guess of the country from a +<code> phone number (longest code wins; +1 -> None, it is shared)."""
    raw = str(phone or "").strip()
    if not raw.startswith("+"):
        return None
    digits = re.sub(r"\D", "", raw)
    matches = sorted(
        ((iso, d) for iso, (_, d) in COUNTRIES.items() if digits.startswith(d)),
        key=lambda pair: len(pair[1]),
        reverse=True,
    )
    if not matches:
        return None
    best = matches[0][1]
    isos = [iso for iso, d in matches if d == best]
    return isos[0] if len(isos) == 1 else None
