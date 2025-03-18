-- Create a table for storing conversation transcriptions
create table public.transcriptions (
  id bigint generated always as identity primary key,
  conversation_id text not null,
  user_id text not null,
  text text not null,
  speaker text not null,
  timestamp float not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.transcriptions is 'Stores transcriptions of conversations between AI agents and users';
comment on column public.transcriptions.conversation_id is 'Unique identifier for the conversation';
comment on column public.transcriptions.user_id is 'ID of the user/participant, or "agent" for the AI';
comment on column public.transcriptions.text is 'The transcribed speech text';
comment on column public.transcriptions.speaker is 'Who is speaking, either "user" or "agent"';
comment on column public.transcriptions.timestamp is 'Seconds from the start of the conversation when this was spoken';

-- Enable Row Level Security (RLS)
alter table public.transcriptions enable row level security;

-- Create RLS policies
-- Policy for anon users - read-only access to transcriptions
create policy "Transcriptions are viewable by anyone" 
on public.transcriptions
for select 
to anon
using (true);

-- Policy for authenticated users - read-only access to transcriptions
create policy "Transcriptions are viewable by authenticated users" 
on public.transcriptions
for select 
to authenticated
using (true);

-- Policy for authenticated users to insert transcriptions
create policy "Authenticated users can insert transcriptions" 
on public.transcriptions
for insert 
to authenticated
with check (true);

-- Add an index for faster lookups by conversation_id
create index idx_transcriptions_conversation_id on public.transcriptions(conversation_id);

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
create trigger update_transcriptions_timestamp
before update on public.transcriptions
for each row
execute function public.update_updated_at(); 