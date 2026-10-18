"""Main menu keyboard."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/watchlist"), KeyboardButton(text="/status")],
            [KeyboardButton(text="/help")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )