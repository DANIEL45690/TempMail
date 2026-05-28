import os
import json
import hashlib
import secrets
import requests
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string, session
from flask_cors import CORS
import sqlite3
from functools import wraps
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import time

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
CORS(app)

def init_db():
    conn = sqlite3.connect("tempmail.db")
    c = conn.cursor()

    c.execute("DROP TABLE IF EXISTS users")
    c.execute("DROP TABLE IF EXISTS temp_emails")
    c.execute("DROP TABLE IF EXISTS messages")
    c.execute("DROP TABLE IF EXISTS sent_messages")

    c.execute("""CREATE TABLE users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL,
                  created_at TIMESTAMP)""")

    c.execute("""CREATE TABLE temp_emails
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  email_address TEXT NOT NULL,
                  email_prefix TEXT NOT NULL,
                  domain TEXT,
                  service TEXT,
                  created_at TIMESTAMP,
                  last_checked TIMESTAMP,
                  is_favorite INTEGER DEFAULT 0,
                  FOREIGN KEY (user_id) REFERENCES users (id))""")

    c.execute("""CREATE TABLE messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  email_id INTEGER NOT NULL,
                  message_id TEXT,
                  from_name TEXT,
                  from_addr TEXT,
                  subject TEXT,
                  body TEXT,
                  body_html TEXT,
                  received_at TIMESTAMP,
                  is_read BOOLEAN DEFAULT 0,
                  FOREIGN KEY (user_id) REFERENCES users (id))""")

    c.execute("""CREATE TABLE sent_messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  from_email TEXT,
                  to_email TEXT,
                  subject TEXT,
                  body TEXT,
                  sent_at TIMESTAMP,
                  status TEXT,
                  FOREIGN KEY (user_id) REFERENCES users (id))""")

    conn.commit()

    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        admin_hash = hashlib.sha256("admin123".encode()).hexdigest()
        c.execute("INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
                  ("admin", admin_hash, datetime.now()))

    conn.commit()
    conn.close()

init_db()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

