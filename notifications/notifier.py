"""
Notification system for NeeDoh Watch.
Supports email (via Resend API) and WhatsApp (via Twilio).
Designed to be extensible for future channels.
"""

import os
import json
from datetime import datetime


class Notifier:
    """Multi-channel notification dispatcher."""

    def __init__(self):
        self.channels = []
        self._setup_channels()

    def _setup_channels(self):
        """Initialize enabled notification channels."""
        # Resend email
        if os.getenv('RESEND_API_KEY'):
            self.channels.append(ResendEmailChannel())
            print("  ✓ Email notifications enabled (Resend)")

        # Legacy SMTP email (fallback)
        elif os.getenv('EMAIL_ENABLED', '').lower() == 'true':
            self.channels.append(EmailChannel())
            print("  ✓ Email notifications enabled (SMTP)")

        # WhatsApp via Twilio
        if os.getenv('WHATSAPP_ENABLED', '').lower() == 'true':
            self.channels.append(WhatsAppChannel())
            print("  ✓ WhatsApp notifications enabled")

        if not self.channels:
            print("  ⚠ No notification channels configured. Alerts will print to console only.")

    def send(self, user_id, message, subject=None):
        """Send a notification through all enabled channels."""
        results = []
        for channel in self.channels:
            try:
                success = channel.send(user_id, message, subject)
                results.append((channel.name, success))
            except Exception as e:
                results.append((channel.name, False))
                print(f"  ✗ {channel.name} notification failed: {e}")

        # Always log to console
        timestamp = datetime.utcnow().strftime('%H:%M:%S')
        print(f"  [{timestamp}] 📢 → {user_id}: {message[:80]}...")

        return results

    def send_digest(self, user_id, alerts, subject="NeeDoh Watch Daily Digest"):
        """Send a daily digest of all alerts."""
        if not alerts:
            return

        lines = [
            "📋 NeeDoh Watch Daily Digest",
            f"Date: {datetime.utcnow().strftime('%Y-%m-%d')}",
            f"Total alerts: {len(alerts)}",
            "─" * 40,
            ""
        ]

        for alert in alerts:
            lines.append(f"• {alert['message']}")
            lines.append("")

        lines.extend([
            "─" * 40,
            "Manage your subscriptions with the /wishlist command.",
            "Report sightings with /seen <product> <store> <mall>"
        ])

        message = '\n'.join(lines)
        self.send(user_id, message, subject=subject)


class ResendEmailChannel:
    """Email notification channel via Resend API."""

    name = "Email (Resend)"

    def __init__(self):
        self.api_key = os.getenv('RESEND_API_KEY', '')
        self.from_email = os.getenv('RESEND_FROM', 'NeeDoh Watch <onboarding@resend.dev>')
        self.default_recipients = [
            r.strip() for r in os.getenv('EMAIL_RECIPIENTS', '').split(',')
            if r.strip()
        ]

    def send(self, user_id, message, subject=None):
        """Send email via Resend API."""
        if not self.api_key:
            print("  ⚠ Resend not configured (missing RESEND_API_KEY)")
            return False

        # Determine recipient
        recipients = self.default_recipients
        if '@' in (user_id or ''):
            recipients = [user_id]

        if not recipients:
            print("  ⚠ No email recipients configured")
            return False

        subject = subject or "🔔 NeeDoh Watch Alert"
        # Build unsubscribe URL using the recipient's email (URL-encoded)
        from urllib.parse import quote
        recipient_email = recipients[0] if recipients else ''
        base_url = os.getenv('APP_URL', 'https://needoh-watch.onrender.com')
        unsubscribe_url = f"{base_url}/unsubscribe?email={quote(recipient_email)}"
        html = self._message_to_html(message, subject, unsubscribe_url)

        try:
            import requests
            resp = requests.post(
                'https://api.resend.com/emails',
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'from': self.from_email,
                    'to': recipients,
                    'subject': subject,
                    'html': html,
                    'text': message + f'\n\nUnsubscribe: {unsubscribe_url}',
                },
                timeout=10,
            )
            if resp.status_code in (200, 201):
                print(f"  ✓ Email sent via Resend to {', '.join(recipients)}")
                return True
            else:
                print(f"  ✗ Resend API error ({resp.status_code}): {resp.text}")
                return False
        except Exception as e:
            print(f"  ✗ Resend email send failed: {e}")
            return False

    def _message_to_html(self, message, subject, unsubscribe_url=''):
        """Convert plain text message to styled HTML email."""
        lines = message.split('\n')
        html_lines = []
        for line in lines:
            if line.startswith('─'):
                html_lines.append('<hr style="border: 1px solid #e0e0e0;">')
            elif line.startswith('•'):
                html_lines.append(f'<li style="margin: 8px 0;">{line[1:].strip()}</li>')
            else:
                html_lines.append(f'<p style="margin: 4px 0;">{line}</p>')

        body = '\n'.join(html_lines)

        unsub_html = ''
        if unsubscribe_url:
            unsub_html = f'<a href="{unsubscribe_url}" style="color: #999; text-decoration: underline;">Unsubscribe from alerts</a>'

        return f"""
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                      max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        padding: 20px; border-radius: 12px 12px 0 0; color: white;">
                <h2 style="margin: 0;">🎯 NeeDoh Watch</h2>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">{subject}</p>
            </div>
            <div style="background: #fff; padding: 20px; border: 1px solid #e0e0e0;
                        border-radius: 0 0 12px 12px;">
                {body}
            </div>
            <p style="text-align: center; color: #999; font-size: 12px; margin-top: 16px;">
                NeeDoh Watch UAE — Tracking NeeDoh availability across UAE stores
                <br>{unsub_html}
            </p>
        </body>
        </html>
        """


