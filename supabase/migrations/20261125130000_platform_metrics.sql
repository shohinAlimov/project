-- Private aggregates for developers, outside every business workspace.
create table growth.site_visitors (
 day date not null,
 visitor_hash text not null check(length(visitor_hash)=64),
 views bigint not null default 1 check(views>0),
 primary key(day,visitor_hash)
);
alter table growth.site_visitors enable row level security;
revoke all on growth.site_visitors from public;

create function growth.record_site_visit(p_day date,p_visitor text)
returns void language sql security definer set search_path='' as $$
 insert into growth.site_visitors(day,visitor_hash) values(p_day,p_visitor)
 on conflict(day,visitor_hash) do update set views=growth.site_visitors.views+1;
$$;
revoke all on function growth.record_site_visit(date,text) from public;

create view growth.developer_statistics as
with visits as (
 select day,count(*) as daily_browsers,sum(views) as page_views
 from growth.site_visitors group by day
), signups as (
 select (created_at at time zone 'Asia/Dushanbe')::date as day,
 count(*) as registrations,
 count(*) filter(where email_confirmed_at is not null) as confirmed_registrations
 from auth.users group by 1
)
select coalesce(v.day,s.day) as day,
 coalesce(v.daily_browsers,0) as daily_browsers,
 coalesce(v.page_views,0) as page_views,
 coalesce(s.registrations,0) as registrations,
 coalesce(s.confirmed_registrations,0) as confirmed_registrations
from visits v full join signups s using(day);
revoke all on growth.developer_statistics from public;
-- Disable superseded workspace counters without deleting historical rows.
do $migration$ begin
 if exists(select from pg_roles where rolname='growth_web') then
 revoke select,insert,update on growth.analytics_daily from growth_web;
 end if;
end $migration$;
