"""
Poller IMAP → POST /api/process-email
Hébergé sur Render comme Background Worker.
"""
import imaplib
import email
import os
import time
import logging
import requests
from email.header import decode_header

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
PIPELINE_URL = os.environ["PIPELINE_URL"]          # https://ton-app.vercel.app/api/process-email
PIPELINE_SECRET = os.environ["PROCESS_EMAIL_SECRET"]
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
ALLOWED_SENDERS = {
    s.strip().lower()
    for s in os.getenv("ALLOWED_SENDERS", "noreply@immoweb.be,notifications@immovlan.be,no-reply@immovlan.be").split(",")
}


def decode_str(value: str) -> str:
    parts = decode_header(value)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def extract_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace") if payload else ""
    return ""


def sender_email(from_header: str) -> str:
    if "<" in from_header:
        return from_header.split("<")[-1].rstrip(">").strip().lower()
    return from_header.strip().lower()


def poll():
    with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
        imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        imap.select("INBOX")
        _, ids = imap.search(None, "UNSEEN")

        for mid in ids[0].split():
            _, data = imap.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])
            sender = sender_email(msg.get("From", ""))

            if sender not in ALLOWED_SENDERS:
                imap.store(mid, "+FLAGS", "\\Seen")
                continue

            subject = decode_str(msg.get("Subject", ""))
            body = extract_text(msg)
            raw = f"De : {msg.get('From', '')}\nObjet : {subject}\nDate : {msg.get('Date', '')}\n\n{body}"

            try:
                resp = requests.post(
                    PIPELINE_URL,
                    json={"raw_email": raw, "sender": sender},
                    headers={"x-pipeline-secret": PIPELINE_SECRET},
                    timeout=30,
                )
                log.info("Email traité — %s | status=%d", subject, resp.status_code)
            except Exception as exc:
                log.error("Erreur POST pipeline : %s", exc)

            imap.store(mid, "+FLAGS", "\\Seen")


def run():
    log.info("Poller démarré — polling toutes les %ds", POLL_INTERVAL)
    while True:
        try:
            poll()
        except Exception as exc:
            log.error("Erreur polling : %s", exc)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
