-- Compatibility schema for a new development database. Existing public legacy tables
-- keep their original search_path on existing deployments.
create schema growth_legacy;
revoke all on schema growth_legacy from public;
create table growth_legacy.users(id bigserial primary key,telegram_id bigint unique not null,lang text not null default 'uz');
create table growth_legacy.businesses(id bigserial primary key,owner_id bigint not null references growth_legacy.users,name text not null,currency text default 'UZS');
create table growth_legacy.categories(id bigserial primary key,business_id bigint references growth_legacy.businesses,code text,type text not null,name_ru text,name_uz text);
create table growth_legacy.transactions(id bigserial primary key,business_id bigint not null references growth_legacy.businesses,type text not null,amount bigint not null check(amount>0),occurred_on date not null,category_id bigint references growth_legacy.categories,description text,source text,counterparty text,is_corrected boolean default false,deleted_at timestamptz);
create table growth_legacy.link_codes(user_id bigint not null references growth_legacy.users,code_hash text not null,expires_at timestamptz not null,used_at timestamptz);
