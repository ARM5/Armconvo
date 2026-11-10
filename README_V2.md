# Instagram Group Bot v2

A safer starter based on the original Armconvo project.

## Features
- Credentials are read from a local .env file, not source code.
- Finds one group by its exact title.
- Welcomes members detected after the first baseline scan.
- SQLite keeps member and message records across restarts.
- Commands: !help, !ping, !rules.
- Admin-only commands: !mute, !unmute, !welcome on, !welcome off.
- !ask is a placeholder; no AI provider is connected.
- Does not auto-reply to every ordinary group message.

## Setup
1. Use Python 3.10 or newer.
2. Install dependencies: pip install -r requirements-v2.txt
3. Copy .env.example to .env and fill in your own values.
4. Run: python bot_v2.py

Keep .env, .ig_session.json, and group_bot.sqlite3 private. Never commit them.

## Limitations and safety
This starter uses instagrapi, an unofficial Instagram private API, not Meta's official Graph API. Instagram may challenge, rate-limit, or restrict the account. Use a test account, keep activity low, and only use the bot in groups where members and admins approve it. Instagram can change private endpoints at any time, so operation is not guaranteed.

AI-generated replies, automatic moderation, and a web dashboard are not included yet. Connect an AI provider only after choosing one and storing its API key outside source control.
