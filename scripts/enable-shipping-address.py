#!/usr/bin/env python3
"""
Turn on shipping address collection for every Stripe Payment Link.

Shipping is priced into the products themselves (free shipping at checkout),
so no shipping *rates* are attached here — this only makes Stripe ask the
buyer where to send the order. Without it, checkout.session.completed
arrives with no address and the Orders tab in admin.html has nothing to
show.

Re-run this whenever new products (and therefore new payment links) are
added; links that are already configured are skipped.

Usage:
    export STRIPE_SECRET_KEY=sk_live_...      # your key, never stored here
    python3 scripts/enable-shipping-address.py            # dry run
    python3 scripts/enable-shipping-address.py --apply    # make changes

The key is read from the environment and only ever sent to api.stripe.com.
"""

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.stripe.com/v1"


def ssl_context():
    """The python.org macOS build ships without wired-up CA certificates
    unless "Install Certificates.command" was ever run, so a plain HTTPS
    call dies with CERTIFICATE_VERIFY_FAILED. Prefer certifi's bundle when
    it is importable and fall back to the system default."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CONTEXT = ssl_context()

# Where he is willing to ship. Free shipping is baked into the product
# prices at US domestic rates, so opening this up to other countries would
# mean eating the difference on every international order. Add codes here
# only if the prices can absorb it.
ALLOWED_COUNTRIES = ["US"]


def request(method, path, key, params=None):
    url = f"{API}{path}"
    data = None
    if params:
        data = urllib.parse.urlencode(params, doseq=True).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Stripe-Version", "2023-10-16")
    if data:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, context=SSL_CONTEXT) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            message = json.loads(body)["error"]["message"]
        except Exception:
            message = body[:300]
        if e.code == 401:
            raise SystemExit(
                "Stripe rejected the key (401). Check that STRIPE_SECRET_KEY is a "
                "current secret key from Dashboard > Developers > API keys."
            )
        raise SystemExit(f"Stripe API error ({e.code}) on {method} {path}: {message}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Could not reach Stripe: {e.reason}")


def all_payment_links(key):
    """Page through every payment link on the account."""
    links, starting_after = [], None
    while True:
        query = {"limit": 100}
        if starting_after:
            query["starting_after"] = starting_after
        page = request("GET", "/payment_links?" + urllib.parse.urlencode(query), key)
        links.extend(page["data"])
        if not page.get("has_more"):
            return links
        starting_after = page["data"][-1]["id"]


def needs_update(link):
    current = link.get("shipping_address_collection")
    if not current:
        return True
    return sorted(current.get("allowed_countries", [])) != sorted(ALLOWED_COUNTRIES)


def main():
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise SystemExit(
            "STRIPE_SECRET_KEY is not set.\n"
            "Run:  export STRIPE_SECRET_KEY=sk_live_...   then re-run this script."
        )
    if not key.startswith("sk_"):
        raise SystemExit("That does not look like a Stripe secret key (expected sk_...).")

    apply_changes = "--apply" in sys.argv
    mode = "APPLY" if apply_changes else "DRY RUN"
    live = key.startswith("sk_live_")
    print(f"[{mode}] {'LIVE' if live else 'TEST'} mode, shipping to {', '.join(ALLOWED_COUNTRIES)}\n")

    links = all_payment_links(key)
    active = [l for l in links if l.get("active")]
    todo = [l for l in active if needs_update(l)]

    print(f"{len(links)} payment links ({len(active)} active)")
    print(f"{len(active) - len(todo)} already collect the right address")
    print(f"{len(todo)} to update\n")

    if not todo:
        print("Nothing to do.")
        return

    if not apply_changes:
        for link in todo[:10]:
            print(f"  would update {link['id']}  {link.get('url', '')}")
        if len(todo) > 10:
            print(f"  ... and {len(todo) - 10} more")
        print("\nRe-run with --apply to make these changes.")
        return

    updated = 0
    for i, link in enumerate(todo, 1):
        request(
            "POST",
            f"/payment_links/{link['id']}",
            key,
            {"shipping_address_collection[allowed_countries][]": ALLOWED_COUNTRIES},
        )
        updated += 1
        print(f"  [{i}/{len(todo)}] {link['id']} updated")

    print(f"\nDone. {updated} payment links now collect a shipping address.")
    print("Existing orders are unaffected — only new checkouts will have addresses.")


if __name__ == "__main__":
    main()
