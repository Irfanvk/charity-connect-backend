ISLAMIC_GREETING = "Assalamu Alaikum"


def with_islamic_greeting(message: str) -> str:
    normalized_message = str(message or "").strip()
    if not normalized_message:
        return ISLAMIC_GREETING

    if normalized_message.lower().startswith(ISLAMIC_GREETING.lower()):
        return normalized_message

    return f"{ISLAMIC_GREETING}\n\n{normalized_message}"