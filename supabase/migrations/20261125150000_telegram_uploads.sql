create table growth.telegram_upload_links (
 business_id uuid not null,
 subject uuid not null,
 token_hash text not null unique,
 expires timestamptz not null,
 telegram_id bigint unique,
 primary key(business_id,subject),
 foreign key(business_id,subject) references growth.members(business_id,subject) on delete cascade
);
alter table growth.telegram_upload_links enable row level security;
alter table growth.telegram_upload_links force row level security;
create policy scoped_link on growth.telegram_upload_links using (
 (business_id=growth.scope() and subject=nullif(current_setting('growth.subject',true),'')::uuid)
 or token_hash=current_setting('growth.telegram_claim',true)
 or telegram_id=nullif(current_setting('growth.telegram_sender',true),'')::bigint
) with check (
 (business_id=growth.scope() and subject=nullif(current_setting('growth.subject',true),'')::uuid)
 or token_hash=current_setting('growth.telegram_claim',true)
);
