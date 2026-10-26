"""Phone push (ntfy.sh) and email (SMTP). Configure with environment variables / GitHub secrets:
NTFY_TOPIC, EMAIL_USER, EMAIL_APP_PASSWORD, EMAIL_TO, DASH_URL. Untested against live services."""
import os, smtplib, ssl
from email.message import EmailMessage
import requests


def send(title, body, urgent=False):
    sent = []
    topic = os.getenv("NTFY_TOPIC")
    click = os.getenv("DASH_URL", "")
    if topic:
        h = {"Title": title.encode("utf-8"), "Priority": "high" if urgent else "default"}
        if click:
            h["Click"] = click
        requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), headers=h, timeout=20).raise_for_status()
        sent.append("push")
    user, pw, to = os.getenv("EMAIL_USER"), os.getenv("EMAIL_APP_PASSWORD"), os.getenv("EMAIL_TO") or os.getenv("EMAIL_USER")
    if user and pw:
        m = EmailMessage()
        m["Subject"], m["From"], m["To"] = title, user, to
        m.set_content(body + (f"\n\nDashboard: {click}" if click else ""))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
            s.login(user, pw)
            s.send_message(m)
        sent.append("email")
    return sent
