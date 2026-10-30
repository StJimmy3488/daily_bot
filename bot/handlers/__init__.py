from aiogram import Router

from bot.handlers import add, capture, common, plan, tasks


def build_router() -> Router:
    root = Router()
    # Order matters: capture is the catch-all for plain text, so it goes last.
    root.include_routers(common.router, add.router, tasks.router, plan.router, capture.router)
    return root
