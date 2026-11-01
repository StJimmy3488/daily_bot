"""Print Telegram Mini App init data signed with your bot token, for local development.

    uv run python -m bot.dev_init_data

Put the output into webapp/.env.local as VITE_DEV_INIT_DATA=... so `npm run dev`
works in a normal browser. It's valid for a day, like real init data.
"""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from bot.config import get_settings


def sign_init_data(bot_token: str, user_id: int, auth_date: int | None = None) -> str:
    fields = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "dev",
        "user": json.dumps({"id": user_id, "first_name": "Dev"}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


if __name__ == "__main__":
    settings = get_settings()
    print(sign_init_data(settings.bot_token, settings.owner_id))
