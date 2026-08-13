#!/usr/bin/env python3
"""
Get every Stripe Payment Link ready to take real orders.

Two things per link:

1. Collect a shipping address. Shipping is priced into the products, so no
   shipping *rates* are attached — this only makes Stripe ask the buyer
   where to send the order. Without it checkout.session.completed arrives
   with no address at all and the Orders tab has nothing to show.

2. Stop one-of-a-kind items selling twice. Almost every listing is a
   single vintage piece, but `sold_out` in the admin is a manual checkbox
   and a Payment Link will happily take payment over and over. Capping the
   link at one completed payment makes Stripe deactivate it after the sale,
   so a second buyer cannot be charged for a shirt that is already gone.

   Listings with more than one size, and links shared by more than one
   product, are left uncapped — those can legitimately sell more than once.
   Sizes come from the public products table.

Usage:
    export STRIPE_SECRET_KEY=sk_live_...      # your key, never stored here
    python3 scripts/prepare-payment-links.py            # dry run
    python3 scripts/prepare-payment-links.py --apply    # make changes

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

# Public anon key and project URL, same pair the storefront ships with.
SUPABASE_URL = "https://timslscyvprxyxykhwcb.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_aXXWey_7o5ogT2rNgOw03g_6tiVv28y"

# Where he is willing to ship. Free shipping is baked into the product
# prices at US domestic rates, so opening this up to other countries would
# mean eating the difference on every international order.
ALLOWED_COUNTRIES = ["US"]


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


def request(method, url, headers=None, params=None, fatal=True):
    data = urllib.parse.urlencode(params, doseq=True).encode() if params else None
    req = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
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
        if e.code == 401 and "stripe.com" in url:
            raise SystemExit(
                "Stripe rejected the key (401). Check that STRIPE_SECRET_KEY is a "
                "current secret key from Dashboard > Developers > API keys."
            )
        if not fatal:
            # One link failing should not abandon the other hundred.
            return {"_error": f"{e.code}: {message}"}
        raise SystemExit(f"API error ({e.code}) on {method} {url}: {message}")
    except urllib.error.URLError as e:
        if not fatal:
            return {"_error": str(e.reason)}
        raise SystemExit(f"Could not reach {urllib.parse.urlparse(url).netloc}: {e.reason}")


def stripe(method, path, key, params=None, fatal=True):
    return request(
        method,
        f"{API}{path}",
        headers={"Authorization": f"Bearer {key}", "Stripe-Version": "2023-10-16"},
        params=params,
        fatal=fatal,
    )


def all_payment_links(key):
    """Page through every payment link on the account."""
    links, starting_after = [], None
    while True:
        query = {"limit": 100}
        if starting_after:
            query["starting_after"] = starting_after
        page = stripe("GET", "/payment_links?" + urllib.parse.urlencode(query), key)
        links.extend(page["data"])
        if not page.get("has_more"):
            return links
        starting_after = page["data"][-1]["id"]


def load_products():
    """Map payment link URL -> the products using it, so we know which
    listings are one-of-a-kind and which links are shared."""
    url = f"{SUPABASE_URL}/rest/v1/products?select=id,name,size,stripe_link"
    rows = request("GET", url, headers={"apikey": SUPABASE_ANON_KEY})
    by_link = {}
    for row in rows:
        if row.get("stripe_link"):
            by_link.setdefault(row["stripe_link"].strip(), []).append(row)
    return by_link


def is_one_of_a_kind(products):
    """One product, one size — capping the link at a single sale is safe."""
    if len(products) != 1:
        return False
    size = (products[0].get("size") or "").strip()
    return "," not in size


def main():
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise SystemExit(
            "STRIPE_SECRET_KEY is not set.\n"
            "Run:  export STRIPE_SECRET_KEY=sk_live_...   then re-run this script."
        )
    # Stripe keeps adding key formats (sk_, rk_, and newer prefixes), so an
    # allowlist here just blocks valid keys. Note anything unfamiliar and let
    # Stripe be the judge — a bad key comes back as a clean 401 anyway.
    if not key.startswith(("sk_", "rk_")):
        print(f"Note: key starts '{key.split('_')[0]}_' ({len(key)} chars), which is not a "
              "prefix this script knows. Letting Stripe decide.\n")

    apply_changes = "--apply" in sys.argv
    print(f"[{'APPLY' if apply_changes else 'DRY RUN'}] "
          f"{'LIVE' if key.startswith('sk_live_') else 'TEST'} mode, "
          f"shipping to {', '.join(ALLOWED_COUNTRIES)}\n")

    by_link = load_products()
    links = all_payment_links(key)
    active = [l for l in links if l.get("active")]

    planned, skipped_shared, unmatched = [], [], []
    for link in active:
        products = by_link.get(link.get("url", "").strip(), [])
        changes = {}

        current = link.get("shipping_address_collection") or {}
        if sorted(current.get("allowed_countries", [])) != sorted(ALLOWED_COUNTRIES):
            changes["shipping_address_collection[allowed_countries][]"] = ALLOWED_COUNTRIES

        if not products:
            # A link with no product pointing at it — still worth collecting
            # an address, but we cannot judge whether it is a one-off.
            unmatched.append(link)
        elif len(products) > 1:
            skipped_shared.append((link, products))
        elif is_one_of_a_kind(products):
            existing = (link.get("restrictions") or {}).get("completed_sessions", {})
            if existing.get("limit") != 1:
                changes["restrictions[completed_sessions][limit]"] = 1

        if changes:
            planned.append((link, products, changes))

    print(f"{len(links)} payment links ({len(active)} active)")
    print(f"{len(planned)} need changes")
    if skipped_shared:
        print(f"\n{len(skipped_shared)} link(s) shared by more than one product — "
              "left uncapped, fix these in the admin:")
        for link, products in skipped_shared:
            print(f"  {link.get('url')}")
            for p in products:
                print(f"     id {p['id']}  {p['name'][:58]}")
    if unmatched:
        print(f"\n{len(unmatched)} active link(s) match no product — address collection "
              "only, no sale cap applied.")

    if not planned:
        print("\nNothing to do.")
        return

    caps = sum(1 for _, _, c in planned if "restrictions[completed_sessions][limit]" in c)
    addrs = sum(1 for _, _, c in planned if "shipping_address_collection[allowed_countries][]" in c)
    print(f"\n  {addrs} link(s) to start collecting an address")
    print(f"  {caps} one-of-a-kind link(s) to cap at a single sale")

    if not apply_changes:
        print("\nRe-run with --apply to make these changes.")
        return

    print()
    updated, failed = 0, []
    for i, (link, products, changes) in enumerate(planned, 1):
        result = stripe("POST", f"/payment_links/{link['id']}", key, changes, fatal=False)
        label = products[0]["name"][:44] if products else link.get("url", "")
        if "_error" in result:
            failed.append((link, label, result["_error"]))
            print(f"  [{i}/{len(planned)}] FAILED {link['id']}  {label}  -> {result['_error']}")
        else:
            updated += 1
            print(f"  [{i}/{len(planned)}] {link['id']}  {label}")

    print(f"\nDone. {updated} updated, {len(failed)} failed.")
    if failed:
        print("Failures are usually a link that has already been paid more times "
              "than the cap allows — check those in the Stripe Dashboard.")
    print("Existing orders are unaffected; only new checkouts change.")


if __name__ == "__main__":
    main()
