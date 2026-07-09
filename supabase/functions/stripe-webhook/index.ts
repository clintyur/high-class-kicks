// Supabase Edge Function: receives Stripe webhooks and records completed
// checkouts in the `orders` table automatically.
//
// Deploy with: supabase functions deploy stripe-webhook --no-verify-jwt
// (--no-verify-jwt is required because Stripe calls this directly with its
// own signature, not a Supabase auth JWT.)
//
// Required secrets (set with `supabase secrets set KEY=value`):
//   STRIPE_SECRET_KEY     - from Stripe Dashboard > Developers > API keys
//   STRIPE_WEBHOOK_SECRET - generated when you add the webhook endpoint in
//                           Stripe Dashboard > Developers > Webhooks
//
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are provided automatically by
// the Supabase Edge Functions runtime — no need to set those yourself.

import Stripe from 'https://esm.sh/stripe@14?target=deno';

const stripe = new Stripe(Deno.env.get('STRIPE_SECRET_KEY')!, {
  apiVersion: '2023-10-16',
  httpClient: Stripe.createFetchHttpClient(),
});

const webhookSecret = Deno.env.get('STRIPE_WEBHOOK_SECRET')!;
const supabaseUrl = Deno.env.get('SUPABASE_URL')!;
const serviceRoleKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;

Deno.serve(async (req) => {
  const signature = req.headers.get('stripe-signature');
  const body = await req.text();

  let event;
  try {
    event = await stripe.webhooks.constructEventAsync(body, signature!, webhookSecret);
  } catch (err) {
    console.error('Signature verification failed:', err.message);
    return new Response(`Webhook signature verification failed: ${err.message}`, { status: 400 });
  }

  if (event.type === 'checkout.session.completed') {
    const session = event.data.object;

    let productName = 'Unknown product';
    try {
      const lineItems = await stripe.checkout.sessions.listLineItems(session.id, { limit: 10 });
      productName = lineItems.data.map((li) => li.description).filter(Boolean).join(', ') || productName;
    } catch (err) {
      console.error('Could not fetch line items:', err.message);
    }

    const res = await fetch(
      `${supabaseUrl}/rest/v1/orders?on_conflict=stripe_session_id`,
      {
        method: 'POST',
        headers: {
          apikey: serviceRoleKey,
          Authorization: `Bearer ${serviceRoleKey}`,
          'Content-Type': 'application/json',
          Prefer: 'resolution=ignore-duplicates,return=minimal',
        },
        body: JSON.stringify({
          stripe_session_id: session.id,
          product_name: productName,
          amount: (session.amount_total || 0) / 100,
          currency: session.currency,
          customer_email: session.customer_details?.email || null,
        }),
      }
    );

    if (!res.ok) {
      const text = await res.text();
      console.error('Failed to insert order:', text);
      return new Response('Failed to record order', { status: 500 });
    }
  }

  return new Response(JSON.stringify({ received: true }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
});