class EmailChannel:
    """Legacy email notification channel via SMTP (fallback)."""

    name = "Email"

    def __init__(self):
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        self.smtp_host = os.getenv('EMAIL_SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('EMAIL_SMTP_PORT', '587'))
        self.sender = os.getenv('EMAIL_SENDER', '')
        self.password = os.getenv('EMAIL_PASSWORD', '')
        self.default_recipients = [
            r.strip() for r in os.getenv('EMAIL_RECIPIENTS', '').split(',')
            if r.strip()
        ]

    def send(self, user_id, message, subject=None):
        """Send email notification."""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        if not self.sender or not self.password:
            print("  ⚠ Email not configured (missing sender/password)")
            return False

        # Determine recipient
        recipients = self.default_recipients
        if '@' in (user_id or ''):
            recipients = [user_id]

        if not recipients:
            return False

        subject = subject or "🔔 NeeDoh Watch Alert"

        # Build email
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.sender
        msg['To'] = ', '.join(recipients)

        # Plain text
        msg.attach(MIMEText(message, 'plain'))

        # HTML version
        html = self._message_to_html(message, subject)
        msg.attach(MIMEText(html, 'html'))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"  ✗ Email send failed: {e}")
            return False

    def _message_to_html(self, message, subject):
        """Convert plain text message to styled HTML email."""
        # Replace emojis and format
        lines = message.split('\n')
        html_lines = []
        for line in lines:
            if line.startswith('─'):
                html_lines.append('<hr style="border: 1px solid #e0e0e0;">')
            elif line.startswith('•'):
                html_lines.append(f'<li style="margin: 8px 0;">{line[1:].strip()}</li>')
            else:
                html_lines.append(f'<p style="margin: 4px 0;">{line}</p>')

        body = '\n'.join(html_lines)

        return f"""
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                      max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        padding: 20px; border-radius: 12px 12px 0 0; color: white;">
                <h2 style="margin: 0;">🎯 NeeDoh Watch</h2>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">{subject}</p>
            </div>
            <div style="background: #fff; padding: 20px; border: 1px solid #e0e0e0;
                        border-radius: 0 0 12px 12px;">
                {body}
            </div>
            <p style="text-align: center; color: #999; font-size: 12px; margin-top: 16px;">
                NeeDoh Watch UAE — Tracking NeeDoh availability across UAE stores
            </p>
        </body>
        </html>
        """


class WhatsAppChannel:
    """WhatsApp notification via Twilio."""

    name = "WhatsApp"

    def __init__(self):
        self.account_sid = os.getenv('TWILIO_ACCOUNT_SID', '')
        self.auth_token = os.getenv('TWILIO_AUTH_TOKEN', '')
        self.from_number = os.getenv('TWILIO_WHATSAPP_FROM', 'whatsapp:+14155238886')
        self.default_recipients = [
            r.strip() for r in os.getenv('WHATSAPP_RECIPIENTS', '').split(',')
            if r.strip()
        ]

    def send(self, user_id, message, subject=None):
        """Send WhatsApp message via Twilio."""
        if not self.account_sid or not self.auth_token:
            print("  ⚠ WhatsApp not configured (missing Twilio credentials)")
            return False

        recipients = self.default_recipients
        if user_id and user_id.startswith('whatsapp:'):
            recipients = [user_id]

        if not recipients:
            return False

        try:
            # Using requests directly to avoid twilio SDK dependency
            import requests
            url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"

            for recipient in recipients:
                resp = requests.post(url, data={
                    'From': self.from_number,
                    'To': recipient,
                    'Body': message[:1600],  # WhatsApp limit
                }, auth=(self.account_sid, self.auth_token))

                if resp.status_code not in (200, 201):
                    print(f"  ✗ WhatsApp send failed ({resp.status_code}): {resp.text}")
                    return False

            return True
        except Exception as e:
            print(f"  ✗ WhatsApp send failed: {e}")
            return False


class ConsoleChannel:
    """Fallback channel that just prints to console."""

    name = "Console"

    def send(self, user_id, message, subject=None):
        timestamp = datetime.utcnow().strftime('%H:%M:%S')
        print(f"\n{'='*50}")
        print(f"[{timestamp}] ALERT for {user_id}")
        if subject:
            print(f"Subject: {subject}")
        print(f"{'─'*50}")
        print(message)
        print(f"{'='*50}\n")
        return True
