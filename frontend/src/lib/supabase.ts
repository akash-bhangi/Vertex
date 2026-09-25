import { createClient } from '@supabase/supabase-js';

const supabaseUrl =
  process.env.NEXT_PUBLIC_SUPABASE_URL ||
  process.env.SUPABASE_URL ||
  'https://heezkejugtehennmiugd.supabase.co';

const supabaseAnonKey =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
  process.env.SUPABASE_ANON_KEY ||
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhlZXprZWp1Z3RlaGVubm1pdWdkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgwNjgyMTYsImV4cCI6MjEwMzY0NDIxNn0.Ft0oe-ked_Eiba9LPOmWbc1LHvRgq9DnD27q9FPj6L8';

// VERTEX uses custom RPC authentication, not Supabase Auth sessions.
// Disabling the unused Auth client prevents browser lock/session work from
// being started during development refreshes.
export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    persistSession: false,
    autoRefreshToken: false,
    detectSessionInUrl: false,
  },
});
