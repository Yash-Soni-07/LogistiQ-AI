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
    <div className="min-h-screen w-full flex items-center justify-center bg-[var(--lq-bg)] p-4 sm:p-8">
      
      <AuthBackground />

      <div className="w-full max-w-lg flex flex-col items-center relative z-10">
        
        {/* Logo Header */}
        <div className="flex flex-col items-center mb-6">
          <div className="w-10 h-10 rounded-xl bg-[var(--lq-cyan)] flex items-center justify-center text-white mb-3 shadow-lg shadow-cyan-500/20">
            <Hexagon size={20} className="fill-current" />
          </div>
          <h1 className="text-xl font-bold text-[var(--lq-text-bright)] tracking-tight">Create Workspace</h1>
        </div>

        {/* Register Card */}
        <div className="w-full bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-2xl p-6 sm:p-8 shadow-xl shadow-black/5">
          {error && (
            <Alert variant="destructive" className="mb-6 bg-red-500/10 text-red-500 border-red-500/20">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <form onSubmit={handleRegister} className="space-y-4">
            
            <div className="grid grid-cols-2 gap-4">
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
              className="w-full bg-[var(--lq-cyan)] hover:bg-[var(--lq-cyan)]/90 text-white mt-6 h-11 transition-opacity duration-300"
              disabled={loading || isWaking || !formData.email || !formData.password || !formData.firstName || !formData.lastName || !formData.companyName}
              style={{ opacity: isWaking ? 0.6 : 1 }}
            >
              {loading ? (
                <Loader2 size={18} className="animate-spin" />
              ) : isWaking ? (
                <span className="text-sm">⏳ Waking secure servers (approx 5s)...</span>
              ) : (
                <>
                  Initialize Workspace <ArrowRight size={16} className="ml-2" />
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
          Already have an account?{' '}
          <Link to="/login" className="text-[var(--lq-cyan)] hover:underline font-medium">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
