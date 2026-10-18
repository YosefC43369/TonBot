"""Handler for /balance command."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import get_settings
from app.logging_config import get_logger
from security.input_validation import escape_mdv2, validate_command_arg
from security.redaction import safe_error_message
from services.balance_service import BalanceService
from ton.address import AddressValidationError
from ton.base_client import ProviderError
from ton.tonapi_client import TonApiClient

log = get_logger(__name__)
router = Router(name="balance")


@router.message(Command("balance"))
async def cmd_balance(message: Message) -> None:
    """
    /balance ADDRESS
    Fetch and display TON and Jetton balances for an address.
    """
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Usage: <code>/balance ADDRESS</code>", parse_mode="HTML"
        )
        return

    raw_address = validate_command_arg(args[1])
    settings = get_settings()

    await message.answer("⏳ Fetching balance…", parse_mode=None)

    async with TonApiClient(
        base_url=settings.tonapi_base_url,
        api_key=settings.tonapi_key,
        timeout_seconds=settings.http_timeout_seconds,
    ) as client:
        svc = BalanceService(client)
        try:
            result = await svc.get_balance(raw_address)
        except AddressValidationError as exc:
            await message.answer(f"Invalid address: {exc}", parse_mode=None)
            return
        except ProviderError as exc:
            log.warning("balance_provider_error", error=safe_error_message(exc))
            await message.answer(
                "Could not retrieve balance right now. Please try again later.",
                parse_mode=None,
            )
            return

    if result.account_not_found:
        await message.answer(
            f"<code>{result.canonical_address}</code>\n\nAccount not found on-chain "
            "(never initialized or incorrect address).",
            parse_mode="HTML",
        )
        return

    scam_flag = " ⚠ <b>SCAM FLAGGED</b>" if result.is_scam else ""
    name_line = f"\nName: {escape_mdv2(result.account_name)}" if result.account_name else ""

    lines = [
        f"<b>Balance</b>{scam_flag}",
        f"<code>{result.canonical_address}</code>{name_line}",
        f"Status: {result.status}",
        f"\n💎 <b>{result.ton_formatted} TON</b>",
    ]

    if result.jettons:
        lines.append("\n🪙 <b>Jettons:</b>")
        for j in result.jettons[:20]:  # cap display at 20
            lines.append(
                f"• {escape_mdv2(j.symbol)}: {escape_mdv2(j.formatted_balance)}"
            )
        if len(result.jettons) > 20:
            lines.append(f"…and {len(result.jettons) - 20} more")

    await message.answer("\n".join(lines), parse_mode="HTML")