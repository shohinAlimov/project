alter function growth.scope() set search_path = pg_catalog;
create index journal_by_day on growth.journal(business_id, day desc);
create index journal_by_order on growth.journal(business_id, order_id) where order_id is not null;
create index visuals_by_month on growth.visuals(business_id, month);
create index chats_by_update on growth.chats(business_id, updated_at desc);
do $$ begin
 if exists(select 1 from pg_roles where rolname='growth_web') then
 grant update(question,language) on growth.faqs to growth_web;
 end if;
end $$;
