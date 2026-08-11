-- Capture the shipping address Stripe collects at checkout so orders can
-- actually be fulfilled from the admin panel. Before this, `orders` held
-- only session id, product, amount, currency and email — nothing you could
-- put on a label.

alter table orders add column if not exists customer_name text;
alter table orders add column if not exists customer_phone text;
alter table orders add column if not exists shipping_name text;
alter table orders add column if not exists shipping_line1 text;
alter table orders add column if not exists shipping_line2 text;
alter table orders add column if not exists shipping_city text;
alter table orders add column if not exists shipping_state text;
alter table orders add column if not exists shipping_postal_code text;
alter table orders add column if not exists shipping_country text;

-- Fulfilment tracking, so the owner can tell at a glance what still needs
-- to go out the door.
alter table orders add column if not exists shipped boolean not null default false;
alter table orders add column if not exists shipped_at timestamptz;
alter table orders add column if not exists tracking_number text;

-- Orders were read-only for the admin (insert stays service_role-only so
-- nothing client-side can fake a sale). Marking an order shipped is an
-- update, so the admin needs that grant.
drop policy if exists "admin update orders" on orders;
create policy "admin update orders" on orders for update using (auth.role() = 'authenticated');
