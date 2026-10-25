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



# ---------------------------------------------------------------------------
# Vapi lead email notification (FlowPilot AI sales agent)
# ---------------------------------------------------------------------------
# The Vapi assistant posts its end-of-call report here. Set the assistant's
# Server URL in Vapi to https://maroof25.pythonanywhere.com/vapi-lead and
# every finished call will arrive as a POST with the call transcript and
# summary. We extract the lead details and email them to Abdul.
#
# Email uses Gmail SMTP. Set these in the PythonAnywhere WSGI file
# (os.environ), never in this file:
#   LEAD_GMAIL_USER          Gmail address that sends the mail
#   LEAD_GMAIL_APP_PASSWORD  Gmail App Password (NOT the normal password:
#                            Google Account -> Security -> 2-Step Verification
#                            -> App passwords)
#   LEAD_NOTIFY_TO           Where the lead mail goes
#                            (default: LEAD_GMAIL_USER)
#   LEAD_WEBHOOK_SECRET      Optional: if set, requests must carry
#                            ?secret=<value> or header X-Lead-Secret.
# If email is not configured, leads are still logged to vapi_leads.jsonl
# and the endpoint returns ok (never break Vapi's delivery).

import smtplib
from email.message import EmailMessage

LEAD_GMAIL_USER = os.environ.get("LEAD_GMAIL_USER", "")
LEAD_GMAIL_APP_PASSWORD = os.environ.get("LEAD_GMAIL_APP_PASSWORD", "")
LEAD_NOTIFY_TO = os.environ.get("LEAD_NOTIFY_TO", "") or LEAD_GMAIL_USER
LEAD_WEBHOOK_SECRET = os.environ.get("LEAD_WEBHOOK_SECRET", "")
LEAD_LOG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "vapi_leads.jsonl")


def _extract_lead(data):
    """Pull lead details out of a Vapi server message. Returns {} if the
    message carries no lead (e.g. a conversation-update)."""
    msg = data.get("message", {}) if isinstance(data, dict) else {}
    mtype = msg.get("type", "")
    lead = {}

    if mtype == "end-of-call-report":
        call = msg.get("call", {}) or {}
        customer = call.get("customer", {}) or {}
        lead["kind"] = "end-of-call-report"
        lead["caller"] = customer.get("number", "")
        lead["call_id"] = call.get("id", "")
        lead["started"] = msg.get("startedAt", "")
        lead["ended"] = msg.get("endedAt", "")
        lead["summary"] = msg.get("summary", "") or (
            msg.get("analysis", {}) or {}).get("summary", "")
        analysis = msg.get("analysis", {}) or {}
        structured = analysis.get("structuredData", {}) or {}
        if isinstance(structured, dict):
            lead.update({k: v for k, v in structured.items()
                         if isinstance(v, (str, int, float))})
        transcript = msg.get("transcript", "") or ""
        lead["transcript"] = transcript[-4000:] if transcript else ""
        return lead

    if mtype == "tool-calls":
        params = {}
        for tc in msg.get("toolCallList", []) or []:
            fn = tc.get("function", {}) or {}
            try:
                args = json.loads(fn.get("arguments", "{}") or "{}")
            except Exception:
                args = {}
            if isinstance(args, dict):
                params.update(args)
        if params:
            lead["kind"] = "tool-call"
            lead["caller"] = params.get("phone") or params.get("caller") or ""
            lead.update({k: v for k, v in params.items()
                         if isinstance(v, (str, int, float))})
            return lead

    return {}


def _log_lead(lead):
    try:
        with open(LEAD_LOG_FILE, "a") as f:
            f.write(json.dumps(lead) + "\n")
    except Exception:
        log.exception("Could not write lead log")


def _send_lead_email(lead):
    """Send the lead by Gmail SMTP. Returns (sent, error)."""
    if not (LEAD_GMAIL_USER and LEAD_GMAIL_APP_PASSWORD and LEAD_NOTIFY_TO):
        return False, "email not configured"
    lines = ["New FlowPilot AI lead", ""]
    lines.append("Time: " + (lead.get("ended") or lead.get("started") or ""))
    if lead.get("caller"):
        lines.append("Caller number: " + str(lead["caller"]))
    for key in ("name", "business", "business_name", "phone", "notes"):
        if lead.get(key):
            lines.append(key.replace("_", " ").title() + ": " + str(lead[key]))
    if lead.get("summary"):
        lines.append("")
        lines.append("Summary:")
        lines.append(str(lead["summary"]))
    if lead.get("transcript"):
        lines.append("")
        lines.append("Transcript (tail):")
        lines.append(str(lead["transcript"]))
    lines.append("")
    lines.append("Next step: contact this lead on WhatsApp (0329 0302088) "
                 "to set up their FREE plan.")
    body = "\n".join(lines)

    msg = EmailMessage()
    msg["Subject"] = "New FlowPilot AI lead: " + str(
        lead.get("business") or lead.get("business_name")
        or lead.get("name") or lead.get("caller") or "unknown")
    msg["From"] = LEAD_GMAIL_USER
    msg["To"] = LEAD_NOTIFY_TO
    msg.set_content(body)
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls()
            s.login(LEAD_GMAIL_USER, LEAD_GMAIL_APP_PASSWORD)
            s.send_message(msg)
        return True, ""
    except Exception as e:
        log.exception("Lead email failed")
        return False, str(e)[:200]


@app.route("/vapi-lead", methods=["POST"])
def vapi_lead():
    """Receive a Vapi call report and email the lead to Abdul."""
    if LEAD_WEBHOOK_SECRET:
        provided = (request.args.get("secret", "")
                    or request.headers.get("X-Lead-Secret", ""))
        if provided != LEAD_WEBHOOK_SECRET:
            return jsonify({"status": "unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    lead = _extract_lead(data)
    if not lead:
        return jsonify({"status": "ignored"}), 200
    _log_lead(lead)
    sent, err = _send_lead_email(lead)
    log.info("Vapi lead: caller=%s email_sent=%s err=%s",
             lead.get("caller"), sent, err)
    return jsonify({"status": "ok", "email_sent": sent}), 200


@app.route("/vapi-lead/health", methods=["GET"])
def vapi_lead_health():
    return jsonify({
        "status": "ok",
        "email_configured": bool(
            LEAD_GMAIL_USER and LEAD_GMAIL_APP_PASSWORD and LEAD_NOTIFY_TO),
        "notify_to_set": bool(LEAD_NOTIFY_TO),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info("Starting WhatsApp webhook on port %s", port)
    app.run(host="0.0.0.0", port=port)
