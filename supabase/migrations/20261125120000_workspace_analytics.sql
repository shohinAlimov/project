create table growth.analytics_daily (
 business_id uuid not null references growth.shops(id) on delete cascade,
 day date not null default (now() at time zone 'Asia/Tashkent')::date,
 event text not null check(event in ('page_view','product_saved','assistant_used','order_created','entry_recorded','visual_created')),
 count bigint not null default 1 check(count > 0),
 primary key(business_id,day,event)
);
alter table growth.analytics_daily enable row level security;
alter table growth.analytics_daily force row level security;
create policy scoped on growth.analytics_daily using (business_id=growth.scope()) with check (business_id=growth.scope());
