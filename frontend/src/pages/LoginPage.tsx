import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Mail, Lock, ArrowRight, Loader2, AlertCircle, Hexagon } from 'lucide-react';
import { useAuthStore } from '@/stores/auth.store';
import { apiClient } from '@/lib/api';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import AuthBackground from '@/components/auth/AuthBackground';
import { useServerWarmup } from '@/hooks/useServerWarmup';
import { WarmupTypewriter } from '@/components/auth/WarmupTypewriter';
import { GoogleSignInButton } from '@/components/auth/GoogleSignInButton';

export default function LoginPage() {
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const isAuthenticated = useAuthStore((s) => !!s.token);

  React.useEffect(() => {
    if (isAuthenticated) navigate('/dashboard', { replace: true });
  }, [isAuthenticated, navigate]);

  // ── Server warm-up (Cloud Run cold-start mitigation) ──────────────────────
  const apiUrl = (import.meta.env.VITE_API_URL as string | undefined) ?? '';
  const { warmupStatus } = useServerWarmup(apiUrl);
  const isWaking = warmupStatus === 'waking';
  // ─────────────────────────────────────────────────────────────────────────

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) return;

    setLoading(true);
    setError(null);

    try {
      // 1. Fetch Tokens
      const tokenRes = await apiClient.post('/auth/login', { email, password });
      const { access_token } = tokenRes.data;

      // 2. Fetch User Profile
      // Temporarily set authorization header for this request before Zustand updates it globally
      const profileRes = await apiClient.get('/auth/me', {
        headers: { Authorization: `Bearer ${access_token}` }
      });

      // 3. Update Store & Redirect
      login(access_token, profileRes.data);
      navigate('/dashboard', { replace: true });
      
    } catch (err: any) {
      if (err.response?.data?.detail) {
        setError(err.response.data.detail);
      } else {
        setError('Unable to connect to the authentication server.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full min-h-screen md:h-screen md:overflow-hidden flex items-center justify-center bg-[var(--lq-bg)] px-4 py-6">
      
      <AuthBackground />

      <div className="w-full max-w-md flex flex-col items-center relative z-10">
        
        {/* Logo Header */}
        <div className="flex flex-col items-center mb-3">
          <div className="w-10 h-10 rounded-xl bg-[var(--lq-cyan)] flex items-center justify-center text-white mb-2 shadow-lg shadow-cyan-500/25 ring-4 ring-[var(--lq-cyan)]/10">
            <Hexagon size={20} className="fill-current" />
          </div>
          <h1 className="text-xl font-bold text-[var(--lq-text-bright)] tracking-tight">LogistiQ AI</h1>
          <p className="text-[var(--lq-text-dim)] text-xs mt-0.5">Intelligent Freight Orchestration</p>
        </div>

        {/* AI insight panel — always visible, independent of server state */}
        <div className="w-full mb-2">
          <WarmupTypewriter />
        </div>

        {/* Google OAuth */}
        <div className="w-full mb-2">
          <GoogleSignInButton
            mode="signin"
            onStart={() => { setLoading(true); setError(null); }}
            onError={(msg) => { setError(msg); setLoading(false); }}
          />
        </div>

        {/* Divider */}
        <div className="w-full flex items-center gap-3 mb-2">
          <div className="flex-1 h-px bg-[var(--lq-border)]" />
          <span className="text-xs text-[var(--lq-text-dim)] uppercase tracking-widest font-medium">or</span>
          <div className="flex-1 h-px bg-[var(--lq-border)]" />
        </div>

        {/* Login Card */}
        <div className="w-full bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-2xl p-4 sm:p-5 shadow-[0_4px_24px_rgba(0,0,0,0.08),0_0_0_1px_rgba(34,211,238,0.06)]">
          {/* Card header: title + live connection badge */}
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-xl font-semibold text-[var(--lq-text-bright)]">Sign In</h2>
            <div className="flex items-center gap-1.5">
              {isWaking && (
                <>
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                  <span className="text-xs text-[var(--lq-text-dim)] font-medium">Connecting</span>
                </>
              )}
              {warmupStatus === 'connected' && (
                <>
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  <span className="text-xs text-emerald-400 font-medium">Connected</span>
                </>
              )}
            </div>
          </div>

          {error && (
            <Alert variant="destructive" className="mb-5 bg-red-500/10 text-red-500 border-red-500/20">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <form onSubmit={handleLogin} className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="email" className="text-[var(--lq-text-bright)] text-xs uppercase tracking-wider font-semibold">Email Address</Label>
              <div className="relative">
                <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--lq-text-dim)]">
                  <Mail size={16} />
                </div>
                <Input 
                  id="email" 
                  type="email" 
                  placeholder="admin@logistiq.ai" 
                  className="pl-10 bg-[var(--lq-bg)] border-[var(--lq-border)] text-[var(--lq-text-bright)] focus-visible:ring-[var(--lq-cyan)]"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={loading}
                  required
                />
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password" className="text-[var(--lq-text-bright)] text-xs uppercase tracking-wider font-semibold">Password</Label>
                <a href="#" className="text-xs text-[var(--lq-cyan)] hover:underline">Forgot password?</a>
              </div>
              <div className="relative">
                <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--lq-text-dim)]">
                  <Lock size={16} />
                </div>
                <Input 
                  id="password" 
                  type="password" 
                  placeholder="••••••••" 
                  className="pl-10 bg-[var(--lq-bg)] border-[var(--lq-border)] text-[var(--lq-text-bright)] focus-visible:ring-[var(--lq-cyan)]"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={loading}
                  required
                />
              </div>
            </div>

            <Button 
              type="submit" 
              className="w-full text-white mt-3 h-10 font-medium transition-all duration-300 shadow-md"
              disabled={loading || isWaking || !email || !password}
              style={{
                opacity: isWaking ? 0.65 : 1,
                background: 'linear-gradient(135deg, var(--lq-cyan) 0%, #0e7490 100%)',
              }}
            >
              {loading ? (
                <Loader2 size={18} className="animate-spin" />
              ) : isWaking ? (
                <span className="text-sm">⏳ Waking secure servers...</span>
              ) : (
                <>
                  Sign In <ArrowRight size={16} className="ml-2" />
                </>
              )}
            </Button>
          </form>

        </div>

        {/* Footer */}
        <p className="mt-3 text-sm text-[var(--lq-text-dim)]">
          Don't have an account?{' '}
          <Link to="/register" className="text-[var(--lq-cyan)] hover:underline font-medium">
            Create tenant workspace
          </Link>
        </p>
      </div>
    </div>
  );
}
