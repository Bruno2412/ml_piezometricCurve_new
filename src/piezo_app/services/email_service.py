# -*- coding: utf-8 -*-
"""
services/email_service.py — Emails du parcours d'inscription/activation.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st


def send_verification_email(to_email: str, verify_link: str) -> bool:
    smtp_config = st.secrets["smtp"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Confirmez votre inscription — Expert Piézométrie Pro"
    msg["From"] = smtp_config["user"]
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
        with smtplib.SMTP(smtp_config["host"], smtp_config["port"]) as server:
            server.starttls()
            server.login(smtp_config["user"], smtp_config["password"])
            server.sendmail(smtp_config["user"], to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Erreur envoi email: {e}")
        return False


def send_admin_notification_email(
    admin_emails: list[str], new_user_email: str, company_name: str = ""
) -> bool:
    smtp_config = st.secrets["smtp"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Nouvelle inscription à valider — Expert Piézométrie Pro"
    msg["From"] = smtp_config["user"]
    msg["To"] = ", ".join(admin_emails)

    company_line = f" (société : {company_name})" if company_name else ""

    text = (
        f"Bonjour,\n\n"
        f"L'utilisateur {new_user_email}{company_line} vient de confirmer "
        f"son adresse email suite à son inscription.\n\n"
        f"Son compte est en attente de validation. Rendez-vous dans "
        f"l'administration des comptes pour l'activer.\n"
    )
    html = f"""
    <p>Bonjour,</p>
    <p>L'utilisateur <strong>{new_user_email}</strong>{company_line} vient de
    confirmer son adresse email suite à son inscription.</p>
    <p>Son compte est en attente de validation. Rendez-vous dans
    l'administration des comptes pour l'activer.</p>
    """
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_config["host"], smtp_config["port"]) as server:
            server.starttls()
            server.login(smtp_config["user"], smtp_config["password"])
            server.sendmail(smtp_config["user"], admin_emails, msg.as_string())
        return True
    except Exception as e:
        print(f"Erreur envoi email admin: {e}")
        return False


def send_account_activation_email(to_email: str, pages: dict) -> bool:
    """
    Confirme à l'utilisateur que son compte vient d'être activé par un
    administrateur, avec la liste des pages auxquelles il a désormais
    accès.
    """
    smtp_config = st.secrets["smtp"]

    active_pages = [key for key, allowed in (pages or {}).items() if allowed]
    pages_list_html = (
        "".join(f"<li>{p}</li>" for p in active_pages) or "<li>(aucune page activée)</li>"
    )
    pages_list_text = ", ".join(active_pages) or "(aucune page activée)"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Votre compte a été activé — Expert Piézométrie Pro"
    msg["From"] = smtp_config["user"]
    msg["To"] = to_email

    text = (
        f"Bonjour,\n\n"
        f"Votre compte Expert Piézométrie Pro vient d'être activé par un "
        f"administrateur.\n\n"
        f"Pages accessibles : {pages_list_text}\n\n"
        f"Vous pouvez dès à présent vous connecter.\n"
    )
    html = f"""
    <p>Bonjour,</p>
    <p>Votre compte <strong>Expert Piézométrie Pro</strong> vient d'être
    activé par un administrateur.</p>
    <p>Pages accessibles :</p>
    <ul>{pages_list_html}</ul>
    <p>Vous pouvez dès à présent vous connecter.</p>
    """
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_config["host"], smtp_config["port"]) as server:
            server.starttls()
            server.login(smtp_config["user"], smtp_config["password"])
            server.sendmail(smtp_config["user"], to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Erreur envoi email d'activation: {e}")
        return False
