'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { FormEvent, useEffect, useState, Suspense } from 'react';
import { supabase } from '@/lib/supabase';
import { setVertexUser } from '@/lib/auth-session';
import { InteractiveDotGrid } from '@/components/ui/InteractiveDotGrid';

type AuthMode = 'login' | 'signup' | 'admin-login';

type AuthResult = {
  success?: boolean;
  message?: string;
  user_id?: string;
  username?: string;
  full_name?: string | null;
  role?: 'user' | 'admin';
};

function AuthPanelContent({ mode: initialMode }: { mode: AuthMode }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  
  // Determine starting mode, checking for ?mode=admin or initialMode
  const urlMode = searchParams?.get('mode');
  const [mode, setMode] = useState<AuthMode>(() => {
    if (urlMode === 'admin' || initialMode === 'admin-login') return 'admin-login';
    return initialMode;
  });

  const isSignup = mode === 'signup';
  const isAdminLogin = mode === 'admin-login';

  const [username, setUsername] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const switchMode = (newMode: AuthMode) => {
    setMode(newMode);
    setError('');
  };

  const persistUser = (user: AuthResult) => {
    const isUserAdmin = user.role === 'admin';
    setVertexUser({
      id: user.user_id ?? null,
      username: user.username ?? username.trim().toLowerCase(),
      fullName: user.full_name ?? (fullName.trim() || (isUserAdmin ? 'VERTEX Administrator' : null)),
      role: isUserAdmin ? 'admin' : 'user',
      adminPassword: isUserAdmin ? password : undefined,
    });
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setLoading(true);

    try {
      const activeUsername = username.trim();
      const rpcName = isSignup ? 'register_user' : 'authenticate_user';
      const rpcParams = isSignup
        ? { p_username: activeUsername, p_password: password, p_full_name: fullName }
        : { p_username: activeUsername, p_password: password };

      const { data, error: rpcError } = await supabase.rpc(rpcName, rpcParams);

      if (rpcError) throw rpcError;
      const result = data as AuthResult | null;
      if (!result?.success) {
        setError(result?.message || 'Invalid username or password. Please verify your credentials.');
        return;
      }

      persistUser(result);
      router.push('/');
    } catch (requestError: any) {
      setError(requestError?.message || 'Unable to reach the secure access service.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="relative flex-1 min-h-0 overflow-y-auto bg-surface-dim px-4 py-10">
      <InteractiveDotGrid />
      <div className="relative z-10 mx-auto flex min-h-full max-w-5xl items-center justify-center">
        <section className="grid w-full max-w-4xl overflow-hidden border border-outline-variant bg-surface shadow-2xl md:grid-cols-[.9fr_1.1fr]">
          {/* Tactical Left Panel */}
          <aside className="relative hidden overflow-hidden border-r border-outline-variant bg-surface-container-low p-8 md:block">
            <div className="absolute inset-0 opacity-40 bg-[linear-gradient(to_right,#a1400017_1px,transparent_1px),linear-gradient(to_bottom,#a1400017_1px,transparent_1px)] bg-[size:42px_42px]" />
            <div className="relative flex h-full flex-col justify-between">
              <div>
                <div className="flex items-center gap-2 text-primary">
                  <span className="material-symbols-outlined text-[24px]">target</span>
                  <span className="font-headline-sm text-lg tracking-wide">VERTEX</span>
                </div>
                <p className="mt-10 font-mono text-[10px] tracking-[.2em] text-primary">THERMAL INTELLIGENCE PLATFORM</p>
                <h1 className="mt-3 font-headline-sm text-3xl leading-tight text-on-surface">See what the heat signal means.</h1>
                <p className="mt-4 font-body-sm leading-6 text-secondary">A focused view of current satellite detections, context, and risk.</p>
              </div>

              {/* Admin Portal Indicator in Left Panel */}
              {isAdminLogin ? (
                <div className="border-l-2 border-primary pl-3 font-mono text-[10px] leading-5 tracking-wider text-primary">
                  <span className="font-bold uppercase">ADMIN CONSOLE GATEWAY</span><br />
                  SINGLE ADMINISTRATOR: ACTIVE<br />
                  AUTHORITY: USER AUDIT &amp; PURGE
                </div>
              ) : (
                <div className="border-l-2 border-primary pl-3 font-mono text-[10px] leading-5 tracking-wider text-secondary">
                  OBSERVE<br />UNDERSTAND<br />ACT
                </div>
              )}
            </div>
          </aside>

          {/* Form Right Panel */}
          <div className="p-6 sm:p-9">
            <div className="flex items-center justify-between">
              <Link href="/" className="inline-flex items-center gap-1 font-mono text-[10px] tracking-widest text-secondary transition-colors hover:text-primary">
                <span className="material-symbols-outlined text-[16px]">arrow_back</span>RETURN HOME
              </Link>
              {isAdminLogin && (
                <span className="border border-primary bg-primary/10 px-2 py-0.5 font-mono text-[9px] font-bold tracking-widest text-primary flex items-center gap-1">
                  <span className="material-symbols-outlined text-[12px]">security</span>
                  ADMIN PORTAL
                </span>
              )}
            </div>

            {/* Mode Switcher Tabs */}
            {isSignup ? (
              <div className="mt-6 flex border border-outline-variant bg-surface-container-low p-1">
                <button
                  type="button"
                  onClick={() => switchMode('login')}
                  className="flex-1 py-2 font-mono text-[10px] font-bold tracking-wider uppercase transition-colors flex items-center justify-center gap-1.5 text-secondary hover:text-on-surface"
                >
                  <span className="material-symbols-outlined text-[15px]">login</span>
                  SIGN IN
                </button>
                <button
                  type="button"
                  onClick={() => switchMode('signup')}
                  className="flex-1 py-2 font-mono text-[10px] font-bold tracking-wider uppercase transition-colors flex items-center justify-center gap-1.5 bg-surface text-primary shadow-sm border border-outline-variant/60"
                >
                  <span className="material-symbols-outlined text-[15px]">person_add</span>
                  SIGN UP
                </button>
              </div>
            ) : (
              <div className="mt-6 flex border border-outline-variant bg-surface-container-low p-1">
                <button
                  type="button"
                  onClick={() => switchMode('login')}
                  className={`flex-1 py-2 font-mono text-[10px] font-bold tracking-wider uppercase transition-colors flex items-center justify-center gap-1.5 ${
                    mode === 'login'
                      ? 'bg-surface text-primary shadow-sm border border-outline-variant/60'
                      : 'text-secondary hover:text-on-surface'
                  }`}
                >
                  <span className="material-symbols-outlined text-[15px]">person</span>
                  USER SIGN IN
                </button>
                <button
                  type="button"
                  onClick={() => switchMode('admin-login')}
                  className={`flex-1 py-2 font-mono text-[10px] font-bold tracking-wider uppercase transition-colors flex items-center justify-center gap-1.5 ${
                    mode === 'admin-login'
                      ? 'bg-primary text-on-primary shadow-sm'
                      : 'text-secondary hover:text-primary'
                  }`}
                >
                  <span className="material-symbols-outlined text-[15px]">shield_person</span>
                  ADMIN SIGN IN
                </button>
                <button
                  type="button"
                  onClick={() => switchMode('signup')}
                  className="flex-1 py-2 font-mono text-[10px] font-bold tracking-wider uppercase transition-colors flex items-center justify-center gap-1.5 text-secondary hover:text-on-surface"
                >
                  <span className="material-symbols-outlined text-[15px]">person_add</span>
                  SIGN UP
                </button>
              </div>
            )}

            <div className="mt-6">
              <p className="font-mono text-[10px] font-bold tracking-[.18em] text-primary">
                {isAdminLogin
                  ? 'ADMINISTRATOR AUTHENTICATION'
                  : isSignup
                  ? 'CREATE YOUR ACCOUNT'
                  : 'WELCOME BACK'}
              </p>
              <h2 className="mt-1 font-headline-sm text-3xl text-on-surface">
                {isAdminLogin
                  ? 'Sign in as Administrator'
                  : isSignup
                  ? 'Join VERTEX'
                  : 'Sign in to VERTEX'}
              </h2>
              <p className="mt-1 text-sm leading-6 text-secondary">
                {isAdminLogin
                  ? 'Single administrator account. Admin does not require registration.'
                  : isSignup
                  ? 'Create an account to continue to the VERTEX platform.'
                  : 'Enter your credentials to access the platform.'}
              </p>
            </div>

            {/* Admin Policy Notice */}
            {isAdminLogin && (
              <div className="mt-4 border border-primary/40 bg-primary/10 p-3.5 text-xs text-on-surface font-mono">
                <div className="flex items-center gap-1.5 text-primary font-bold mb-1">
                  <span className="material-symbols-outlined text-[16px]">shield</span>
                  <span>ADMINISTRATOR PORTAL</span>
                </div>
                <p className="text-secondary text-[11px] leading-relaxed">
                  Single administrator account. Please enter your administrator credentials to continue.
                </p>
              </div>
            )}

            <form onSubmit={submit} className="mt-5 space-y-4">
              {isSignup && (
                <label className="block">
                  <span className="mb-1.5 block font-mono text-[10px] tracking-widest text-secondary">
                    FULL NAME <span className="text-secondary/60">(OPTIONAL)</span>
                  </span>
                  <input
                    value={fullName}
                    onChange={(event) => setFullName(event.target.value)}
                    type="text"
                    autoComplete="name"
                    placeholder="Your name"
                    className="w-full border border-outline-variant bg-surface-container-low px-3 py-3 text-sm text-on-surface outline-none transition-colors placeholder:text-secondary/50 focus:border-primary"
                  />
                </label>
              )}

              <label className="block">
                <span className="mb-1.5 block font-mono text-[10px] tracking-widest text-secondary">
                  {isAdminLogin ? 'ADMIN USERNAME' : 'USERNAME'}
                </span>
                <input
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  type="text"
                  autoComplete="username"
                  minLength={3}
                  required
                  placeholder={isAdminLogin ? 'e.g. admin' : 'e.g. rohan'}
                  className="w-full border border-outline-variant bg-surface-container-low px-3 py-3 text-sm text-on-surface outline-none transition-colors placeholder:text-secondary/50 focus:border-primary"
                />
              </label>

              <label className="block">
                <span className="mb-1.5 block font-mono text-[10px] tracking-widest text-secondary">
                  {isAdminLogin ? 'ADMIN PASSWORD' : 'PASSWORD'}
                </span>
                <input
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  type="password"
                  autoComplete={isSignup ? 'new-password' : 'current-password'}
                  minLength={8}
                  required
                  placeholder={isSignup ? 'At least 8 characters' : 'Enter password'}
                  className="w-full border border-outline-variant bg-surface-container-low px-3 py-3 text-sm text-on-surface outline-none transition-colors placeholder:text-secondary/50 focus:border-primary"
                />
              </label>

              {error && (
                <div role="alert" className="flex items-center gap-2 border border-error bg-error-container p-3 text-sm text-on-error-container">
                  <span className="material-symbols-outlined text-[18px]">error</span>
                  <span>{error}</span>
                </div>
              )}

              <button
                disabled={loading}
                type="submit"
                className="flex w-full items-center justify-center gap-2 bg-primary px-4 py-3 font-mono text-[11px] font-bold tracking-[.12em] text-on-primary transition-colors hover:bg-primary-container hover:text-on-primary-container disabled:cursor-wait disabled:opacity-60"
              >
                {loading ? (
                  <span className="material-symbols-outlined animate-spin text-[18px]">progress_activity</span>
                ) : (
                  <span className="material-symbols-outlined text-[18px]">
                    {isAdminLogin ? 'shield_person' : isSignup ? 'person_add' : 'login'}
                  </span>
                )}
                {loading
                  ? 'PLEASE WAIT…'
                  : isAdminLogin
                  ? 'SIGN IN AS ADMINISTRATOR'
                  : isSignup
                  ? 'CREATE ACCOUNT'
                  : 'SIGN IN'}
              </button>
            </form>


            {/* Bottom link to switch modes */}
            <div className="mt-6 flex flex-col items-center gap-2 text-center text-xs text-secondary font-mono">
              {isAdminLogin ? (
                <p>
                  Not the administrator?{' '}
                  <button
                    type="button"
                    onClick={() => switchMode('login')}
                    className="font-bold text-primary hover:underline"
                  >
                    Standard User Sign In
                  </button>
                </p>
              ) : isSignup ? (
                <p>
                  Already have an account?{' '}
                  <button
                    type="button"
                    onClick={() => switchMode('login')}
                    className="font-bold text-primary hover:underline"
                  >
                    Sign in
                  </button>
                </p>
              ) : (
                <div className="space-y-1.5">
                  <p>
                    New to VERTEX?{' '}
                    <button
                      type="button"
                      onClick={() => switchMode('signup')}
                      className="font-bold text-primary hover:underline"
                    >
                      Create an account
                    </button>
                  </p>
                  <p>
                    Administrator access?{' '}
                    <button
                      type="button"
                      onClick={() => switchMode('admin-login')}
                      className="font-bold text-primary hover:underline"
                    >
                      Sign in as Admin
                    </button>
                  </p>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

export function AuthPanel({ mode }: { mode: AuthMode }) {
  return (
    <Suspense fallback={<div className="flex-1 bg-surface-dim" />}>
      <AuthPanelContent mode={mode} />
    </Suspense>
  );
}
