"""
Poller IMAP → POST /api/process-email
Hébergé sur Render comme Web Service (tier gratuit).
Le thread principal expose un serveur HTTP minimal sur PORT
pour satisfaire Render, le polling tourne en thread de fond.
"""
import imaplib
import email
import os
import time
import logging
import threading
from datetime import datetime, timedelta
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
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


processed_ids: set = set()

# Mots-clés pour identifier le dossier "Tous les messages" dans n'importe quelle langue Gmail
_ALL_MAIL_KEYWORDS = ("All Mail", "Tous les messages", "Alle Nachrichten", "Tutti i messaggi", "Todos los mensajes")

def _find_all_mail_folder(imap) -> str:
    _, listing = imap.list()
    for entry in listing:
        decoded = entry.decode() if isinstance(entry, bytes) else entry
        if any(kw in decoded for kw in _ALL_MAIL_KEYWORDS):
            # Format : (\Flags) "/" "Nom du dossier"  ou  (\Flags) "/" Nom
            import re
            m = re.search(r'"([^"]+)"$', decoded)
            if m:
                return m.group(1)
            parts = decoded.rsplit(" ", 1)
            if len(parts) == 2:
                return parts[-1].strip('"')
    log.warning("Dossier All Mail introuvable — fallback sur INBOX")
    return "INBOX"

def poll():
    log.info("--- Cycle polling ---")
    with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
        imap.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        folder = _find_all_mail_folder(imap)
        mailbox = f'"{folder}"' if ' ' in folder else folder
        typ, _ = imap.select(mailbox)
        if typ != 'OK':
            log.error("Impossible de sélectionner le dossier '%s' (typ=%s)", folder, typ)
            return
        log.info("Dossier sélectionné : %s", folder)
        since = (datetime.now() - timedelta(hours=24)).strftime("%d-%b-%Y")
        _, ids = imap.search(None, f'SINCE "{since}"')

        email_ids = ids[0].split()
        sent = 0
        ignored = 0

        for mid in email_ids:
            if mid in processed_ids:
                continue

            _, data = imap.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])
            sender = sender_email(msg.get("From", ""))

            if sender not in ALLOWED_SENDERS:
                ignored += 1
                continue

            subject = decode_str(msg.get("Subject", ""))
            log.info(">>> Lead détecté — from=%s | sujet=%s", sender, subject)

            body = extract_text(msg)
            raw = f"De : {msg.get('From', '')}\nObjet : {subject}\nDate : {msg.get('Date', '')}\n\n{body}"

            try:
                resp = requests.post(
                    PIPELINE_URL,
                    json={"raw_email": raw, "sender": sender},
                    headers={"x-pipeline-secret": PIPELINE_SECRET},
                    timeout=30,
                )
                log.info(">>> Pipeline OK — HTTP=%d | %s", resp.status_code, resp.text[:200])
                processed_ids.add(mid)
                sent += 1
            except Exception as exc:
                log.error(">>> Erreur POST pipeline : %s", exc)

        log.info("Cycle terminé — %d envoyé(s), %d ignoré(s) (non autorisés)", sent, ignored)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass  # silence les logs HTTP


def run():
    log.info("Poller démarré — polling toutes les %ds", POLL_INTERVAL)
    while True:
        try:
            poll()
        except Exception as exc:
            log.error("Erreur polling : %s", exc)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    log.info("Serveur HTTP démarré sur le port %d", port)

    poller_thread = threading.Thread(target=run, daemon=True)
    poller_thread.start()

    server.serve_forever()
