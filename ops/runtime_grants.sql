-- psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -v runtime_role=growth_web -f ops/runtime_grants.sql
-- The named login must already exist and must not own the schema or bypass RLS.
grant usage on schema growth to :"runtime_role";
grant select on all tables in schema growth to :"runtime_role";
grant insert on growth.shops,growth.members,growth.products,growth.faqs,growth.connections,
    growth.chats,growth.events,growth.topics,growth.orders,growth.files,growth.receipts,
    growth.journal,growth.visuals,growth.invoices,growth.invites,growth.notes to :"runtime_role";
grant update(name,language,profile,paid_until) on growth.shops to :"runtime_role";
grant update(name,price,details) on growth.products to :"runtime_role";
grant update(question,answer,language) on growth.faqs to :"runtime_role";
grant update(paused,summary,updated_at) on growth.chats to :"runtime_role";
grant update(enabled) on growth.connections to :"runtime_role";
grant update(count) on growth.topics to :"runtime_role";
grant update(paid_at,provider_ref) on growth.invoices to :"runtime_role";
grant delete on growth.invites,growth.members to :"runtime_role";

grant execute on function growth.record_site_visit(date,text) to :"runtime_role";
revoke all on growth.site_visitors,growth.developer_statistics,growth.analytics_daily from :"runtime_role";