class EmailService:
    def __init__(self):
        self.domains = ["1secmail.com", "1secmail.org", "1secmail.net", "1secmail.xyz"]

        self.smtp_config = {
            "server": "smtp.yandex.ru",
            "port": 587,
            "email": "no-reply@tempmail.xyz",
            "password": "",
            "use_auth": False
        }

    def generate_email(self):
        prefix = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        domain = random.choice(self.domains)
        return prefix, f"{prefix}@{domain}"

    def create_temp_email(self, user_id):
        prefix, email = self.generate_email()
        conn = sqlite3.connect("tempmail.db")
        c = conn.cursor()
        c.execute(
            """INSERT INTO temp_emails (user_id, email_address, email_prefix, domain, service, created_at, last_checked, is_favorite)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, email, prefix, email.split("@")[1], "1secmail", datetime.now(), datetime.now(), 0),
        )
        email_id = c.lastrowid
        conn.commit()
        conn.close()
        return {"id": email_id, "email": email, "prefix": prefix}

    def check_inbox(self, email):
        try:
            login = email.split("@")[0]
            domain = email.split("@")[1]
            url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return data
            return []
        except:
            return []

    def read_message(self, email, msg_id):
        try:
            login = email.split("@")[0]
            domain = email.split("@")[1]
            url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={msg_id}"
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                return {
                    "from": data.get("from", "Unknown"),
                    "subject": data.get("subject", "No Subject"),
                    "body": data.get("textBody", data.get("htmlBody", "No content")),
                }
            return None
        except:
            return None

    def send_email(self, from_email, to_email, subject, body):
        try:
            msg = MIMEMultipart()
            msg['From'] = from_email
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            server = smtplib.SMTP("smtp.mail.ru", 587)
            server.starttls()
            server.ehlo()

            try:
                server.login("tempmailer@mail.ru", "Tempmail2024")
            except:
                pass

            server.sendmail(from_email, to_email, msg.as_string())
            server.quit()
            return True, "Email sent successfully"
        except Exception as e:
            return False, str(e)

    def send_via_mailgun(self, to_email, subject, body):
        try:
            domain = "sandbox.mailgun.org"
            api_key = "YOUR_MAILGUN_API_KEY"
            url = f"https://api.mailgun.net/v3/{domain}/messages"
            auth = ("api", api_key)
            data = {
                "from": "TempMail <mailgun@sandbox.mailgun.org>",
                "to": [to_email],
                "subject": subject,
                "text": body
            }
            response = requests.post(url, auth=auth, data=data, timeout=30)
            return response.status_code == 200, "Sent via Mailgun" if response.status_code == 200 else "Mailgun failed"
        except:
            return False, "Mailgun not configured"

    def send_via_smtp2go(self, to_email, subject, body):
        try:
            url = "https://api.smtp2go.com/v3/email/send"
            headers = {"Content-Type": "application/json", "X-Smtp2go-Api-Key": "api_YOUR_KEY"}
            data = {
                "sender": "noreply@tempmail.com",
                "to": [to_email],
                "subject": subject,
                "text_body": body
            }
            response = requests.post(url, headers=headers, json=data, timeout=30)
            return response.status_code == 200, "Sent via SMTP2GO"
        except:
            return False, "SMTP2GO not configured"

    def get_messages(self, user_id, email_id):
        conn = sqlite3.connect("tempmail.db")
        c = conn.cursor()

        c.execute("SELECT email_address FROM temp_emails WHERE id = ? AND user_id = ?", (email_id, user_id))
        email_data = c.fetchone()

        if not email_data:
            conn.close()
            return []

        email_address = email_data[0]
        messages_from_api = self.check_inbox(email_address)

        for msg in messages_from_api:
            msg_id = str(msg.get("id"))

            c.execute("SELECT id FROM messages WHERE message_id = ? AND user_id = ? AND email_id = ?", (msg_id, user_id, email_id))

            if not c.fetchone():
                message_detail = self.read_message(email_address, msg_id)
                if message_detail:
                    c.execute("""INSERT INTO messages
                                 (user_id, email_id, message_id, from_name, from_addr, subject, body, received_at)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                              (user_id, email_id, msg_id, message_detail["from"], message_detail["from"],
                               message_detail["subject"], message_detail["body"], datetime.now()))

        conn.commit()

        c.execute("UPDATE temp_emails SET last_checked = ? WHERE id = ?", (datetime.now(), email_id))
        conn.commit()

        c.execute("""SELECT id, message_id, from_name, from_addr, subject, body, received_at, is_read
                     FROM messages WHERE user_id = ? AND email_id = ? ORDER BY received_at DESC""",
                  (user_id, email_id))
        messages = c.fetchall()
        conn.close()

        return [{"id": m[0], "message_id": m[1], "from_name": m[2], "from_addr": m[3],
                 "subject": m[4], "body": m[5], "received_at": m[6], "is_read": m[7]} for m in messages]

    def mark_as_read(self, user_id, message_id):
        conn = sqlite3.connect("tempmail.db")
        c = conn.cursor()
        c.execute("UPDATE messages SET is_read = 1 WHERE id = ? AND user_id = ?", (message_id, user_id))
        conn.commit()
        conn.close()

    def get_user_emails(self, user_id):
        conn = sqlite3.connect("tempmail.db")
        c = conn.cursor()
        c.execute("""SELECT id, email_address, email_prefix, domain, service, created_at, last_checked, is_favorite
                     FROM temp_emails WHERE user_id = ? ORDER BY is_favorite DESC, created_at DESC""", (user_id,))
        emails = c.fetchall()
        conn.close()
        return [{"id": e[0], "email": e[1], "prefix": e[2], "domain": e[3], "service": e[4], "created_at": e[5], "last_checked": e[6], "is_favorite": e[7]} for e in emails]

    def get_unread_count(self, user_id, email_id):
        conn = sqlite3.connect("tempmail.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM messages WHERE user_id = ? AND email_id = ? AND is_read = 0", (user_id, email_id))
        count = c.fetchone()[0]
        conn.close()
        return count

