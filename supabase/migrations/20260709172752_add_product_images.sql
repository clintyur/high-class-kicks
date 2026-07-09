alter table products add column if not exists images jsonb default '[]'::jsonb;
