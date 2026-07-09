-- ============ TABLES ============

create table products (
  id bigint generated always as identity primary key,
  name text not null,
  sub text,
  price numeric not null,
  size text,
  category text not null,
  badge text,
  sold_out boolean default false,
  image text,
  description text,
  stripe_link text,
  sort_order int default 0,
  created_at timestamptz default now()
);

create table settings (
  id bigint primary key,
  data jsonb not null
);

create table visits (
  id bigint generated always as identity primary key,
  created_at timestamptz default now()
);

create table signups (
  id bigint generated always as identity primary key,
  phone text not null,
  created_at timestamptz default now()
);

-- Written only by the stripe-webhook Edge Function using the service_role
-- key, which bypasses RLS entirely — so there is no insert policy here on
-- purpose. Nothing client-side (anon or authenticated) can create fake orders.
create table orders (
  id bigint generated always as identity primary key,
  stripe_session_id text unique,
  product_name text,
  amount numeric,
  currency text default 'usd',
  customer_email text,
  created_at timestamptz default now()
);

-- ============ ROW LEVEL SECURITY ============

alter table products enable row level security;
alter table settings enable row level security;
alter table visits enable row level security;
alter table signups enable row level security;
alter table orders enable row level security;

-- products: public read, logged-in admin write
create policy "public read products" on products for select using (true);
create policy "admin insert products" on products for insert with check (auth.role() = 'authenticated');
create policy "admin update products" on products for update using (auth.role() = 'authenticated');
create policy "admin delete products" on products for delete using (auth.role() = 'authenticated');

-- settings: public read, logged-in admin write
create policy "public read settings" on settings for select using (true);
create policy "admin insert settings" on settings for insert with check (auth.role() = 'authenticated');
create policy "admin update settings" on settings for update using (auth.role() = 'authenticated');

-- visits: anyone can log a visit, only the admin can read the stats
create policy "public insert visits" on visits for insert with check (true);
create policy "admin read visits" on visits for select using (auth.role() = 'authenticated');

-- signups: anyone can submit their phone number, only the admin can read the list
create policy "public insert signups" on signups for insert with check (true);
create policy "admin read signups" on signups for select using (auth.role() = 'authenticated');

-- orders: admin-only read. No insert policy — only the service_role key
-- (used server-side by the stripe-webhook Edge Function) can write here.
create policy "admin read orders" on orders for select using (auth.role() = 'authenticated');
