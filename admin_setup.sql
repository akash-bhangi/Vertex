-- ==============================================================
-- VERTEX Complete Authentication & User Management Setup
-- Run this in your Supabase SQL Editor (Dashboard > SQL Editor > New query)
-- ==============================================================

-- 1. Enable pgcrypto extension for password encryption
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

-- 2. Create the app_users table
CREATE TABLE IF NOT EXISTS public.app_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT UNIQUE NOT NULL,
  full_name TEXT,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable Row Level Security
ALTER TABLE public.app_users ENABLE ROW LEVEL SECURITY;

-- Allow users table access through security definer functions only
-- (or read-only for authenticated admins if needed)
DROP POLICY IF EXISTS "Deny direct anon table access" ON public.app_users;
CREATE POLICY "Deny direct anon table access" ON public.app_users
  FOR ALL TO anon USING (false);

-- 3. VERTEX permits exactly one administrator. Reset or create it.
DELETE FROM public.app_users WHERE role = 'admin' AND username <> 'admin';

INSERT INTO public.app_users (username, full_name, password_hash, role)
VALUES ('admin', 'VERTEX Administrator', extensions.crypt('18117094', extensions.gen_salt('bf')), 'admin')
ON CONFLICT (username) DO UPDATE
SET full_name = EXCLUDED.full_name,
    password_hash = EXCLUDED.password_hash,
    role = 'admin';

-- ==============================================================
-- 4. User Registration Function (register_user)
-- ==============================================================
CREATE OR REPLACE FUNCTION public.register_user(
  p_username TEXT,
  p_password TEXT,
  p_full_name TEXT DEFAULT NULL
)
RETURNS JSON
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, extensions
AS $$
DECLARE
  v_clean_username TEXT;
  v_user_id UUID;
BEGIN
  v_clean_username := lower(trim(p_username));

  -- Validation
  IF length(v_clean_username) < 3 THEN
    RETURN json_build_object('success', false, 'message', 'Username must be at least 3 characters.');
  END IF;

  IF length(p_password) < 6 THEN
    RETURN json_build_object('success', false, 'message', 'Password must be at least 6 characters.');
  END IF;

  -- Disallow registering the reserved admin username
  IF v_clean_username = 'admin' THEN
    RETURN json_build_object('success', false, 'message', 'Username "admin" is reserved.');
  END IF;

  -- Check if user already exists
  IF EXISTS (SELECT 1 FROM public.app_users WHERE username = v_clean_username) THEN
    RETURN json_build_object('success', false, 'message', 'Username is already registered. Please log in.');
  END IF;

  -- Insert new user
  INSERT INTO public.app_users (username, full_name, password_hash, role)
  VALUES (
    v_clean_username,
    nullif(trim(p_full_name), ''),
    extensions.crypt(p_password, extensions.gen_salt('bf')),
    'user'
  )
  RETURNING id INTO v_user_id;

  RETURN json_build_object(
    'success', true,
    'user_id', v_user_id,
    'username', v_clean_username,
    'full_name', p_full_name,
    'role', 'user'
  );
END;
$$;

-- ==============================================================
-- 5. User Authentication / Login Function (authenticate_user)
-- ==============================================================
CREATE OR REPLACE FUNCTION public.authenticate_user(
  p_username TEXT,
  p_password TEXT
)
RETURNS JSON
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, extensions
AS $$
DECLARE
  v_user public.app_users%rowtype;
BEGIN
  SELECT * INTO v_user FROM public.app_users WHERE username = lower(trim(p_username));

  IF NOT FOUND OR v_user.password_hash <> extensions.crypt(p_password, v_user.password_hash) THEN
    RETURN json_build_object('success', false, 'message', 'Invalid username or password.');
  END IF;

  RETURN json_build_object(
    'success', true,
    'user_id', v_user.id,
    'username', v_user.username,
    'full_name', v_user.full_name,
    'role', v_user.role
  );
END;
$$;

-- ==============================================================
-- 6. Admin Registration Function (register_admin)
-- ==============================================================
CREATE OR REPLACE FUNCTION public.register_admin(
  p_username TEXT,
  p_password TEXT,
  p_full_name TEXT DEFAULT NULL
)
RETURNS JSON
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, extensions
AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM public.app_users WHERE role = 'admin') THEN
    RETURN json_build_object('success', false, 'message', 'The VERTEX administrator account already exists.');
  END IF;

  IF lower(trim(p_username)) <> 'admin' THEN
    RETURN json_build_object('success', false, 'message', 'The administrator username must be admin.');
  END IF;

  IF length(p_password) < 8 THEN
    RETURN json_build_object('success', false, 'message', 'Password must be at least 8 characters.');
  END IF;

  INSERT INTO public.app_users (username, full_name, password_hash, role)
  VALUES ('admin', nullif(trim(p_full_name), ''), extensions.crypt(p_password, extensions.gen_salt('bf')), 'admin');

  RETURN json_build_object('success', true, 'username', 'admin', 'full_name', p_full_name, 'role', 'admin');
END;
$$;

-- ==============================================================
-- 7. Admin List Users Function (list_users)
-- ==============================================================
CREATE OR REPLACE FUNCTION public.list_users(p_admin_password TEXT)
RETURNS JSON
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, extensions
AS $$
DECLARE
  v_admin public.app_users%rowtype;
BEGIN
  SELECT * INTO v_admin FROM public.app_users WHERE username = 'admin' AND role = 'admin';
  IF NOT FOUND OR v_admin.password_hash <> extensions.crypt(p_admin_password, v_admin.password_hash) THEN
    RETURN json_build_object('success', false, 'message', 'Administrator password is invalid.');
  END IF;

  RETURN json_build_object('success', true, 'users', coalesce((
    SELECT json_agg(json_build_object('id', id, 'username', username, 'full_name', full_name, 'role', role, 'created_at', created_at) ORDER BY created_at DESC)
    FROM public.app_users
  ), '[]'::json));
END;
$$;

-- ==============================================================
-- 8. Admin Delete User Function (delete_user)
-- ==============================================================
CREATE OR REPLACE FUNCTION public.delete_user(p_user_id UUID, p_admin_password TEXT)
RETURNS JSON
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, extensions
AS $$
DECLARE
  v_admin public.app_users%rowtype;
BEGIN
  SELECT * INTO v_admin FROM public.app_users WHERE username = 'admin' AND role = 'admin';
  IF NOT FOUND OR v_admin.password_hash <> extensions.crypt(p_admin_password, v_admin.password_hash) THEN
    RETURN json_build_object('success', false, 'message', 'Administrator password is invalid.');
  END IF;

  DELETE FROM public.app_users WHERE id = p_user_id AND role = 'user';
  IF NOT FOUND THEN
    RETURN json_build_object('success', false, 'message', 'User was not found or cannot be deleted.');
  END IF;

  RETURN json_build_object('success', true, 'message', 'User deleted.');
END;
$$;

-- ==============================================================
-- 9. Grant RPC Execution Permissions to anon & authenticated
-- ==============================================================
REVOKE ALL ON FUNCTION public.register_admin(TEXT, TEXT, TEXT) FROM public;
REVOKE ALL ON FUNCTION public.list_users(TEXT) FROM public;
REVOKE ALL ON FUNCTION public.delete_user(UUID, TEXT) FROM public;

GRANT EXECUTE ON FUNCTION public.register_user(TEXT, TEXT, TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.authenticate_user(TEXT, TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_admin(TEXT, TEXT, TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.list_users(TEXT) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.delete_user(UUID, TEXT) TO anon, authenticated;
