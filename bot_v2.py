import logging
import os
import signal
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv
from instagrapi import Client

load_dotenv()

USERNAME = os.getenv("IG_USERNAME", "").strip()
PASSWORD = os.getenv("IG_PASSWORD", "")
GROUP_NAME = os.getenv("IG_GROUP_NAME", "").strip()
ADMIN_USERNAMES = {x.strip().lstrip("@").lower() for x in os.getenv("BOT_ADMINS", "").split(",") if x.strip()}
POLL_SECONDS = max(10, int(os.getenv("POLL_SECONDS", "20")))
WELCOME_ENABLED = os.getenv("WELCOME_ENABLED", "true").lower() == "true"
RULES_TEXT = os.getenv("GROUP_RULES", "Be respectful. No spam or harassment.")
DB_PATH = Path(os.getenv("BOT_DB", "group_bot.sqlite3"))
SESSION_PATH = Path(os.getenv("SESSION_FILE", ".ig_session.json"))

if not USERNAME or not PASSWORD or not GROUP_NAME:
    raise SystemExit("Set IG_USERNAME, IG_PASSWORD and IG_GROUP_NAME in your .env file.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("group-bot")
client = Client()
running = True
muted = False


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS seen_messages (message_id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE IF NOT EXISTS members (user_id TEXT PRIMARY KEY, username TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    return conn


def setting(conn, key, default):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()


def login():
    if SESSION_PATH.exists():
        try:
            client.load_settings(str(SESSION_PATH))
            client.login(USERNAME, PASSWORD)
            log.info("Logged in using saved session")
            return
        except Exception as exc:
            log.warning("Saved session could not be reused: %s", exc)
    client.login(USERNAME, PASSWORD)
    client.dump_settings(str(SESSION_PATH))
    try:
        SESSION_PATH.chmod(0o600)
    except OSError:
        pass
    log.info("Fresh login successful; session saved locally")


def find_group_thread_id():
    result = client.private_request("direct_v2/inbox/", {})
    for thread in result.get("inbox", {}).get("threads", []):
        if (thread.get("thread_title") or "").strip() == GROUP_NAME:
            return thread.get("thread_id")
    return None


def safe_send(thread_id, message):
    try:
        client.direct_send(message[:900], thread_ids=[thread_id])
        return True
    except Exception as exc:
        log.warning("Could not send group message: %s", exc)
        return False


def uname(user):
    return (getattr(user, "username", "") or "").strip()


def uid(user):
    return str(getattr(user, "pk", "") or "")


def handle_command(conn, thread_id, sender, raw_text):
    global muted
    parts = (raw_text or "").strip().split(maxsplit=1)
    if not parts:
        return
    command = parts[0].lower()
    is_admin = sender.lower() in ADMIN_USERNAMES

    if command in ("!help", "!commands"):
        safe_send(thread_id, "🤖 Group Bot Commands\n!ping — bot status\n!rules — group rules\n!help — commands\nAdmin: !mute, !unmute, !welcome on/off")
    elif command == "!ping":
        safe_send(thread_id, "Pong! 🟢 Bot is active.")
    elif command == "!rules":
        safe_send(thread_id, "📌 Group rules:\n" + RULES_TEXT)
    elif command in ("!mute", "!unmute", "!welcome"):
        if not is_admin:
            safe_send(thread_id, "Only configured group admins can use this command.")
            return
        if command == "!mute":
            muted = True
            set_setting(conn, "muted", "true")
            safe_send(thread_id, "🔕 Bot replies paused by an admin.")
        elif command == "!unmute":
            muted = False
            set_setting(conn, "muted", "false")
            safe_send(thread_id, "🔔 Bot replies resumed.")
        else:
            arg = parts[1].lower() if len(parts) > 1 else ""
            if arg not in ("on", "off"):
                safe_send(thread_id, "Use !welcome on or !welcome off")
            else:
                set_setting(conn, "welcome_enabled", arg)
                safe_send(thread_id, "Welcome messages: " + arg)
    elif command == "!ask":
        safe_send(thread_id, "AI replies are not connected yet. Choose an AI provider and add its API key privately before enabling generated replies.")


def seed_existing_members(conn, thread):
    count = conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    if count:
        return
    for user in getattr(thread, "users", []):
        user_id, username = uid(user), uname(user)
        if user_id and username:
            conn.execute("INSERT OR IGNORE INTO members(user_id, username) VALUES(?,?)", (user_id, username))
    conn.commit()
    log.info("Current members saved as baseline; no welcome spam on first startup")


def welcome_new_members(conn, thread_id, thread):
    enabled = setting(conn, "welcome_enabled", "on" if WELCOME_ENABLED else "off") == "on"
    if not enabled:
        return
    for user in getattr(thread, "users", []):
        user_id, username = uid(user), uname(user)
        if not user_id or not username or username.lower() == USERNAME.lower():
            continue
        exists = conn.execute("SELECT 1 FROM members WHERE user_id=?", (user_id,)).fetchone()
        if not exists and safe_send(thread_id, f"👋 Welcome @{username}! Please check !rules and enjoy the group."):
            conn.execute("INSERT OR IGNORE INTO members(user_id, username) VALUES(?,?)", (user_id, username))
            conn.commit()
            log.info("Welcomed new member @%s", username)


def process_messages(conn, thread_id, thread):
    global muted
    muted = setting(conn, "muted", "false") == "true"
    for item in reversed(list(getattr(thread, "messages", []))):
        message_id = str(getattr(item, "id", "") or getattr(item, "pk", ""))
        sender = uname(getattr(item, "user", None))
        body = getattr(item, "text", "") or ""
        if not message_id or not sender or sender.lower() == USERNAME.lower():
            continue
        seen = conn.execute("SELECT 1 FROM seen_messages WHERE message_id=?", (message_id,)).fetchone()
        if seen:
            continue
        conn.execute("INSERT OR IGNORE INTO seen_messages(message_id) VALUES(?)", (message_id,))
        conn.commit()
        if body.strip().startswith("!") and not muted:
            handle_command(conn, thread_id, sender, body)


def stop(_signum, _frame):
    global running
    running = False


def main():
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    conn = db()
    login()
    thread_id = find_group_thread_id()
    if not thread_id:
        raise SystemExit(f'Group "{GROUP_NAME}" was not found in the Instagram inbox.')
    thread = client.direct_thread(thread_id)
    seed_existing_members(conn, thread)
    log.info("Bot started for group: %s", GROUP_NAME)
    while running:
        try:
            thread = client.direct_thread(thread_id)
            welcome_new_members(conn, thread_id, thread)
            process_messages(conn, thread_id, thread)
        except Exception:
            log.exception("Polling cycle failed")
        time.sleep(POLL_SECONDS)
    conn.close()
    log.info("Bot stopped")


if __name__ == "__main__":
    main()
