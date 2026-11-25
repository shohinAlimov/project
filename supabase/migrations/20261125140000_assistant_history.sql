create table growth.assistant_turns (
 business_id uuid not null references growth.shops(id) on delete cascade,
 subject uuid not null,
 role text not null check(role in ('owner','finance','marketing')),
 request_id uuid not null,
 question text not null,
 answer text not null,
 source text not null check(source in ('ai','records')),
 created_at timestamptz not null default now(),
 primary key(business_id,subject,role,request_id)
);
create index assistant_recent on growth.assistant_turns(business_id,subject,role,created_at desc);
alter table growth.assistant_turns enable row level security;
alter table growth.assistant_turns force row level security;
create policy personal_scope on growth.assistant_turns
 using(business_id=growth.scope() and subject=nullif(current_setting('growth.subject',true),'')::uuid)
 with check(business_id=growth.scope() and subject=nullif(current_setting('growth.subject',true),'')::uuid);
