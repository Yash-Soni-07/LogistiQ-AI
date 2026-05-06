import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Mail, Lock, ArrowRight, Loader2, AlertCircle, Building, User, Hexagon } from 'lucide-react';
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

export default function RegisterPage() {
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

  const [formData, setFormData] = useState({
    firstName: '',
    lastName: '',
    companyName: '',
    email: '',
    password: ''
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData(prev => ({ ...prev, [e.target.id]: e.target.value }));
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    const { firstName, lastName, companyName, email, password } = formData;
    if (!firstName || !lastName || !companyName || !email || !password) return;

    setLoading(true);
    setError(null);

    try {
      // 1. Register & Fetch Tokens
      const tokenRes = await apiClient.post('/auth/register', {
        first_name: firstName,
        last_name: lastName,
        company_name: companyName,
        email,
        password
      });
      const { access_token } = tokenRes.data;

      // 2. Fetch User Profile
      const profileRes = await apiClient.get('/auth/me', {
        headers: { Authorization: `Bearer ${access_token}` }
      });

      // 3. Update Store & Redirect
      login(access_token, profileRes.data);
      navigate('/dashboard', { replace: true });
      
    } catch (err: any) {
      if (err.response?.data?.detail) {
        // Handle FastAPI validation errors or standard HTTP exceptions
        const detail = err.response.data.detail;
        if (Array.isArray(detail)) {
          setError(detail[0].msg);
        } else {
          setError(detail);
        }
      } else {
        setError('Unable to complete registration. Please try again later.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full min-h-screen md:h-screen md:overflow-hidden flex items-center justify-center bg-[var(--lq-bg)] px-4 py-6">
      
      <AuthBackground />

      <div className="w-full max-w-lg flex flex-col items-center relative z-10">
        
        {/* Logo Header */}
        <div className="flex flex-col items-center mb-2">
          <div className="w-9 h-9 rounded-xl bg-[var(--lq-cyan)] flex items-center justify-center text-white mb-2 shadow-lg shadow-cyan-500/25 ring-4 ring-[var(--lq-cyan)]/10">
            <Hexagon size={18} className="fill-current" />
          </div>
          <h1 className="text-lg font-bold text-[var(--lq-text-bright)] tracking-tight">Create Workspace</h1>
        </div>

        {/* AI insight panel — always visible, independent of server state */}
        <div className="w-full mb-2">
          <WarmupTypewriter />
        </div>

        {/* Google OAuth — companyName passed for first-time tenant creation */}
        <div className="w-full mb-2">
          <GoogleSignInButton
            mode="signup"
            companyName={formData.companyName || undefined}
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

        {/* Register Card */}
        <div className="w-full bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-2xl p-4 shadow-[0_4px_24px_rgba(0,0,0,0.08),0_0_0_1px_rgba(34,211,238,0.06)]">
          {error && (
            <Alert variant="destructive" className="mb-4 bg-red-500/10 text-red-500 border-red-500/20">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <form onSubmit={handleRegister} className="space-y-2">
            
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="firstName" className="text-[var(--lq-text-bright)] text-xs uppercase tracking-wider font-semibold">First Name</Label>
                <div className="relative">
                  <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--lq-text-dim)]">
                    <User size={16} />
                  </div>
                  <Input 
                    id="firstName" 
                    placeholder="John" 
                    className="pl-10 bg-[var(--lq-bg)] border-[var(--lq-border)] text-[var(--lq-text-bright)] focus-visible:ring-[var(--lq-cyan)]"
                    value={formData.firstName}
                    onChange={handleChange}
                    disabled={loading}
                    required
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="lastName" className="text-[var(--lq-text-bright)] text-xs uppercase tracking-wider font-semibold">Last Name</Label>
                <Input 
                  id="lastName" 
                  placeholder="Doe" 
                  className="bg-[var(--lq-bg)] border-[var(--lq-border)] text-[var(--lq-text-bright)] focus-visible:ring-[var(--lq-cyan)]"
                  value={formData.lastName}
                  onChange={handleChange}
                  disabled={loading}
                  required
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="companyName" className="text-[var(--lq-text-bright)] text-xs uppercase tracking-wider font-semibold">Company Name</Label>
              <div className="relative">
                <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--lq-text-dim)]">
                  <Building size={16} />
                </div>
                <Input 
                  id="companyName" 
                  placeholder="Global Freight Inc." 
                  className="pl-10 bg-[var(--lq-bg)] border-[var(--lq-border)] text-[var(--lq-text-bright)] focus-visible:ring-[var(--lq-cyan)]"
                  value={formData.companyName}
                  onChange={handleChange}
                  disabled={loading}
                  required
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="email" className="text-[var(--lq-text-bright)] text-xs uppercase tracking-wider font-semibold">Work Email</Label>
              <div className="relative">
                <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--lq-text-dim)]">
                  <Mail size={16} />
                </div>
                <Input 
                  id="email" 
                  type="email" 
                  placeholder="admin@globalfreight.com" 
                  className="pl-10 bg-[var(--lq-bg)] border-[var(--lq-border)] text-[var(--lq-text-bright)] focus-visible:ring-[var(--lq-cyan)]"
                  value={formData.email}
                  onChange={handleChange}
                  disabled={loading}
                  required
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="password" className="text-[var(--lq-text-bright)] text-xs uppercase tracking-wider font-semibold">Password</Label>
              <div className="relative">
                <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--lq-text-dim)]">
                  <Lock size={16} />
                </div>
                <Input 
                  id="password" 
                  type="password" 
                  placeholder="Create a strong password" 
                  className="pl-10 bg-[var(--lq-bg)] border-[var(--lq-border)] text-[var(--lq-text-bright)] focus-visible:ring-[var(--lq-cyan)]"
                  value={formData.password}
                  onChange={handleChange}
                  disabled={loading}
                  required
                />
              </div>
            </div>

            <Button 
              type="submit" 
              className="w-full text-white mt-2 h-10 font-medium transition-all duration-300 shadow-md"
              disabled={loading || isWaking || !formData.email || !formData.password || !formData.firstName || !formData.lastName || !formData.companyName}
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
                  Initialize Workspace <ArrowRight size={16} className="ml-2" />
                </>
              )}
            </Button>
          </form>

          {/* Connection status — compact single row */}
          <div className="mt-2 flex items-center justify-center gap-1.5 h-4">
            {isWaking && (
              <><span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" /><span className="text-xs text-[var(--lq-text-dim)]">Establishing secure connection...</span></>
            )}
            {warmupStatus === 'connected' && (
              <><span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400" /><span className="text-xs text-emerald-400">Securely connected</span></>
            )}
          </div>
        </div>

        {/* Footer */}
        <p className="mt-2 text-sm text-[var(--lq-text-dim)]">
          Already have an account?{' '}
          <Link to="/login" className="text-[var(--lq-cyan)] hover:underline font-medium">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
