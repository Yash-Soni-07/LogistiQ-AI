/**
 * GoogleSignInButton.tsx — fully custom Google OAuth button.
 *
 * Root-cause fixes applied:
 *  1. Uses useGoogleLogin (implicit flow) instead of GoogleLogin (iframe).
 *     → Full CSS control: 100% width, no white-gap rendering issue.
 *  2. Sends access_token to POST /auth/google.
 *     → Backend calls Google's /userinfo API (async, no blocking sync call).
 *
 * Auth logic is identical to email/password flow:
 *  JWT issued → login(jwt, user) → /dashboard
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useGoogleLogin } from '@react-oauth/google';
import { Loader2 } from 'lucide-react';
import { useAuthStore } from '@/stores/auth.store';
import { apiClient } from '@/lib/api';
import { useServerWarmup } from '@/hooks/useServerWarmup';

interface GoogleSignInButtonProps {
  /** 'signin' → "Continue with Google" | 'signup' → "Sign up with Google" */
  mode?: 'signin' | 'signup';
  /** Passed to backend for tenant creation on first Google sign-up */
  companyName?: string;
  /** Called immediately before the API request (for parent loading state) */
  onStart?: () => void;
  /** Called with a human-readable error message on any failure */
  onError?: (message: string) => void;
}

// ── Google logo SVG (per Google branding guidelines) ──────────────────────────
const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path
      d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
      fill="#4285F4"
    />
    <path
      d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
      fill="#34A853"
    />
    <path
      d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"
      fill="#FBBC05"
    />
    <path
      d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
      fill="#EA4335"
    />
  </svg>
);

export function GoogleSignInButton({
  mode = 'signin',
  companyName,
  onStart,
  onError,
}: GoogleSignInButtonProps) {
  const login    = useAuthStore((s) => s.login);
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);

  // Disable while Cloud Run is waking up (same gate as email/password submit)
  const apiUrl = (import.meta.env.VITE_API_URL as string | undefined) ?? '';
  const { warmupStatus } = useServerWarmup(apiUrl);
  const isWaking   = warmupStatus === 'waking';
  const isDisabled = isWaking || loading;

  // ── Google OAuth popup (implicit flow → access_token) ─────────────────────
  const googleLogin = useGoogleLogin({
    onSuccess: async (tokenResponse) => {
      setLoading(true);
      onStart?.();
      try {
        // 1. Exchange Google access_token for a LogistiQ JWT
        const tokenRes = await apiClient.post('/auth/google', {
          access_token: tokenResponse.access_token,
          company_name: companyName || undefined,
        });
        const { access_token: jwt } = tokenRes.data;

        // 2. Fetch user profile (same pattern as email/password login)
        const profileRes = await apiClient.get('/auth/me', {
          headers: { Authorization: `Bearer ${jwt}` },
        });

        // 3. Store in Zustand + redirect — identical to email/password path
        login(jwt, profileRes.data);
        navigate('/dashboard', { replace: true });
      } catch (err: any) {
        const detail = err.response?.data?.detail;
        onError?.(detail || 'Google sign-in failed. Please try again.');
      } finally {
        setLoading(false);
      }
    },
    onError: () => {
      onError?.('Google sign-in was cancelled. Please try again.');
    },
  });

  const label = mode === 'signup' ? 'Sign up with Google' : 'Continue with Google';

  // ── Render — fully custom button, 100% width, lq design system ───────────
  return (
    <button
      id={`google-${mode}-btn`}
      type="button"
      disabled={isDisabled}
      onClick={() => !isDisabled && googleLogin()}
      onMouseEnter={(e) => {
        if (!isDisabled) {
          (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--lq-cyan)';
          (e.currentTarget as HTMLButtonElement).style.boxShadow =
            '0 0 0 1px var(--lq-cyan), 0 2px 6px rgba(0,0,0,0.10)';
        }
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.borderColor = 'var(--lq-border)';
        (e.currentTarget as HTMLButtonElement).style.boxShadow = '0 1px 3px rgba(0,0,0,0.07)';
      }}
      style={{
        width:          '100%',
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        gap:            '10px',
        height:         '40px',
        padding:        '0 16px',
        borderRadius:   '8px',
        border:         '1px solid var(--lq-border)',
        background:     'var(--lq-surface)',
        color:          'var(--lq-text-bright)',
        fontSize:       '14px',
        fontWeight:     500,
        letterSpacing:  '0.01em',
        cursor:         isDisabled ? 'not-allowed' : 'pointer',
        opacity:        isDisabled ? 0.5 : 1,
        transition:     'border-color 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease',
        boxShadow:      '0 1px 3px rgba(0,0,0,0.07)',
        userSelect:     'none',
        outline:        'none',
      }}
    >
      {loading
        ? <Loader2 size={16} className="animate-spin flex-shrink-0" />
        : <GoogleIcon />}
      <span>{loading ? 'Signing in...' : label}</span>
    </button>
  );
}
