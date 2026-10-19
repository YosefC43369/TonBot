"""Handlers for TON deposit / invoice flow."""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from app.logging_config import get_logger
from database.invoice_service import (
    InvoiceAmountInvalid, InvoiceAuthorizationError,
    InvoiceNotFound, InvoiceService,
)
from database.session import get_session
from security.input_validation import validate_command_arg
from ton.units import format_ton, ton_to_nanoton

log = get_logger(__name__)
router = Router(name="deposit")
_DEFAULT_TTL = 3600

def _status_icon(status: str) -> str:
    return {"pending":"⏳","detected":"👀","confirmed":"✅",
            "expired":"❌","underpaid":"⚠️","overpaid":"⚠️","late":"🕐"}.get(status,"❓")

@router.message(Command("deposit"))
async def cmd_deposit(message: Message) -> None:
    if not message.from_user:
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Usage: <code>/deposit AMOUNT_TON</code>\nExample: <code>/deposit 5</code>",
            parse_mode="HTML")
        return
    try:
        raw = validate_command_arg(args[1])
        amount_ton = Decimal(raw)
        if amount_ton <= 0:
            raise ValueError
        amount_nanotons = ton_to_nanoton(amount_ton)
    except (InvalidOperation, ValueError):
        await message.answer("Invalid amount — e.g. <code>/deposit 5</code>", parse_mode="HTML")
        return
    async with get_session() as session:
        svc = InvoiceService(session)
        try:
            invoice = await svc.create_invoice(
                telegram_id=message.from_user.id,
                amount_nanotons=amount_nanotons,
                ttl_seconds=_DEFAULT_TTL,
            )
        except InvoiceAmountInvalid as exc:
            await message.answer(str(exc))
            return
    ton_str = format_ton(invoice.amount_nanotons)
    expires = invoice.expires_at.strftime("%Y-%m-%d %H:%M UTC")
    await message.answer(
        f"💎 <b>Deposit Invoice</b>\n\n"
        f"Amount: <b>{ton_str} TON</b>\n"
        f"Send to:\n<code>{invoice.receiving_address}</code>\n\n"
        f"⚠️ <b>Required comment / memo:</b>\n"
        f"<code>{invoice.public_ref}</code>\n\n"
        f"Expires: {expires}\n\n"
        f"<i>You will be notified when payment is confirmed.</i>",
        parse_mode="HTML")

@router.message(Command("invoices"))
async def cmd_invoices(message: Message) -> None:
    if not message.from_user:
        return
    async with get_session() as session:
        invoices = await InvoiceService(session).list_invoices(message.from_user.id, limit=10)
    if not invoices:
        await message.answer(
            "No invoices yet.\nUse <code>/deposit AMOUNT</code> to create one.",
            parse_mode="HTML")
        return
    lines = [f"<b>Your invoices</b> (last {len(invoices)}):"]
    for inv in invoices:
        icon = _status_icon(inv.status)
        ton_str = format_ton(inv.amount_nanotons)
        exp = inv.expires_at.strftime("%m-%d %H:%M UTC")
        lines.append(
            f"\n{icon} <b>{ton_str} TON</b> — {inv.status}\n"
            f"  Ref: <code>{inv.public_ref[:12]}…</code>  Exp: {exp}")
    await message.answer("\n".join(lines), parse_mode="HTML")

@router.message(Command("invoice"))
async def cmd_invoice(message: Message) -> None:
    if not message.from_user:
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: <code>/invoice REF</code>", parse_mode="HTML")
        return
    ref = validate_command_arg(args[1])
    async with get_session() as session:
        svc = InvoiceService(session)
        try:
            inv = await svc.get_invoice(message.from_user.id, ref)
        except (InvoiceNotFound, InvoiceAuthorizationError):
            await message.answer("Invoice not found.")
            return
    icon = _status_icon(inv.status)
    ton_str = format_ton(inv.amount_nanotons)
    confirmed = inv.confirmed_at.strftime("%Y-%m-%d %H:%M UTC") if inv.confirmed_at else "—"
    tx_line = f"\nTX: <code>{inv.provider_tx_ref[:16]}…</code>" if inv.provider_tx_ref else ""
    await message.answer(
        f"<b>Invoice</b>\n\n"
        f"Ref: <code>{inv.public_ref}</code>\n"
        f"Amount: <b>{ton_str} TON</b>\n"
        f"Status: {icon} {inv.status}{tx_line}\n"
        f"Confirmed: {confirmed}\n"
        f"Expires: {inv.expires_at.strftime('%Y-%m-%d %H:%M UTC')}",
        parse_mode="HTML")
