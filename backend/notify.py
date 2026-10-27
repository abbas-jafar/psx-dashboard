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


def diagnose():
    """Which channels are configured. Never returns secret values."""
    topic = (os.getenv("NTFY_TOPIC") or "").strip()
    user = (os.getenv("EMAIL_USER") or "").strip()
    pw = (os.getenv("EMAIL_APP_PASSWORD") or "").replace(" ", "").strip()
    return {"phone": {"configured": bool(topic), "note": f"NTFY_TOPIC set ({len(topic)} characters)" if topic else "NTFY_TOPIC secret is missing or empty"},
            "email": {"configured": bool(user and pw), "note": (f"EMAIL_USER set, app password {len(pw)} characters (Google app passwords have 16)" if user and pw
                      else "EMAIL_USER and/or EMAIL_APP_PASSWORD secret is missing or empty")}}


HINTS = {"535": "Gmail rejected the login: use a 16-character Google App Password (needs 2-step verification), not your normal password.",
         "404": "ntfy answered 404: check the topic name.", "403": "ntfy refused: the topic may be reserved; pick a long random one.",
         "Timeout": "network timeout: try again"}


if __name__ == "__main__":
    import sys
    d = diagnose()
    for k, v in d.items():
        print(f"{k:6} {'configured' if v['configured'] else 'NOT CONFIGURED'}: {v['note']}")
    if "--check" in sys.argv:
        sys.exit(0)
    if not any(v["configured"] for v in d.values()):
        print("FAIL: no notification secret is configured. Add NTFY_TOPIC and/or EMAIL_USER + EMAIL_APP_PASSWORD under Settings > Secrets and variables > Actions > Repository secrets, then run this again.")
        sys.exit(1)
    sent, errs = send("PSX dashboard test", "If you can read this, this channel works. Sent by the Test notifications workflow.", False)
    print("sent via:", sent or "nothing")
    for e in errs:
        print("problem:", e, "|", next((h for k, h in HINTS.items() if k in e), ""))
    bad = [k for k, v in d.items() if v["configured"] and (k == "phone" and "phone" not in sent or k == "email" and "email" not in sent)]
    if bad:
        print("FAIL:", ", ".join(bad), "configured but did not send")
        sys.exit(1)
    print("OK: every configured channel accepted the message. If nothing arrives: phone = open the ntfy app and subscribe to exactly the same topic; email = check Spam.")
