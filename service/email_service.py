# -*- coding: utf-8 -*-
"""
Created on Wed Sep 16 11:27:42 2026

@author: bruno
"""

import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")

def send_verification_email(to_email: str, verify_link: str) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Confirmez votre inscription — Expert Piézométrie Pro"
    msg["From"] = SMTP_USER
    msg["To"] = to_email

    text = f"Bonjour,\n\nConfirmez votre inscription en cliquant sur ce lien :\n{verify_link}\n"
    html = f"""
    <p>Bonjour,</p>
    <p>Confirmez votre inscription en cliquant sur le bouton ci-dessous :</p>
    <p><a href="{verify_link}" style="background:#0d6efd;color:#fff;padding:10px 20px;
       text-decoration:none;border-radius:6px;">Valider mon compte</a></p>
    <p>Ou copiez ce lien : {verify_link}</p>
    """
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Erreur envoi email: {e}")
        return False