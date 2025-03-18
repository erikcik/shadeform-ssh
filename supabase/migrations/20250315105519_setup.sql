-- Migration: Initial Setup
-- This migration sets up the initial database schema for the admin dashboard

-- Enable RLS on auth.users
alter table auth.users enable row level security;
-- Create profiles table to store additional user information
create table public.profiles (
  id uuid references auth.users(id) primary key,
  updated_at timestamp with time zone default now(),
  username text unique,
  full_name text,
  avatar_url text,
  role text not null default 'user' check (role in ('user', 'admin')),
  is_active boolean default true
);
comment on table public.profiles is 'Profile information for each user.';
-- Enable Row Level Security
alter table public.profiles enable row level security;
-- Create secure policies

-- Allow users to view their own profile
create policy "Users can view their own profile"
on public.profiles
for select
to authenticated
using ((auth.uid() = id));
-- Allow users to update their own profile
create policy "Users can update their own profile"
on public.profiles
for update
to authenticated
using ((auth.uid() = id))
with check ((auth.uid() = id));
-- Automatically create a profile entry when a new user signs up
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  insert into public.profiles (id, full_name, avatar_url, username)
  values (new.id, new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'avatar_url', new.email);
  return new;
end;
$$;
-- Trigger the function every time a user is created
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();
-- Set up RLS policy for admins to view all profiles
create policy "Admins can view all profiles"
on public.profiles
for select
to authenticated
using (
  (select role from public.profiles where id = auth.uid()) = 'admin'
);
-- Set up RLS policy for admins to update all profiles
create policy "Admins can update all profiles"
on public.profiles
for update
to authenticated
using (
  (select role from public.profiles where id = auth.uid()) = 'admin'
)
with check (
  (select role from public.profiles where id = auth.uid()) = 'admin'
);
