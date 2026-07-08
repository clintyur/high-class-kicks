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

-- ============ ROW LEVEL SECURITY ============

alter table products enable row level security;
alter table settings enable row level security;
alter table visits enable row level security;

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
