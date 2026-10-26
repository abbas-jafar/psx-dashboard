"""Phone push (ntfy.sh) and email (Gmail SMTP). Configure with environment variables / GitHub secrets:
NTFY_TOPIC, EMAIL_USER, EMAIL_APP_PASSWORD, optional EMAIL_TO, and DASH_URL (a repository variable)."""
import os, smtplib, ssl
from email.message import EmailMessage
import requests


def send(title, body, urgent=False):
    """Returns (sent_channels, error_messages). Each channel is tried on its own."""
    sent, errors = [], []
    click = os.getenv("DASH_URL", "")
    topic = (os.getenv("NTFY_TOPIC") or "").strip()
    if topic:
        try:
            h = {"Title": title.encode("utf-8"), "Priority": "high" if urgent else "default", "Tags": "chart_with_upwards_trend"}
            if click:
                h["Click"] = click
            requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), headers=h, timeout=20).raise_for_status()
            sent.append("phone")
        except Exception as e:
            errors.append("phone: " + str(e)[:120])
    else:
        errors.append("phone: NTFY_TOPIC secret is empty or missing")
    user = (os.getenv("EMAIL_USER") or "").strip()
    pw = (os.getenv("EMAIL_APP_PASSWORD") or "").replace(" ", "").strip()
    to = (os.getenv("EMAIL_TO") or user).strip()
    if user and pw:
        try:
            m = EmailMessage()
            m["Subject"], m["From"], m["To"] = title, user, to
            m.set_content(body + (f"\n\nDashboard: {click}" if click else ""))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
                s.login(user, pw)
                s.send_message(m)
            sent.append("email")
        except Exception as e:
            errors.append("email: " + str(e)[:120])
    else:
        errors.append("email: EMAIL_USER or EMAIL_APP_PASSWORD secret is empty or missing")
    return sent, errors
