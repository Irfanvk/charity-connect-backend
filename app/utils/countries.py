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

# Common cities per country, offered as suggestions (any other city can still be typed).
# Keep in sync with CITY_SUGGESTIONS in CharityConnect src/lib/countries.js.
CITY_SUGGESTIONS: dict[str, list[str]] = {
    "SA": ["Riyadh", "Jeddah", "Dammam", "Al Khobar", "Dhahran", "Makkah", "Madinah", "Jubail", "Taif",
           "Abha", "Khamis Mushait", "Tabuk", "Buraidah", "Hail", "Al Ahsa", "Hafar Al Batin", "Yanbu",
           "Jizan", "Najran", "Qatif", "Al Kharj", "Unaizah"],
    "AE": ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Al Ain", "Ras Al Khaimah", "Fujairah", "Umm Al Quwain",
           "Khor Fakkan", "Ruwais"],
    "KW": ["Kuwait City", "Farwaniya", "Hawalli", "Salmiya", "Jahra", "Mangaf", "Fahaheel", "Abbasiya",
           "Mahboula", "Ahmadi"],
    "OM": ["Muscat", "Salalah", "Sohar", "Nizwa", "Sur", "Ibri", "Barka", "Ruwi", "Seeb", "Duqm"],
    "QA": ["Doha", "Al Wakrah", "Al Khor", "Al Rayyan", "Mesaieed", "Umm Salal", "Lusail"],
    "BH": ["Manama", "Riffa", "Muharraq", "Isa Town", "Hamad Town", "Sitra", "Juffair", "Budaiya"],
    "IN": ["Mangaluru", "Kasaragod", "Udupi", "Puttur", "Bantwal", "Belthangady", "Uppala", "Manjeshwar",
           "Bengaluru", "Mysuru", "Kozhikode", "Kannur", "Kochi", "Thiruvananthapuram", "Mumbai", "Chennai",
           "Hyderabad", "Delhi"],
}

# Words that name a country, not a city (any case, dots and extra spaces ignored).
_COUNTRY_WORDS = {name.lower() for name, _ in COUNTRIES.values()} | {
    "ksa", "k.s.a", "saudi", "saudia", "saudiarabia", "kingdom of saudi arabia", "uae", "u.a.e", "emirates",
    "the emirates", "united arab emirate", "oman", "sultanate of oman", "qatar", "bahrain", "kingdom of bahrain",
    "india", "bharat", "usa", "u.s.a", "us", "america", "united states of america", "uk", "u.k", "england",
    "great britain", "britain", "canada", "australia", "gcc", "gulf", "middle east",
}
# A country name that people also use for the capital: saved as the city's name.
_CITY_FIXES = {"kuwait": "Kuwait City"}


def _key(value: str) -> str:
    return " ".join(str(value or "").replace(".", " ").replace(",", " ").lower().split())


def is_country_word(value: str | None) -> bool:
    k = _key(value or "")
    return bool(k) and (k in _COUNTRY_WORDS or k.replace(" ", "") in {w.replace(" ", "") for w in _COUNTRY_WORDS})


CITY_NOT_COUNTRY = "Please enter your city, not the country (for example Riyadh, Dubai or Doha)."
NOT_SET = "none"  # filter value for members who have not entered a country yet


def normalize_country(value: str | None) -> str | None:
    """Return the ISO code, or raise ValueError for a country not on the list. Empty -> None."""
    code = str(value or "").strip().upper()
    if not code:
        return None
    if code not in COUNTRIES:
        raise ValueError("Please choose your country from the list.")
    return code


_KNOWN_CITIES = {_key(c): c for cities in CITY_SUGGESTIONS.values() for c in cities}


def normalize_city(value: str | None) -> str | None:
    """Tidy a city: known cities get their usual spelling ("riyadh" -> "Riyadh"); a country name
    (e.g. "Saudi Arabia", "KSA") is refused. Empty -> None."""
    city = " ".join(str(value or "").split())
    if not city:
        return None
    if len(city) > CITY_MAX_LENGTH:
        raise ValueError(f"City must be at most {CITY_MAX_LENGTH} characters.")
    k = _key(city)
    if k in _CITY_FIXES:
        return _CITY_FIXES[k]
    if is_country_word(city):
        raise ValueError(CITY_NOT_COUNTRY)
    if len(k.replace(" ", "")) < 2 or not re.search(r"[^\W\d_]", city):
        raise ValueError("Please enter the name of your city.")
    return _KNOWN_CITIES.get(k, city)


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
