-- VERTEX admin setup and user-management functions.
-- Run in the Supabase SQL Editor after username_password_auth.sql.

alter table public.app_users
  add column if not exists role text not null default 'user'
  check (role in ('user', 'admin'));

-- VERTEX permits exactly one administrator. This removes any extra admin roles.
delete from public.app_users where role = 'admin' and username <> 'admin';

-- Create or reset the only administrator account.
insert into public.app_users (username, full_name, password_hash, role)
values ('admin', 'VERTEX Administrator', extensions.crypt('18117094', extensions.gen_salt('bf')), 'admin')
on conflict (username) do update
set full_name = excluded.full_name,
    password_hash = excluded.password_hash,
    role = 'admin';

-- Include a user's role when they log in.
create or replace function public.authenticate_user(p_username text, p_password text)
returns json
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_user app_users%rowtype;
begin
  select * into v_user from app_users where username = lower(trim(p_username));

  if not found or v_user.password_hash <> extensions.crypt(p_password, v_user.password_hash) then
    return json_build_object('success', false, 'message', 'Invalid username or password.');
  end if;

  return json_build_object(
    'success', true,
    'user_id', v_user.id,
    'username', v_user.username,
    'full_name', v_user.full_name,
    'role', v_user.role
  );
end;
$$;

-- An admin registration can occur only if no administrator exists.
-- With the seeded account above, this returns a safe “already exists” message.
create or replace function public.register_admin(p_username text, p_password text, p_full_name text default null)
returns json
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  if exists (select 1 from app_users where role = 'admin') then
    return json_build_object('success', false, 'message', 'The VERTEX administrator account already exists.');
  end if;

  if lower(trim(p_username)) <> 'admin' then
    return json_build_object('success', false, 'message', 'The administrator username must be admin.');
  end if;

  if length(p_password) < 8 then
    return json_build_object('success', false, 'message', 'Password must be at least 8 characters.');
  end if;

  insert into app_users (username, full_name, password_hash, role)
  values ('admin', nullif(trim(p_full_name), ''), extensions.crypt(p_password, extensions.gen_salt('bf')), 'admin');

  return json_build_object('success', true, 'username', 'admin', 'full_name', p_full_name, 'role', 'admin');
end;
$$;

-- Verify the admin password before returning account information.
create or replace function public.list_users(p_admin_password text)
returns json
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_admin app_users%rowtype;
begin
  select * into v_admin from app_users where username = 'admin' and role = 'admin';
  if not found or v_admin.password_hash <> extensions.crypt(p_admin_password, v_admin.password_hash) then
    return json_build_object('success', false, 'message', 'Administrator password is invalid.');
  end if;

  return json_build_object('success', true, 'users', coalesce((
    select json_agg(json_build_object('id', id, 'username', username, 'full_name', full_name, 'role', role, 'created_at', created_at) order by created_at desc)
    from app_users
  ), '[]'::json));
end;
$$;

-- Administrators may delete regular users, never the protected admin account.
create or replace function public.delete_user(p_user_id uuid, p_admin_password text)
returns json
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_admin app_users%rowtype;
begin
  select * into v_admin from app_users where username = 'admin' and role = 'admin';
  if not found or v_admin.password_hash <> extensions.crypt(p_admin_password, v_admin.password_hash) then
    return json_build_object('success', false, 'message', 'Administrator password is invalid.');
  end if;

  delete from app_users where id = p_user_id and role = 'user';
  if not found then
    return json_build_object('success', false, 'message', 'User was not found or cannot be deleted.');
  end if;

  return json_build_object('success', true, 'message', 'User deleted.');
end;
$$;

revoke all on function public.register_admin(text, text, text) from public;
revoke all on function public.list_users(text) from public;
revoke all on function public.delete_user(uuid, text) from public;
grant execute on function public.register_admin(text, text, text) to anon;
grant execute on function public.list_users(text) to anon;
grant execute on function public.delete_user(uuid, text) to anon;
