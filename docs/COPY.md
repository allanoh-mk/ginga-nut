# Interface copy

Use short, factual labels. State amounts and order states exactly. Use “balance” for funds held inside Kola Market. “Wallet” refers only to an external crypto wallet or a linked address. Never write “connect wallet.”

## Button labels

- Create account
- Sign in
- Verify signature
- Save changes
- Save listing
- Search listings
- Place order
- Fund order
- Confirm delivery
- Open dispute
- Submit evidence
- Submit review
- Request deposit address
- Request withdrawal
- Add payout address
- Verify address
- Link address
- Unlink address
- Mark all as read
- Approve withdrawal
- Reject withdrawal
- Pause new orders
- Resume new orders
- Pause withdrawals
- Resume withdrawals
- Submit vendor application
- Add bond
- Save pack photo and mark packed
- Accept order
- Reject order
- Dispatch order
- Approve vendor
- Approve maker
- Publish ruling
- Pause feature
- Resume feature

## Error strings

1. **Sign-in details are incorrect. Try again.**
2. **The signature is invalid or expired. Request a new challenge and sign it again.**
3. **This recovery code has already been used. Use another unused code.**
4. **The listing is no longer available. Choose another listing.**
5. **There is not enough stock for this quantity. Reduce the quantity and try again.**
6. **The balance is too low to fund this order. Add funds, then try again.**
7. **The delivery zone does not match this listing. Select the listed zone.**
8. **The delivery confirmation has expired or was already used. Ask the vendor for a new code.**
9. **This order cannot be changed from its current state. Reload the order and review its status.**
10. **The payout address is not verified or is still locked. Verify the address and wait until the lock ends.**
11. **The withdrawal could not be sent. The reserved amount remains on hold while the send is checked.**
12. **The provider could not confirm this deposit. Check the transaction status before trying again.**
13. **Available balance is too low for this bond amount. Add funds and try again.**
14. **Add a pack photo before dispatching this order.**
15. **A published reason of 1 to 2000 characters is required. Enter the reason and publish the ruling.**

## Empty states

- **Order history:** Orders will appear here after an order is placed. Browse listings to place an order.
- **Deposits:** Deposit addresses will appear here when requested. Request an address to add funds.
- **Deposit history:** Deposits will appear here after a transaction is detected. Send funds to a requested deposit address.
- **Withdrawals:** Withdrawal requests will appear here after submission. Request a withdrawal from your available balance.
- **Payout addresses:** Saved addresses will appear here after one is added. Add an address to request a withdrawal.
- **Linked addresses:** Linked addresses will appear here after ownership is verified. Sign a one-time message to link an address.
- **Notifications:** Notifications will appear here when an order, dispute, withdrawal, or vendor application changes. Use the marketplace to create activity.
- **Reviews:** Reviews will appear here after a buyer reviews a finalized order. Complete an order to leave a review.
- **Vendor order queue:** Orders will appear here after a buyer funds one. Publish an active listing so buyers can order.
- **Vendor payouts:** Payout requests will appear here after you request a withdrawal. Request a withdrawal from your balance.
- **Vendor applications:** Applications will appear here after a seller submits a profile. Submit a vendor application to start review.
- **Maker applications:** Maker applications will appear here after submission. Submit an application to start review.

## Balance strip

**Available balance**  `{{ amount }} base units`  ·  **Held for orders**  `{{ held_amount }} base units`

## Paused-feature strings

- **New orders are paused. Existing orders remain available.**
- **Withdrawals are paused. Requests and sends will resume when withdrawals are enabled.**
- **Digital listings are unavailable. Physical listings can still be browsed and ordered.**

## Error and paused pages

- **Request not accepted:** The request could not be read. Check the submitted fields and send it again.
- **Access denied:** This account cannot open that page. Sign in with an account that has access or return to the marketplace.
- **Page not found:** This address does not match a page. Check the address or return to the marketplace.
- **Service error:** The server could not complete this request. Return to the marketplace and try again.
- **New orders are paused:** Existing orders remain available. New orders will be accepted when the service resumes.
- **Withdrawals are paused:** Requests and sends will resume when withdrawals are enabled. Existing requests remain available in your history.
- **Digital listings are unavailable:** Digital fulfillment is not supported. Physical listings can still be browsed and ordered.
