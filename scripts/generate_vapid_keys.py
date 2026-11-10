"""Generate a VAPID key pair for Web Push.

Usage:  python scripts/generate_vapid_keys.py

Prints values for VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY (base64-encoded PEM).
Nothing is written to disk, so the keys cannot be committed by accident.
Set the SAME values on the web, worker and beat services.
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main() -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    point = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(point).rstrip(b"=").decode()
    private_b64 = base64.b64encode(pem).decode()

    print("# Keep VAPID_PRIVATE_KEY secret. Never commit it.")
    print(f"VAPID_PUBLIC_KEY={public_b64}")
    print(f"VAPID_PRIVATE_KEY={private_b64}")
    print("VAPID_SUBJECT=mailto:admin@your-domain.example")


if __name__ == "__main__":
    main()