email_service = EmailService()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TempMail - Send & Receive</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300;14..32,400;14..32,500;14..32,600;14..32,700;14..32,800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        :root {
            --primary: #6366f1;
            --primary-dark: #4f46e5;
            --primary-light: #818cf8;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
        }

        [data-theme="dark"] {
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-tertiary: #334155;
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --border: #334155;
            --card-bg: #1e293b;
            --hover: #334155;
        }

        [data-theme="light"] {
            --bg-primary: #f1f5f9;
            --bg-secondary: #ffffff;
            --bg-tertiary: #f8fafc;
            --text-primary: #0f172a;
            --text-secondary: #64748b;
            --border: #e2e8f0;
            --card-bg: #ffffff;
            --hover: #f1f5f9;
        }

        body {
            font-family: 'Inter', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            transition: all 0.3s;
        }

        .auth-container {
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #6366f1, #ec4899);
        }

        .auth-card {
            background: var(--card-bg);
            border-radius: 32px;
            padding: 48px;
            width: 460px;
            box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);
        }

        .auth-logo {
            text-align: center;
            margin-bottom: 40px;
        }

        .auth-logo i {
            font-size: 48px;
            background: linear-gradient(135deg, #6366f1, #ec4899);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .auth-logo h1 {
            font-size: 28px;
            margin-top: 12px;
            background: linear-gradient(135deg, #6366f1, #ec4899);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .auth-tabs {
            display: flex;
            gap: 12px;
            margin-bottom: 32px;
            background: var(--bg-primary);
            padding: 6px;
            border-radius: 60px;
        }

        .auth-tab {
            flex: 1;
            padding: 12px;
            border: none;
            background: transparent;
            font-weight: 600;
            cursor: pointer;
            border-radius: 50px;
            color: var(--text-secondary);
            font-family: inherit;
        }

        .auth-tab.active {
            background: var(--primary);
            color: white;
        }

        .auth-form {
            display: none;
        }

        .auth-form.active {
            display: block;
            animation: fadeIn 0.3s;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .input-group {
            margin-bottom: 24px;
        }

        .input-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: var(--text-secondary);
            font-size: 14px;
        }

        .input-group input, .input-group textarea {
            width: 100%;
            padding: 14px 16px;
            background: var(--bg-primary);
            border: 2px solid var(--border);
            border-radius: 16px;
            font-family: inherit;
            color: var(--text-primary);
            transition: all 0.3s;
            font-size: 14px;
        }

        .input-group input:focus, .input-group textarea:focus {
            outline: none;
            border-color: var(--primary);
        }

        .btn {
            padding: 14px 24px;
            border: none;
            border-radius: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            font-family: inherit;
            font-size: 14px;
        }

        .btn-primary {
            background: var(--primary);
            color: white;
            width: 100%;
        }

        .btn-primary:hover {
            background: var(--primary-dark);
            transform: translateY(-2px);
        }

        .app-container {
            display: none;
        }

        .sidebar {
            width: 300px;
            background: var(--card-bg);
            border-right: 1px solid var(--border);
            position: fixed;
            left: 0;
            top: 0;
            bottom: 0;
            overflow-y: auto;
        }

        .sidebar-header {
            padding: 24px;
            border-bottom: 1px solid var(--border);
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 20px;
            font-weight: 700;
            background: linear-gradient(135deg, var(--primary), #ec4899);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .user-info {
            padding: 20px 24px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .user-avatar {
            width: 48px;
            height: 48px;
            background: linear-gradient(135deg, var(--primary), #ec4899);
            border-radius: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 20px;
            color: white;
        }

        .email-list {
            padding: 16px;
        }

        .email-item {
            background: var(--bg-primary);
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 12px;
            cursor: pointer;
            transition: all 0.3s;
            border: 2px solid transparent;
        }

        .email-item:hover {
            transform: translateX(4px);
            background: var(--hover);
        }

        .email-item.active {
            border-color: var(--primary);
        }

        .email-address {
            font-size: 13px;
            font-weight: 600;
            word-break: break-all;
            margin-bottom: 8px;
        }

        .email-meta {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: var(--text-secondary);
        }

        .main-content {
            margin-left: 300px;
            padding: 24px;
        }

        .top-bar {
            background: var(--card-bg);
            border-radius: 24px;
            padding: 16px 24px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            border: 1px solid var(--border);
        }

        .action-buttons {
            display: flex;
            gap: 12px;
        }

        .action-btn {
            background: var(--bg-primary);
            border: 1px solid var(--border);
            padding: 10px 20px;
            border-radius: 40px;
            cursor: pointer;
            font-family: inherit;
            font-weight: 500;
            color: var(--text-primary);
        }

        .action-btn:hover {
            background: var(--primary);
            color: white;
            border-color: var(--primary);
        }

        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }

        .card {
            background: var(--card-bg);
            border-radius: 24px;
            border: 1px solid var(--border);
            overflow: hidden;
        }

        .card-header {
            padding: 20px 24px;
            border-bottom: 1px solid var(--border);
            font-weight: 600;
        }

        .compose-form {
            padding: 20px 24px;
        }

        .messages-list {
            max-height: 500px;
            overflow-y: auto;
        }

        .message-item {
            padding: 16px 24px;
            border-bottom: 1px solid var(--border);
            cursor: pointer;
            transition: all 0.3s;
            position: relative;
        }

        .message-item:hover {
            background: var(--hover);
        }

        .message-item.unread::before {
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 3px;
            background: var(--primary);
        }

        .message-from {
            font-weight: 600;
            margin-bottom: 4px;
        }

        .message-subject {
            font-size: 13px;
            color: var(--text-secondary);
            margin-bottom: 4px;
        }

        .message-date {
            font-size: 11px;
            color: var(--text-secondary);
        }

        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--text-secondary);
        }

        .empty-state i {
            font-size: 48px;
            margin-bottom: 16px;
            opacity: 0.5;
        }

        .modal {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.8);
            backdrop-filter: blur(8px);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }

        .modal-content {
            background: var(--card-bg);
            border-radius: 32px;
            max-width: 600px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
        }

        .modal-header {
            padding: 20px 24px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .modal-body {
            padding: 24px;
        }

        .toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: var(--primary);
            color: white;
            padding: 12px 20px;
            border-radius: 16px;
            z-index: 2000;
            animation: slideIn 0.3s;
        }

        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }

        .theme-toggle {
            position: fixed;
            bottom: 24px;
            left: 324px;
            width: 40px;
            height: 40px;
            background: var(--card-bg);
            border-radius: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            border: 1px solid var(--border);
            z-index: 99;
        }

        .loading {
            width: 20px;
            height: 20px;
            border: 2px solid var(--border);
            border-top-color: var(--primary);
            border-radius: 50%;
            animation: spin 0.6s linear infinite;
            display: inline-block;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        @media (max-width: 768px) {
            .sidebar {
                transform: translateX(-100%);
                transition: transform 0.3s;
                z-index: 100;
            }
            .sidebar.open {
                transform: translateX(0);
            }
            .main-content {
                margin-left: 0;
            }
            .grid-2 {
                grid-template-columns: 1fr;
            }
            .theme-toggle {
                left: 20px;
            }
        }

        ::-webkit-scrollbar {
            width: 6px;
        }
        ::-webkit-scrollbar-track {
            background: var(--bg-primary);
        }
        ::-webkit-scrollbar-thumb {
            background: var(--primary);
            border-radius: 3px;
        }
    </style>
</head>
<body>
    <div class="auth-container" id="authContainer">
        <div class="auth-card">
            <div class="auth-logo">
                <i class="fas fa-paper-plane"></i>
                <h1>TempMail</h1>
                <p>Send & Receive Temporary Emails</p>
            </div>
            <div class="auth-tabs">
                <button class="auth-tab active" onclick="switchTab('login')">Sign In</button>
                <button class="auth-tab" onclick="switchTab('register')">Sign Up</button>
            </div>
            <div id="loginForm" class="auth-form active">
                <div id="loginError" style="display: none; color: #ef4444; margin-bottom: 16px; font-size: 14px;"></div>
                <div class="input-group">
                    <label>Username</label>
                    <input type="text" id="loginUsername" placeholder="Enter username">
                </div>
                <div class="input-group">
                    <label>Password</label>
                    <input type="password" id="loginPassword" placeholder="Enter password">
                </div>
                <button class="btn btn-primary" onclick="login()">Sign In</button>
            </div>
            <div id="registerForm" class="auth-form">
                <div id="registerError" style="display: none; color: #ef4444; margin-bottom: 16px; font-size: 14px;"></div>
                <div class="input-group">
                    <label>Username</label>
                    <input type="text" id="regUsername" placeholder="Choose username">
                </div>
                <div class="input-group">
                    <label>Password</label>
                    <input type="password" id="regPassword" placeholder="Choose password">
                </div>
                <div class="input-group">
                    <label>Confirm Password</label>
                    <input type="password" id="regConfirmPassword" placeholder="Confirm password">
                </div>
                <button class="btn btn-primary" onclick="register()">Sign Up</button>
            </div>
        </div>
    </div>

    <div class="app-container" id="appContainer">
        <div class="sidebar" id="sidebar">
            <div class="sidebar-header">
                <div class="logo">
                    <i class="fas fa-paper-plane"></i>
                    <span>TempMail</span>
                </div>
            </div>
            <div class="user-info">
                <div class="user-avatar" id="userAvatar">A</div>
                <div>
                    <div id="userName" style="font-weight: 600;">Admin</div>
                    <div style="font-size: 12px; color: var(--text-secondary);" id="emailCount">0 mailboxes</div>
                </div>
            </div>
            <div class="email-list" id="emailList"></div>
        </div>

        <div class="main-content">
            <div class="top-bar">
                <div>
                    <h3 id="currentEmail">Select a mailbox</h3>
                </div>
                <div class="action-buttons">
                    <button class="action-btn" onclick="createEmail()"><i class="fas fa-plus"></i> New</button>
                    <button class="action-btn" onclick="refreshInbox()"><i class="fas fa-sync-alt"></i> Refresh</button>
                    <button class="action-btn" onclick="toggleSidebar()"><i class="fas fa-bars"></i></button>
                </div>
            </div>

            <div class="grid-2">
                <div class="card">
                    <div class="card-header">
                        <i class="fas fa-paper-plane"></i> Compose Message
                    </div>
                    <div class="compose-form">
                        <div class="input-group">
                            <label>From</label>
                            <input type="text" id="composeFrom" placeholder="Select an email first" readonly>
                        </div>
                        <div class="input-group">
                            <label>To</label>
                            <input type="email" id="composeTo" placeholder="recipient@example.com">
                        </div>
                        <div class="input-group">
                            <label>Subject</label>
                            <input type="text" id="composeSubject" placeholder="Subject">
                        </div>
                        <div class="input-group">
                            <label>Message</label>
                            <textarea id="composeBody" rows="4" placeholder="Your message..."></textarea>
                        </div>
                        <button class="btn btn-primary" onclick="sendEmail()" style="width: 100%;">
                            <i class="fas fa-paper-plane"></i> Send Email
                        </button>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <i class="fas fa-inbox"></i> Inbox
                        <span id="unreadBadge" style="float: right; background: var(--primary); padding: 2px 8px; border-radius: 20px; font-size: 11px;"></span>
                    </div>
                    <div class="messages-list" id="messagesList"></div>
                </div>
            </div>
        </div>
    </div>

    <div class="theme-toggle" onclick="toggleTheme()">
        <i class="fas fa-moon"></i>
    </div>

    <div class="modal" id="messageModal">
        <div class="modal-content">
            <div class="modal-header">
                <h3 id="modalSubject"></h3>
                <button class="btn" onclick="closeModal()" style="background: transparent; padding: 8px 12px;">&times;</button>
            </div>
            <div class="modal-body" id="modalBody"></div>
        </div>
    </div>

    <script>
        let currentEmailId = null;
        let currentEmailAddress = null;
        let refreshInterval = null;
        let theme = localStorage.getItem('theme') || 'dark';

        function setTheme() {
            document.body.setAttribute('data-theme', theme);
            const icon = document.querySelector('.theme-toggle i');
            if (theme === 'dark') {
                icon.classList.remove('fa-sun');
                icon.classList.add('fa-moon');
            } else {
                icon.classList.remove('fa-moon');
                icon.classList.add('fa-sun');
            }
        }

        function toggleTheme() {
            theme = theme === 'dark' ? 'light' : 'dark';
            localStorage.setItem('theme', theme);
            setTheme();
        }

        function toggleSidebar() {
            document.getElementById('sidebar').classList.toggle('open');
        }

        function showToast(message, isError = false) {
            const toast = document.createElement('div');
            toast.className = 'toast';
            toast.style.background = isError ? '#ef4444' : '#6366f1';
            toast.innerHTML = `<i class="fas ${isError ? 'fa-exclamation-triangle' : 'fa-check-circle'}"></i> ${message}`;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }

        function switchTab(tab) {
            document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.auth-form').forEach(f => f.classList.remove('active'));
            if (tab === 'login') {
                document.querySelectorAll('.auth-tab')[0].classList.add('active');
                document.getElementById('loginForm').classList.add('active');
            } else {
                document.querySelectorAll('.auth-tab')[1].classList.add('active');
                document.getElementById('registerForm').classList.add('active');
            }
        }

        async function login() {
            const username = document.getElementById('loginUsername').value;
            const password = document.getElementById('loginPassword').value;
            const errorDiv = document.getElementById('loginError');

            if (!username || !password) {
                errorDiv.textContent = 'Fill all fields';
                errorDiv.style.display = 'block';
                setTimeout(() => errorDiv.style.display = 'none', 3000);
                return;
            }

            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                const data = await res.json();
                if (res.ok) {
                    document.getElementById('userName').innerText = username;
                    document.getElementById('userAvatar').innerText = username[0].toUpperCase();
                    document.getElementById('authContainer').style.display = 'none';
                    document.getElementById('appContainer').style.display = 'block';
                    await loadEmails();
                    startAutoRefresh();
                    showToast('Welcome, ' + username);
                } else {
                    errorDiv.textContent = data.error;
                    errorDiv.style.display = 'block';
                    setTimeout(() => errorDiv.style.display = 'none', 3000);
                }
            } catch (error) {
                errorDiv.textContent = 'Network error';
                errorDiv.style.display = 'block';
                setTimeout(() => errorDiv.style.display = 'none', 3000);
            }
        }

        async function register() {
            const username = document.getElementById('regUsername').value;
            const password = document.getElementById('regPassword').value;
            const confirm = document.getElementById('regConfirmPassword').value;
            const errorDiv = document.getElementById('registerError');

            if (!username || !password) {
                errorDiv.textContent = 'Fill all fields';
                errorDiv.style.display = 'block';
                setTimeout(() => errorDiv.style.display = 'none', 3000);
                return;
            }
            if (password !== confirm) {
                errorDiv.textContent = 'Passwords do not match';
                errorDiv.style.display = 'block';
                setTimeout(() => errorDiv.style.display = 'none', 3000);
                return;
            }
            if (password.length < 4) {
                errorDiv.textContent = 'Password too short';
                errorDiv.style.display = 'block';
                setTimeout(() => errorDiv.style.display = 'none', 3000);
                return;
            }

            try {
                const res = await fetch('/api/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                const data = await res.json();
                if (res.ok) {
                    showToast('Registered! Please login.');
                    switchTab('login');
                    document.getElementById('loginUsername').value = username;
                } else {
                    errorDiv.textContent = data.error;
                    errorDiv.style.display = 'block';
                    setTimeout(() => errorDiv.style.display = 'none', 3000);
                }
            } catch (error) {
                errorDiv.textContent = 'Network error';
                errorDiv.style.display = 'block';
                setTimeout(() => errorDiv.style.display = 'none', 3000);
            }
        }

        async function logout() {
            if (refreshInterval) clearInterval(refreshInterval);
            await fetch('/api/logout', { method: 'POST' });
            document.getElementById('authContainer').style.display = 'flex';
            document.getElementById('appContainer').style.display = 'none';
            currentEmailId = null;
            showToast('Logged out');
        }

        async function loadEmails() {
            try {
                const res = await fetch('/api/emails');
                const emails = await res.json();
                const container = document.getElementById('emailList');
                document.getElementById('emailCount').innerText = emails.length + ' mailboxes';

                if (emails.length === 0) {
                    container.innerHTML = '<div class="empty-state"><i class="fas fa-inbox"></i><p>No mailboxes</p><button class="btn btn-primary" style="margin-top: 16px;" onclick="createEmail()">Create New</button></div>';
                    return;
                }

                container.innerHTML = emails.map(e => `
                    <div class="email-item ${currentEmailId === e.id ? 'active' : ''}" onclick="selectEmail(${e.id}, '${e.email}')">
                        <div class="email-address">${escapeHtml(e.email)}</div>
                        <div class="email-meta">
                            <span>📅 ${new Date(e.created_at).toLocaleDateString()}</span>
                            <span id="badge_${e.id}" style="background: var(--primary); padding: 2px 6px; border-radius: 20px; font-size: 10px;"></span>
                        </div>
                    </div>
                `).join('');

                for (const e of emails) {
                    updateUnreadCount(e.id);
                }

                if (emails.length > 0 && !currentEmailId) {
                    selectEmail(emails[0].id, emails[0].email);
                }
            } catch (error) {
                console.error(error);
            }
        }

        async function updateUnreadCount(emailId) {
            try {
                const res = await fetch(`/api/unread/${emailId}`);
                const data = await res.json();
                const badge = document.getElementById(`badge_${emailId}`);
                if (data.count > 0 && badge) {
                    badge.innerText = data.count;
                    badge.style.display = 'inline-block';
                } else if (badge) {
                    badge.innerText = '';
                    badge.style.display = 'none';
                }
                if (emailId === currentEmailId) {
                    document.getElementById('unreadBadge').innerText = data.count > 0 ? `${data.count} unread` : '';
                }
            } catch (error) {}
        }

        async function createEmail() {
            try {
                const res = await fetch('/api/create-email', { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    await loadEmails();
                    selectEmail(data.id, data.email);
                    showToast('Created: ' + data.email);
                }
            } catch (error) {
                showToast('Failed to create', true);
            }
        }

        async function selectEmail(id, email) {
            currentEmailId = id;
            currentEmailAddress = email;
            document.getElementById('currentEmail').innerHTML = `<i class="fas fa-envelope"></i> ${email}`;
            document.getElementById('composeFrom').value = email;
            await loadEmails();
            await loadMessages();
        }

        async function loadMessages() {
            if (!currentEmailId) return;
            const container = document.getElementById('messagesList');
            container.innerHTML = '<div class="empty-state"><div class="loading"></div><p>Loading...</p></div>';

            try {
                const res = await fetch(`/api/messages/${currentEmailId}`);
                const messages = await res.json();

                if (messages.length === 0) {
                    container.innerHTML = '<div class="empty-state"><i class="fas fa-inbox"></i><p>No messages yet</p><p style="font-size: 12px;">Send an email to your address</p></div>';
                    return;
                }

                container.innerHTML = messages.map(m => `
                    <div class="message-item ${!m.is_read ? 'unread' : ''}" onclick="viewMessage(${m.id}, ${!m.is_read})">
                        <div class="message-from">${escapeHtml(m.from_name || m.from_addr || 'Unknown')}</div>
                        <div class="message-subject">${escapeHtml(m.subject || '(No subject)')}</div>
                        <div class="message-date">${new Date(m.received_at).toLocaleString()}</div>
                    </div>
                `).join('');

                await updateUnreadCount(currentEmailId);
            } catch (error) {
                container.innerHTML = '<div class="empty-state"><i class="fas fa-exclamation-triangle"></i><p>Error loading</p></div>';
            }
        }

        async function refreshInbox() {
            if (!currentEmailId) return;
            await loadMessages();
            showToast('Inbox refreshed');
        }

        async function sendEmail() {
            const to = document.getElementById('composeTo').value;
            const subject = document.getElementById('composeSubject').value;
            const body = document.getElementById('composeBody').value;

            if (!currentEmailAddress) {
                showToast('Select a sender email first', true);
                return;
            }
            if (!to) {
                showToast('Enter recipient email', true);
                return;
            }
            if (!subject && !body) {
                showToast('Enter subject or message', true);
                return;
            }

            const btn = event.target;
            const originalText = btn.innerHTML;
            btn.innerHTML = '<div class="loading"></div> Sending...';
            btn.disabled = true;

            try {
                const res = await fetch('/api/send', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        from_email: currentEmailAddress,
                        to_email: to,
                        subject: subject,
                        body: body
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    showToast('Email sent!');
                    document.getElementById('composeTo').value = '';
                    document.getElementById('composeSubject').value = '';
                    document.getElementById('composeBody').value = '';
                } else {
                    showToast(data.error || 'Failed to send', true);
                }
            } catch (error) {
                showToast('Network error', true);
            } finally {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        }

        async function viewMessage(id, isUnread) {
            if (isUnread) {
                await fetch(`/api/mark-read/${id}`, { method: 'POST' });
                await updateUnreadCount(currentEmailId);
                await loadMessages();
            }

            try {
                const res = await fetch(`/api/message/${id}`);
                const msg = await res.json();
                document.getElementById('modalSubject').innerHTML = `<i class="fas fa-envelope"></i> ${escapeHtml(msg.subject || '(No subject)')}`;
                document.getElementById('modalBody').innerHTML = `
                    <div style="margin-bottom: 20px; padding: 16px; background: var(--bg-primary); border-radius: 16px;">
                        <div><strong>From:</strong> ${escapeHtml(msg.from_name || 'Unknown')}</div>
                        <div style="margin-top: 8px;"><strong>Received:</strong> ${new Date(msg.received_at).toLocaleString()}</div>
                    </div>
                    <div style="white-space: pre-wrap;">${escapeHtml(msg.body || 'No content')}</div>
                `;
                document.getElementById('messageModal').style.display = 'flex';
            } catch (error) {
                console.error(error);
            }
        }

        function closeModal() {
            document.getElementById('messageModal').style.display = 'none';
        }

        function startAutoRefresh() {
            if (refreshInterval) clearInterval(refreshInterval);
            refreshInterval = setInterval(() => {
                if (currentEmailId) loadMessages();
            }, 30000);
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        async function checkAuth() {
            try {
                const res = await fetch('/api/check-auth');
                if (res.ok) {
                    const data = await res.json();
                    document.getElementById('userName').innerText = data.username;
                    document.getElementById('userAvatar').innerText = data.username[0].toUpperCase();
                    document.getElementById('authContainer').style.display = 'none';
                    document.getElementById('appContainer').style.display = 'block';
                    await loadEmails();
                    startAutoRefresh();
                }
            } catch (error) {}
        }

        setTheme();
        checkAuth();

        document.getElementById('loginPassword').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') login();
        });
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters"}), 400

    hashed = hashlib.sha256(password.encode()).hexdigest()
    conn = sqlite3.connect("tempmail.db")
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)", (username, hashed, datetime.now()))
        conn.commit()
        return jsonify({"message": "User created successfully"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already exists"}), 400
    finally:
        conn.close()

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    hashed = hashlib.sha256(password.encode()).hexdigest()
    conn = sqlite3.connect("tempmail.db")
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE username = ? AND password = ?", (username, hashed))
    user = c.fetchone()
    conn.close()
    if user:
        session["user_id"] = user[0]
        session["username"] = user[1]
        return jsonify({"message": "Login successful", "username": user[1]}), 200
    return jsonify({"error": "Invalid credentials"}), 401

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"}), 200

@app.route("/api/check-auth")
def check_auth():
    if "user_id" in session:
        return jsonify({"username": session["username"]}), 200
    return jsonify({"error": "Not authenticated"}), 401

@app.route("/api/create-email", methods=["POST"])
@login_required
def create_email():
    result = email_service.create_temp_email(session["user_id"])
    return jsonify(result), 200

@app.route("/api/emails")
@login_required
def get_emails():
    emails = email_service.get_user_emails(session["user_id"])
    return jsonify(emails), 200

@app.route("/api/messages/<int:email_id>")
@login_required
def get_messages(email_id):
    messages = email_service.get_messages(session["user_id"], email_id)
    return jsonify(messages), 200

@app.route("/api/message/<int:message_id>")
@login_required
def get_message(message_id):
    conn = sqlite3.connect("tempmail.db")
    c = conn.cursor()
    c.execute("SELECT from_name, from_addr, subject, body, received_at FROM messages WHERE id = ? AND user_id = ?", (message_id, session["user_id"]))
    message = c.fetchone()
    conn.close()
    if message:
        return jsonify({"from_name": message[0], "from_addr": message[1], "subject": message[2], "body": message[3], "received_at": message[4]}), 200
    return jsonify({"error": "Message not found"}), 404

@app.route("/api/mark-read/<int:message_id>", methods=["POST"])
@login_required
def mark_read(message_id):
    email_service.mark_as_read(session["user_id"], message_id)
    return jsonify({"message": "Marked as read"}), 200

@app.route("/api/unread/<int:email_id>")
@login_required
def get_unread_count(email_id):
    count = email_service.get_unread_count(session["user_id"], email_id)
    return jsonify({"count": count}), 200

@app.route("/api/send", methods=["POST"])
@login_required
def send_email():
    data = request.json
    from_email = data.get("from_email")
    to_email = data.get("to_email")
    subject = data.get("subject", "")
    body = data.get("body", "")

    success, message = email_service.send_email(from_email, to_email, subject, body)

    if success:
        conn = sqlite3.connect("tempmail.db")
        c = conn.cursor()
        c.execute("""INSERT INTO sent_messages (user_id, from_email, to_email, subject, body, sent_at, status)
                     VALUES (?, ?, ?, ?, ?, ?, ?)""",
                  (session["user_id"], from_email, to_email, subject, body, datetime.now(), "sent"))
        conn.commit()
        conn.close()
        return jsonify({"message": "Email sent successfully"}), 200
    else:
        return jsonify({"error": f"Cannot send email: {message}"}), 500

if __name__ == "__main__":
    print("=" * 60)
    print(" TempMail - Send & Receive Temporary Email")
    print("=" * 60)
    print("")
    print(" Open: http://localhost:5000")
    print(" Login: admin / admin123")
    print("")
    print(" Features:")
    print(" - Create temporary email addresses")
    print(" - Receive emails (via 1secmail API)")
    print(" - Send emails (via SMTP)")
    print(" - Dark/Light theme")
    print(" - Real-time inbox refresh")
    print("")
    print("=" * 60)
    app.run(debug=True, host="0.0.0.0", port=5000)

