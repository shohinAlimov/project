-- Private server-only workspace. The web API sets transaction-local scope after authentication.
create schema growth;
revoke all on schema growth from public;
create function growth.scope() returns uuid language sql stable as $$
  select nullif(current_setting('growth.business',true),'')::uuid
$$;
create table growth.shops (
 id uuid primary key default gen_random_uuid(), name text not null,
 language text not null check(language in ('uz','ru')), profile jsonb not null default '{}',
 demo boolean not null default false, paid_until timestamptz, created_at timestamptz default now()
);
create table growth.members (
 business_id uuid references growth.shops on delete cascade, subject uuid not null,
 role text not null check(role in ('owner','finance','marketing')), primary key(business_id,subject)
);
create unique index one_owned_shop on growth.members(subject) where role='owner';
create table growth.products (
 id uuid primary key default gen_random_uuid(), business_id uuid not null references growth.shops,
 name text not null, price bigint not null check(price>=0), details jsonb not null default '{}',
 unique(business_id,id)
);
create table growth.faqs (
 id uuid primary key default gen_random_uuid(), business_id uuid not null references growth.shops,
 question text not null, answer text not null, language text not null check(language in ('uz','ru')),
 unique(business_id,language,question)
);
-- Connections are provisioned by an operator who has verified both sides.
create table growth.connections (
 connection text primary key, business_id uuid not null references growth.shops,
 telegram_owner bigint not null, enabled boolean not null default true
);
create table growth.chats (
 id uuid primary key default gen_random_uuid(), business_id uuid not null references growth.shops,
 connection text not null, chat bigint not null, paused boolean not null default false,
 summary text not null default '', updated_at timestamptz default now(), unique(business_id,connection,chat)
);
create table growth.events (
 business_id uuid references growth.shops, connection text not null, chat bigint not null,
 message_id bigint not null, received_at timestamptz default now(), primary key(business_id,connection,chat,message_id)
);
create table growth.topics (
 business_id uuid references growth.shops, topic text not null, product text not null default '',
 count bigint not null default 1, primary key(business_id,topic,product)
);
create table growth.orders (
 id uuid primary key default gen_random_uuid(), business_id uuid not null references growth.shops,
 product_id uuid not null, customer text not null, total bigint not null check(total>0), due date,
 unique(business_id,id), foreign key(business_id,product_id) references growth.products(business_id,id)
);
create table growth.files (
 id uuid primary key default gen_random_uuid(), business_id uuid not null references growth.shops,
 digest text not null, mime text not null, object_path text, bytes bytea,
 check ((object_path is null) <> (bytes is null)), unique(business_id,digest), unique(business_id,id)
);
create table growth.receipts (
 id uuid primary key default gen_random_uuid(), business_id uuid not null references growth.shops,
 file_id uuid not null, kind text not null check(kind in ('income','expense')), fields jsonb not null,
 customer text not null default '', created_at timestamptz default now(),
 unique(business_id,file_id), unique(business_id,id),
 foreign key(business_id,file_id) references growth.files(business_id,id)
);
create table growth.journal (
 id uuid primary key default gen_random_uuid(), business_id uuid not null references growth.shops,
 request_id uuid not null, kind text not null check(kind in ('income','expense')), amount bigint not null check(amount>0),
 day date not null, category text not null, note text not null default '', reference text,
 order_id uuid, receipt_id uuid, payment_type text check(payment_type in ('deposit','final')),
 check((order_id is null and payment_type is null) or (order_id is not null and kind='income' and payment_type is not null)),
 unique(business_id,request_id), unique(business_id,receipt_id), unique(business_id,kind,reference),
 foreign key(business_id,order_id) references growth.orders(business_id,id),
 foreign key(business_id,receipt_id) references growth.receipts(business_id,id)
);
create table growth.visuals (
 id uuid primary key default gen_random_uuid(), business_id uuid not null references growth.shops,
 month date not null, file_id uuid not null, foreign key(business_id,file_id) references growth.files(business_id,id)
);
create table growth.invoices (
 id uuid primary key default gen_random_uuid(), business_id uuid not null references growth.shops,
 amount bigint not null check(amount>0), created_at timestamptz default now(), paid_at timestamptz,
 provider_ref text unique, test boolean not null
);
create table growth.invites (
 token_hash text primary key, business_id uuid not null references growth.shops,
 email text not null, role text not null check(role in ('finance','marketing')), expires timestamptz not null
);
create table growth.notes (
 id uuid primary key default gen_random_uuid(), business_id uuid not null references growth.shops,
 author uuid not null, body text not null, summary boolean default false, created_at timestamptz default now()
);
alter table growth.shops enable row level security;
create policy scoped on growth.shops using (id=growth.scope()) with check (id=growth.scope());
do $$ declare t text; begin
 foreach t in array array['products','faqs','chats','events','topics','orders','files','receipts','journal','visuals','invoices','invites','notes','members','connections'] loop
 execute format('alter table growth.%I enable row level security',t);
 execute format('create policy scoped on growth.%I using (business_id=growth.scope()) with check (business_id=growth.scope())',t);
 end loop;
end $$;
create policy own_memberships on growth.members for select using(subject=nullif(current_setting('growth.subject',true),'')::uuid);
create policy authorized_connection on growth.connections for select using(connection=current_setting('growth.connection',true));
create policy redeem_invitation on growth.invites for select using(token_hash=current_setting('growth.invite',true));
-- On Supabase, this bucket is accessed only by the server with its storage secret.
do $$ begin
 if to_regclass('storage.buckets') is not null then
 insert into storage.buckets(id,name,public) values ('growth-private','growth-private',false) on conflict(id) do nothing;
 end if;
end $$;
