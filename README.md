# Sombra TON Guardian

Read-only TON watchlist bot with a payment invoice MVP.

## Setup

```bash
cp .env.example .env
# Edit .env — fill in all required values (see below)
```

Required env vars:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host/db` |
| `TONAPI_API_KEY` | From tonconsole.com |
| `PAYMENT_RECEIVING_ADDRESS` | TON address to receive payments (bounceable base64url) |

## Database

```bash
# Run migrations
alembic upgrade head
```

## Run

```bash
python -m app.main
```

Or via Docker:

```bash
docker compose up
```

## Payment MVP

### How it works

1. User runs `/invoice 1.5` — creates a 1.5 TON invoice with a UUID reference.
2. Bot displays the receiving address and instructs the payer to include the invoice
   reference as the TON transfer comment/memo.
3. The payment monitor polls `PAYMENT_RECEIVING_ADDRESS` every
   `PAYMENT_POLL_INTERVAL_SECONDS` seconds using TonAPI.
4. When a finalized transfer arrives whose comment matches an invoice's public_ref,
   the invoice is transitioned to `confirmed`, `underpaid`, or `overpaid`.
5. The invoice owner receives a Telegram notification.

### Correlation strategy

A single receiving address is used for all invoices. Payments are correlated to
invoices via the **TON transfer comment/memo** field. The payer must include the
invoice `public_ref` (UUID4) verbatim as the comment. Payments with no comment
or a comment matching no live invoice are logged and ignored — never falsely
matched.

### Commands

| Command | Description |
|---|---|
| `/invoice AMOUNT [TTL]` | Create an invoice (amount in TON, TTL in seconds) |
| `/invoicestatus REF` | Check invoice status |
| `/invoices` | List your recent invoices |

### Invoice statuses

| Status | Meaning |
|---|---|
| `pending` | Awaiting payment |
| `detected` | Transfer seen on-chain (intermediate) |
| `confirmed` | Exact amount received and finalized |
| `underpaid` | Less than expected received |
| `overpaid` | More than expected received |
| `expired` | Not paid before expiry |
| `late` | Payment arrived after expiry |

## Architecture

- **`database/invoice_repository.py`** — SQL for invoice_payments table
- **`database/invoice_service.py`** — business logic, state machine
- **`workers/payment_monitor.py`** — background poll → match → notify
- **`handlers/invoice.py`** — Telegram commands
- **`alembic/versions/0003_*`** — adds `receiving_address` column

## Blockers for full Mainnet operation

1. `PAYMENT_RECEIVING_ADDRESS` must be set to a real TON address you control.
2. `TONAPI_API_KEY` must be a valid key from tonconsole.com.
3. PostgreSQL must be reachable at `DATABASE_URL`.
4. `alembic upgrade head` must complete (migrations 0001–0003).