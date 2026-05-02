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
    <div className="min-h-screen w-full flex items-center justify-center bg-[var(--lq-bg)] p-4 sm:p-8">
      
      <AuthBackground />

      <div className="w-full max-w-md flex flex-col items-center relative z-10">
        
        {/* Logo Header */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 rounded-xl bg-[var(--lq-cyan)] flex items-center justify-center text-white mb-4 shadow-lg shadow-cyan-500/20">
            <Hexagon size={24} className="fill-current" />
          </div>
          <h1 className="text-2xl font-bold text-[var(--lq-text-bright)] tracking-tight">LogistiQ AI</h1>
          <p className="text-[var(--lq-text-dim)] text-sm mt-1">Intelligent Freight Orchestration</p>
        </div>

        {/* Login Card */}
        <div className="w-full bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-2xl p-6 sm:p-8 shadow-xl shadow-black/5">
          <h2 className="text-xl font-semibold text-[var(--lq-text-bright)] mb-6">Sign In</h2>
          
          {error && (
            <Alert variant="destructive" className="mb-6 bg-red-500/10 text-red-500 border-red-500/20">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <form onSubmit={handleLogin} className="space-y-4">
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
              className="w-full bg-[var(--lq-cyan)] hover:bg-[var(--lq-cyan)]/90 text-white mt-6 h-11 transition-opacity duration-300"
              disabled={loading || isWaking || !email || !password}
              style={{ opacity: isWaking ? 0.6 : 1 }}
            >
              {loading ? (
                <Loader2 size={18} className="animate-spin" />
              ) : isWaking ? (
                <span className="text-sm">⏳ Waking secure servers (approx 5s)...</span>
              ) : (
                <>
                  Sign In <ArrowRight size={16} className="ml-2" />
                </>
              )}
            </Button>
          </form>

          {/* Server warm-up status indicator */}
          <div className="mt-4 flex items-center justify-center gap-2 min-h-[20px]">
            {isWaking && (
              <p className="text-xs text-[var(--lq-text-dim)] flex items-center gap-1.5">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                Establishing secure connection...
              </p>
            )}
            {warmupStatus === 'connected' && (
              <p className="text-xs text-emerald-400 flex items-center gap-1.5">
                ✅ Securely connected
              </p>
            )}
          </div>
        </div>

        {/* Footer */}
        <p className="mt-8 text-sm text-[var(--lq-text-dim)]">
          Don't have an account?{' '}
          <Link to="/register" className="text-[var(--lq-cyan)] hover:underline font-medium">
            Create tenant workspace
          </Link>
        </p>
      </div>
    </div>
  );
}
