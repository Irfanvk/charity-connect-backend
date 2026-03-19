import logging
import json
from urllib import request, error

from app.config import settings

logger = logging.getLogger(__name__)


def _normalize_phone(phone: str) -> str:
    raw = str(phone or '').strip()
    if not raw:
        return ''
    keep_plus = raw.startswith('+')
    digits = ''.join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ''
    return f'+{digits}' if keep_plus else digits


def _build_meta_url() -> str:
    explicit_url = str(settings.WHATSAPP_API_URL or '').strip()
    if explicit_url:
        return explicit_url

    phone_number_id = str(settings.WHATSAPP_PHONE_NUMBER_ID or '').strip()
    api_version = str(settings.WHATSAPP_API_VERSION or 'v22.0').strip()
    if not phone_number_id:
        return ''
    return f'https://graph.facebook.com/{api_version}/{phone_number_id}/messages'


def send_whatsapp_message(phone: str, message: str) -> dict:
    """Send a WhatsApp text message via configured provider.

    Returns a normalized status payload without raising provider exceptions to callers.
    """
    normalized_phone = _normalize_phone(phone)
    normalized_message = str(message or '').strip()

    if not normalized_phone:
        return {"status": "skipped", "reason": "missing_phone"}

    if not normalized_message:
        return {"status": "skipped", "reason": "missing_message"}

    if not settings.WHATSAPP_ENABLED:
        logger.info("WhatsApp disabled in config", extra={"phone": normalized_phone})
        return {"status": "disabled", "phone": normalized_phone}

    provider = str(settings.WHATSAPP_PROVIDER or 'meta').lower().strip()
    if provider != 'meta':
        return {"status": "skipped", "reason": "unsupported_provider", "provider": provider}

    meta_url = _build_meta_url()
    token = str(settings.WHATSAPP_API_TOKEN or '').strip()
    if not meta_url or not token:
        return {
            "status": "skipped",
            "reason": "provider_not_configured",
            "details": "Missing WHATSAPP_API_TOKEN or WHATSAPP_PHONE_NUMBER_ID/WHATSAPP_API_URL",
        }

    payload = {
        "messaging_product": "whatsapp",
        "to": normalized_phone,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": normalized_message,
        },
    }

    req = request.Request(
        meta_url,
        data=json.dumps(payload).encode('utf-8'),
        method='POST',
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
    )

    try:
        with request.urlopen(req, timeout=15) as response:
            raw = response.read().decode('utf-8') if response else ''
            data = json.loads(raw) if raw else {}
            return {
                "status": "sent",
                "phone": normalized_phone,
                "provider": "meta",
                "provider_response": data,
            }
    except error.HTTPError as exc:
        body = ''
        try:
            body = exc.read().decode('utf-8')
        except Exception:
            body = ''
        logger.warning("WhatsApp provider HTTP error", extra={"status": exc.code, "body": body[:500]})
        return {
            "status": "failed",
            "phone": normalized_phone,
            "provider": "meta",
            "http_status": exc.code,
            "error": body or str(exc),
        }
    except error.URLError as exc:
        logger.warning("WhatsApp provider connection error", extra={"error": str(exc)})
        return {
            "status": "failed",
            "phone": normalized_phone,
            "provider": "meta",
            "error": str(exc),
        }
