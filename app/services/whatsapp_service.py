import logging

logger = logging.getLogger(__name__)


def send_whatsapp_message(phone: str, message: str) -> dict:
    """Placeholder for WhatsApp provider integration.

    This keeps queueing and retry semantics in place while avoiding provider lock-in.
    """
    if not phone:
        return {"status": "skipped", "reason": "missing_phone"}

    logger.info("Queued WhatsApp message", extra={"phone": phone, "preview": message[:80]})
    return {"status": "queued", "phone": phone}
