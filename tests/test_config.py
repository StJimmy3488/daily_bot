from bot.config import Settings


def test_public_url_defaults_to_domain():
    s = Settings(bot_token="1:x", owner_id=1, domain="2.31.133.165.sslip.io", _env_file=None)
    assert s.public_url == "https://2.31.133.165.sslip.io"


def test_public_url_explicit_wins_and_local_fallback():
    assert (
        Settings(bot_token="1:x", owner_id=1, domain="a.b", public_url="https://c.d/", _env_file=None).public_url
        == "https://c.d"
    )
    assert Settings(bot_token="1:x", owner_id=1, _env_file=None).public_url == "http://localhost:8080"
