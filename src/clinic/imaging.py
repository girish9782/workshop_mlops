"""Small helpers for validating an uploaded photo. Photos are processed in memory only."""
import base64

MAX_IMAGE_BYTES = 3 * 1024 * 1024  # Groq allows ~4 MB base64 per request; the browser also shrinks photos


def sniff_image(data: bytes):
    """Return the real MIME type from the file's magic bytes (never trust the filename or header)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def to_data_url(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"
