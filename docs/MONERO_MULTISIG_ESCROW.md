# Monero multisig escrow integration

## Trust boundary and current status

Order escrow is internal-ledger by default. The optional XMR order path delegates
multisig wallet setup and signing to a separately deployed signer gateway. Kola
does not call participant wallet RPCs, store participant signing keys, or receive
signing material. The gateway must coordinate three independent participants
(buyer, vendor, mediator), enforce a 2-of-3 threshold, and require participant
authorization for every settlement proposal. A Kola service credential or
webhook HMAC must never authorize a spend.

The integration is **not production-ready without that independently operated
gateway**. No signer gateway or signer infrastructure is included in this
repository. Do not select Monero multisig in production until a gateway that
implements this contract has been deployed, threat-modeled, tested on stagenet,
and independently reviewed.

Monero does not provide native smart-contract time locks. This integration does
not implement a mediator silence deadline or automatic mediator spend. Order
deadlines may create a cancellation/refund proposal, but a spend remains subject
to the gateway's required signer approvals.

## Network configuration

Configure `MONERO_ESCROW_GATEWAY_URL` to the gateway HTTPS base URL and include
its exact hostname in `MONERO_ESCROW_GATEWAY_ALLOWED_HOSTS`. Set a random
`MONERO_ESCROW_GATEWAY_SECRET` of at least 32 characters in the deployment
secret store, `MONERO_ESCROW_CALLBACK_URL` to this site's HTTPS or configured
onion callback, and `MONERO_ESCROW_RELEASE_ADDRESS` to the platform's XMR
wallet address. Arbitrary participant-provided URLs are never accepted.

Kola signs outbound JSON requests with HMAC-SHA256 over:

```
timestamp + "." + nonce + "." + raw_request_body
```

Headers are `X-Kola-Timestamp`, `X-Kola-Nonce`, `X-Kola-Signature`, and
`Idempotency-Key`. The gateway signs callbacks with the same format and key.
Callbacks are rejected when their timestamp differs by more than five minutes.
Event IDs and per-escrow sequence numbers provide replay/idempotency protection.

## Version 1 gateway API contract

All JSON amounts are integer atomic XMR units or integer base units. The gateway
must reject unknown protocol versions and must treat Kola's request signature
only as service authentication, never as buyer, vendor, or mediator approval.

### Create multisig escrow

`POST /v1/escrows` receives:

```json
{
  "protocol_version": 1,
  "order_id": 123,
  "buyer_id": 456,
  "vendor_user_id": 789,
  "amount_base_units": 100000000,
  "release_address": "<platform XMR address>",
  "callback_url": "https://market.example/payments/monero-escrow/events/",
  "signing_policy": {
    "participants": ["buyer", "vendor", "mediator"],
    "threshold": 2,
    "mediator_alone_must_not_sign": true,
    "participant_authorization_required_for_settlement": true
  }
}
```

Return `{"escrow_id":"<opaque-id>"}`. The gateway independently authenticates
each participant and coordinates Monero wallet-RPC multisig setup. Once ready,
it sends a signed `ready` event with the escrow ID, order ID, event ID, sequence,
and multisig address. Kola creates a fresh XMR/base quote and returns the
required `amount_atomic`, locked `base_units_per_coin`, and quote expiry in its
callback response. The gateway must not accept funding until it receives those
terms.

The gateway may use Monero wallet-RPC multisig operations such as
`prepare_multisig`, `make_multisig`, `exchange_multisig_keys`,
`export_multisig_info`, and `import_multisig_info` for wallet setup. Signing and
submission must remain participant-authorized; Kola does not proxy those RPC
methods. Refer to the [official Monero wallet-RPC documentation](https://docs.getmonero.org/rpc-library/wallet-rpc/).

### Funding and settlement callbacks

The gateway sends monotonically sequenced signed callbacks:

- `ready`: `data.address`.
- `funded`: `data.transaction_id`, `data.amount_atomic`,
  `data.confirmations`. Kola only funds the order when the locked quote remains
  valid and the configured XMR confirmation threshold is met.
- `settled`: `data.action` (`release`, `refund`, or `partial`),
  `data.transaction_id`, `data.amount_atomic` received by the platform address,
  and `data.confirmations`. Kola credits the vendor's internal ledger balance
  net of the 3% commission, or credits the buyer for the refunded portion. It
  does not accept a settlement unless the received XMR covers the original
  order total at the locked rate; insufficient/ambiguous results enter operator
  review rather than creating underfunded ledger credits.
- `cancelled`: `data.no_funds` must be `true`; only then may a pending, unfunded
  order be cancelled or expired.
- `failed`: moves the escrow into operator review; it does not fabricate a
  successful order or settlement.

The callback route returns `amount_atomic`, `base_units_per_coin`, and
`quote_expires_at` after accepting `ready`; the gateway must use the exact
returned terms. Duplicate event IDs are accepted idempotently. A new event must
use `last_sequence + 1`.

### Settlement proposal and cancellation

`POST /v1/escrows/{escrow_id}/settlements` carries `action`,
`release_base_units`, and `order_id`. It must create a proposal and return
`{"status":"pending_participant_approval"}`. It must not sign or broadcast until
two distinct authorized participants approve. The eventual signed `settled`
callback is the only signal that lets Kola post corresponding ledger credits.

`POST /v1/escrows/{escrow_id}/cancel` carries `order_id` and a reason
(`buyer` or `deadline`). The gateway returns `cancel_pending` or
`refund_required`; it must send `cancelled` only after verifying that no funds
are held. If funds exist, it must report/confirm funding and require an
approval-gated refund settlement. Kola never treats a timeout as proof that an
escrow is empty.

## Accounting behavior

- The quote is set only when the independent gateway reports that multisig
  setup is ready; expected atomic amount is rounded up using integer arithmetic.
- A confirmed funding event moves the order from draft to funded; it does not
  create a ledger credit.
- A confirmed release credits 97% (subject to the shared integer 3% ceiling
  commission) to the vendor's `vendor_available` account and the commission to
  `market_fee`. A confirmed refund credits the buyer's `user_available` balance
  without a commission. Partial outcomes split the original base total between
  these cases.
- The gateway must send the settlement output to the configured platform XMR
  address. Kola bears network fees; outputs that fail to cover the full base
  amount enter review and are not posted as successful ledger credits.

## Operator validation checklist

Before enabling the XMR multisig option:

1. Deploy independent buyer, vendor, and mediator signer infrastructure that
   implements this API and independently authenticates each participant.
2. Verify no Kola-only credential or gateway compromise can create two
   participant approvals.
3. Run wallet setup, funding, refund, release, partial settlement, cancellation,
   replay, stale quote, RPC outage, and worker-retry cases on stagenet.
4. Verify the gateway's reported transaction amount and confirmations against
   the Monero chain and reconcile the platform wallet/reserve after settlement.
5. Threat-model signer recovery, dispute evidence handling, key rotation,
   participant lockout, and service compromise. The current integration does
   not implement those gateway-side controls.
