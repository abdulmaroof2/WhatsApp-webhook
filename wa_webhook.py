"""
WhatsApp Business API - Webhook Server
======================================
Receives incoming WhatsApp messages from Meta and sends auto-replies.

Setup:
    1. Copy .env.example to .env and fill in your Meta credentials
       (VERIFY_TOKEN, WHATSAPP_TOKEN, PHONE_NUMBER_ID)
    2. pip install -r requirements.txt
    3. python server.py   (runs on port 5000)
    4. Expose with ngrok/cloudflared and paste the public URL into
       Meta App Dashboard > WhatsApp > Configuration > Webhook

Flow once Meta credentials exist:
    Meta App "WhatsApp AI Agent" -> WhatsApp product -> verify +923434071007
    -> PHONE_NUMBER_ID + WHATSAPP_TOKEN -> put in .env -> server live
"""

import os
import json
import logging
from datetime import datetime

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("wa-webhook")

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "change-me-verify-token")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v21.0")

# Simple keyword auto-replies (Roman Urdu + English). The AI brain
# (Muse agent) can replace reply_for() later with an LLM call.
AUTO_REPLIES = [
    (("salam", "assalam", "hello", "hi", "aoa"),
     "Walaikum Assalam! 👋 Main Abdul Maroof ka AI assistant hun. Kaise madad kar sakta hun?"),
    (("price", "rate", "qeemat", "cost", "charges"),
     "Hamari services:\n• WhatsApp AI Sales Agent — $49-$199\n• VoiceLead AI — $99-$599\n• Guest posting service\nDetail ke liye likhein 'detail'"),
    (("detail", "info", "information", "batao"),
     "Zyada maloomat ke liye https://aitoolagent.online visit karein ya apna sawal likhein, main foran jawab dunga!"),
    (("shukriya", "thanks", "thank"),
     "Khush aamdeed! 😊 Aur kuch chahiye to batayein."),
    (("bye", "allah hafiz", "khuda hafiz"),
     "Allah Hafiz! 👋 Phir rabta kijiyega."),
]

FALLBACK_REPLY = (
    "Shukriya aapke message ka! 🙏 Main Abdul Maroof ka AI assistant hun. "
    "Aapka paigham note kar liya hai — thori der mein tafseeli jawab dunga. "
    "Fori madad ke liye 'price' ya 'detail' likhein."
)


def reply_for(text: str) -> str:
    """Pick an auto-reply based on keywords in the incoming message."""
    t = (text or "").lower()
    for keywords, reply in AUTO_REPLIES:
        if any(k in t for k in keywords):
            return reply
    return FALLBACK_REPLY


def send_whatsapp_message(to: str, text: str) -> dict:
    """Send a text message through the WhatsApp Business Cloud API."""
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        log.warning("WHATSAPP_TOKEN / PHONE_NUMBER_ID not set - not sending")
        return {"sent": False, "reason": "missing credentials"}
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    log.info("Send to %s -> HTTP %s", to, r.status_code)
    return {"sent": r.ok, "status": r.status_code, "response": r.text[:500]}


@app.route("/webhook", methods=["GET"])
def verify():
    """Meta webhook verification handshake."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        log.info("Webhook verified OK")
        return challenge, 200
    log.warning("Webhook verification failed")
    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def incoming():
    """Handle incoming WhatsApp messages / status updates."""
    data = request.get_json(force=True, silent=True) or {}
    log.info("Incoming: %s", json.dumps(data)[:2000])

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        continue
                    sender = msg.get("from", "")
                    text = msg.get("text", {}).get("body", "")
                    log.info("Message from %s: %s", sender, text)
                    reply = reply_for(text)
                    send_whatsapp_message(sender, reply)
    except Exception as e:  # never break Meta's delivery retries loop badly
        log.exception("Error handling webhook: %s", e)

    return jsonify({"status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "time": datetime.utcnow().isoformat() + "Z",
        "credentials_configured": bool(WHATSAPP_TOKEN and PHONE_NUMBER_ID),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info("Starting WhatsApp webhook on port %s", port)
    app.run(host="0.0.0.0", port=port)
