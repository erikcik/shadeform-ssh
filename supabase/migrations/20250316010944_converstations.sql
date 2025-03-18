-- Create a table for storing structured conversation data
create table public.conversations (
  id bigint generated always as identity primary key,
  conversation_id text not null unique,
  user_id text not null,
  conversation_data jsonb not null default '{"exchanges": []}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.conversations is 'Stores structured conversation data between AI agents and users';
comment on column public.conversations.conversation_id is 'Unique identifier for the conversation';
comment on column public.conversations.user_id is 'ID of the user/participant';
comment on column public.conversations.conversation_data is 'Structured JSON data containing the conversation exchanges';

-- Enable Row Level Security (RLS)
alter table public.conversations enable row level security;

-- Create RLS policies
-- Policy for anon users - read-only access to conversations
create policy "Conversations are viewable by anyone" 
on public.conversations
for select 
to anon
using (true);

-- Policy for authenticated users - read-only access to conversations
create policy "Conversations are viewable by authenticated users" 
on public.conversations
for select 
to authenticated
using (true);

-- Policy for authenticated users to insert conversations
create policy "Authenticated users can insert conversations" 
on public.conversations
for insert 
to authenticated
with check (true);

-- Policy for authenticated users to update conversations
create policy "Authenticated users can update conversations" 
on public.conversations
for update 
to authenticated
using (true)
with check (true);

-- Policy for anonymous users to insert conversations
create policy "Anonymous users can insert conversations" 
on public.conversations
for insert 
to anon
with check (true);

-- Policy for anonymous users to update conversations
create policy "Anonymous users can update conversations" 
on public.conversations
for update 
to anon
using (true)
with check (true);

-- Add an index for faster lookups by conversation_id
create index idx_conversations_conversation_id on public.conversations(conversation_id);

-- Create a function to automatically update timestamps
create or replace function public.update_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- Create a trigger to update timestamps
create trigger update_conversations_timestamp
before update on public.conversations
for each row
execute function public.update_updated_at(); 