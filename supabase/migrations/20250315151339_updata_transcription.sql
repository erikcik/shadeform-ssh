-- Migration: Update RLS policies for transcriptions table
-- This migration adds a policy for anonymous users to insert into the transcriptions table

-- Add policy for anonymous users to insert transcriptions
create policy "Anonymous users can insert transcriptions" 
on public.transcriptions
for insert 
to anon
with check (true);

-- Additional policies for admin users
create policy "Admins can manage all transcriptions" 
on public.transcriptions
for all
to authenticated
using (
  exists (
    select 1 from public.profiles 
    where profiles.id = auth.uid() 
    and profiles.role = 'admin'
  )
); 