import os
import subprocess
import sys
from flask import Flask, jsonify

app = Flask(__name__)
bot_process = None


def start_bot():
    global bot_process
    if bot_process is None or bot_process.poll() is not None:
        bot_process = subprocess.Popen([sys.executable, "bot_v2.py"], env=os.environ.copy())


@app.route("/")
@app.route("/health")
def health():
    process_running = bot_process is not None and bot_process.poll() is None
    return jsonify({"service": "instagram-group-bot-test", "web": "ok", "bot_process": "running" if process_running else "stopped"})


@app.before_request
def ensure_bot_started():
    start_bot()
