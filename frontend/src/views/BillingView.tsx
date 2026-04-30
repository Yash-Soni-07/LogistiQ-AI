import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { 
  Check, Shield, Zap, Globe, Package, Cloud,
  Factory, Users, Terminal, CreditCard, ExternalLink,
  Loader2, BadgeCheck, AlertCircle, TrendingUp
} from 'lucide-react';
import { apiClient, queryClient } from '@/lib/api';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { RazorpayDemoModal } from '@/components/billing/RazorpayDemoModal';

interface PlanFeature {
  text: string;
  included: boolean;
}

interface SubscriptionPlan {
  id: string;
  name: string;
  price_inr: string;
  price_usd: string;
  limit: string;
  decision_cost: string;
  mcp_servers: string;
  sectors: string;
  features: PlanFeature[];
  popular?: boolean;
  color: string;
}

const PLANS: SubscriptionPlan[] = [
  {
    id: 'starter',
    name: 'Starter',
    price_inr: '₹15,000',
    price_usd: '$180',
    limit: 'Up to 500 Shipments',
    decision_cost: '100 included, then ₹15/decision',
    mcp_servers: 'Weather + Shipment',
    sectors: 'Road only, Retail/Food',
    color: 'var(--lq-cyan)',
    features: [
      { text: 'Real-time Tracking', included: true },
      { text: 'Weather Intelligence', included: true },
      { text: 'Road Freight Only', included: true },
      { text: 'Retail & Food Sectors', included: true },
      { text: 'Custom MCP Servers', included: false },
      { text: 'Multi-modal Logistics', included: false },
    ]
  },
  {
    id: 'pro',
    name: 'Pro',
    popular: true,
    price_inr: '₹45,000',
    price_usd: '$540',
    limit: 'Up to 5,000 Shipments',
    decision_cost: '1,000 included, then ₹8/decision',
    mcp_servers: 'All 5 MCP servers',
    sectors: 'All sectors, Multi-modal',
    color: 'var(--lq-purple)',
    features: [
      { text: 'Everything in Starter', included: true },
      { text: 'All 5 MCP Servers', included: true },
      { text: 'All Industry Sectors', included: true },
      { text: 'Multi-modal (Air/Sea/Road)', included: true },
      { text: 'Priority Agent Support', included: true },
      { text: 'Custom MCP Integration', included: false },
    ]
  },
  {
    id: 'enterprise',
    name: 'Enterprise',
    price_inr: 'Custom',
    price_usd: '₹1.5L+',
    limit: 'Unlimited Shipments',
    decision_cost: 'Unlimited decisions',
    mcp_servers: 'All + custom MCP',
    sectors: 'All + custom sector models',
    color: 'var(--lq-amber)',
    features: [
      { text: 'Unlimited Scale', included: true },
      { text: 'Unlimited AI Decisions', included: true },
      { text: 'Custom Sector Models', included: true },
      { text: 'Dedicated Success Manager', included: true },
      { text: 'SLA Guarantee 99.99%', included: true },
      { text: 'On-premise Deployment', included: true },
    ]
  }
];

export default function BillingView() {
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const { data: status, isLoading: _statusLoading } = useQuery({
    queryKey: ['billing', 'status'],
    queryFn: async () => {
      const res = await apiClient.get('/billing/status');
      return res.data;
    }
  });

  const subscribeMutation = useMutation({
    mutationFn: async (planId: string) => {
      const res = await apiClient.post('/billing/subscribe', {
        plan_tier: planId,
        trial_days: 14
      });
      return res.data;
    },
    onSuccess: (data) => {
      toast.success(`Subscription activated: ${data.plan_tier}`, {
        description: "Welcome to LogistiQ AI Premium."
      });
      queryClient.invalidateQueries({ queryKey: ['billing', 'status'] });
      setSelectedPlanId(null);
    },
    onError: () => {
      toast.error("Subscription failed", {
        description: "Please try again or contact support."
      });
    }
  });

  const handleSubscribe = (planId: string) => {
    if (planId === 'enterprise') {
      toast.info("Sales Inquiry", {
        description: "An Enterprise specialist will contact you shortly."
      });
      return;
    }
    setSelectedPlanId(planId);
    setIsModalOpen(true);
  };

  const handlePaymentSuccess = () => {
    if (selectedPlanId) {
      subscribeMutation.mutate(selectedPlanId);
    }
  };

  const currentTier = status?.plan_tier || 'starter';
  const isActive = status?.status === 'subscribed' || status?.status === 'trialing';
  const activePlan = PLANS.find(p => p.id === selectedPlanId);

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-[var(--lq-bg)] overflow-y-auto">
      <div className="p-8 max-w-7xl mx-auto w-full space-y-12">
        
        {/* Header Section */}
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
          <div className="space-y-2">
            <h1 className="text-3xl font-bold text-[var(--lq-text-bright)] tracking-tight">Subscription & Billing</h1>
            <p className="text-[var(--lq-text)] max-w-2xl">
              Scale your logistics intelligence with precision. Choose a plan that aligns with your operational throughput and AI decision requirements.
            </p>
          </div>
          
          <Card className="bg-[var(--lq-surface)] border-[var(--lq-border)] shadow-sm shrink-0 min-w-[300px]">
            <CardContent className="p-4 flex items-center gap-4">
              <div className={cn(
                "w-10 h-10 rounded-full flex items-center justify-center",
                isActive ? "bg-[var(--lq-green)]/10 text-[var(--lq-green)]" : "bg-[var(--lq-text-dim)]/10 text-[var(--lq-text-dim)]"
              )}>
                {isActive ? <BadgeCheck size={24} /> : <AlertCircle size={24} />}
              </div>
              <div>
                <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--lq-text-dim)]">Current Status</div>
                <div className="flex items-center gap-2">
                  <span className="text-lg font-bold text-[var(--lq-text-bright)] capitalize">{currentTier}</span>
                  <Badge variant={isActive ? "outline" : "secondary"} className={cn(
                    "text-[10px] uppercase font-mono",
                    isActive && "border-[var(--lq-green)] text-[var(--lq-green)]"
                  )}>
                    {status?.status || 'No Active Plan'}
                  </Badge>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <Separator className="bg-[var(--lq-border)]" />

        {/* Pricing Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {PLANS.map((plan) => (
            <Card 
              key={plan.id} 
              className={cn(
                "relative flex flex-col transition-all duration-300 hover:shadow-xl hover:-translate-y-1 bg-[var(--lq-surface)] border-[var(--lq-border)]",
                plan.popular && "border-2 border-[var(--lq-purple)] shadow-md"
              )}
            >
              {plan.popular && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-[var(--lq-purple)] text-white text-[10px] font-bold uppercase tracking-widest px-3 py-1 rounded-full shadow-lg">
                  Most Popular
                </div>
              )}

              <CardHeader>
                <div className="flex justify-between items-start mb-2">
                  <CardTitle className="text-xl font-bold text-[var(--lq-text-bright)]">{plan.name}</CardTitle>
                  <div className="p-2 rounded-lg bg-[var(--lq-surface-2)]" style={{ color: plan.color }}>
                    {plan.id === 'starter' && <Zap size={20} />}
                    {plan.id === 'pro' && <TrendingUp size={20} />}
                    {plan.id === 'enterprise' && <Globe size={20} />}
                  </div>
                </div>
                <div className="flex items-baseline gap-1">
                  <span className="text-3xl font-bold text-[var(--lq-text-bright)]">{plan.price_inr}</span>
                  <span className="text-[var(--lq-text-dim)] font-medium text-sm">/mo</span>
                </div>
                <CardDescription className="text-xs font-medium text-[var(--lq-text)] pt-1">
                  Equivalent to {plan.price_usd}
                </CardDescription>
              </CardHeader>

              <CardContent className="flex-1 space-y-6">
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-xs text-[var(--lq-text)] font-medium">
                    <Package size={14} className="text-[var(--lq-text-dim)]" />
                    {plan.limit}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-[var(--lq-text)] font-medium">
                    <Terminal size={14} className="text-[var(--lq-text-dim)]" />
                    {plan.decision_cost}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-[var(--lq-text)] font-medium">
                    <Cloud size={14} className="text-[var(--lq-text-dim)]" />
                    {plan.mcp_servers}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-[var(--lq-text)] font-medium">
                    <Factory size={14} className="text-[var(--lq-text-dim)]" />
                    {plan.sectors}
                  </div>
                </div>

                <Separator className="bg-[var(--lq-border)]" />

                <ul className="space-y-3">
                  {plan.features.map((feature, i) => (
                    <li key={i} className={cn(
                      "flex items-center gap-3 text-sm",
                      feature.included ? "text-[var(--lq-text)]" : "text-[var(--lq-text-dim)] opacity-50"
                    )}>
                      <Check size={16} className={cn(
                        "shrink-0",
                        feature.included ? "text-[var(--lq-green)]" : "text-[var(--lq-text-dim)]"
                      )} />
                      {feature.text}
                    </li>
                  ))}
                </ul>
              </CardContent>

              <CardFooter className="pt-6">
                <Button 
                  className={cn(
                    "w-full h-11 font-bold transition-all",
                    plan.popular 
                      ? "bg-[var(--lq-purple)] hover:bg-[var(--lq-purple)]/90 text-white shadow-lg shadow-purple-500/20" 
                      : "bg-[var(--lq-surface-2)] hover:bg-[var(--lq-border)] text-[var(--lq-text-bright)]",
                    currentTier === plan.id && "bg-[var(--lq-green)] hover:bg-[var(--lq-green)]/90 text-white pointer-events-none"
                  )}
                  onClick={() => handleSubscribe(plan.id)}
                  disabled={subscribeMutation.isPending && selectedPlanId === plan.id}
                >
                  {subscribeMutation.isPending && selectedPlanId === plan.id ? (
                    <>
                      <Loader2 size={18} className="mr-2 animate-spin" />
                      Processing...
                    </>
                  ) : currentTier === plan.id ? (
                    <>
                      <BadgeCheck size={18} className="mr-2" />
                      Current Plan
                    </>
                  ) : plan.id === 'enterprise' ? (
                    "Contact Sales"
                  ) : (
                    "Subscribe Now"
                  )}
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>

        {/* FAQ / Trust Section */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 pt-8">
          <div className="flex flex-col items-center text-center space-y-3 p-6 bg-[var(--lq-surface-2)] rounded-xl border border-[var(--lq-border)]">
            <div className="w-12 h-12 rounded-full bg-white flex items-center justify-center text-[var(--lq-cyan)] shadow-sm">
              <Shield size={24} />
            </div>
            <h3 className="font-bold text-[var(--lq-text-bright)]">Secure Checkout</h3>
            <p className="text-xs text-[var(--lq-text)]">
              Powered by Razorpay. 256-bit encrypted transactions with multiple payment methods support.
            </p>
          </div>
          <div className="flex flex-col items-center text-center space-y-3 p-6 bg-[var(--lq-surface-2)] rounded-xl border border-[var(--lq-border)]">
            <div className="w-12 h-12 rounded-full bg-white flex items-center justify-center text-[var(--lq-purple)] shadow-sm">
              <CreditCard size={24} />
            </div>
            <h3 className="font-bold text-[var(--lq-text-bright)]">Flexible Billing</h3>
            <p className="text-xs text-[var(--lq-text)]">
              Upgrade, downgrade, or cancel at any time. We prorate your usage for fair and transparent billing.
            </p>
          </div>
          <div className="flex flex-col items-center text-center space-y-3 p-6 bg-[var(--lq-surface-2)] rounded-xl border border-[var(--lq-border)]">
            <div className="w-12 h-12 rounded-full bg-white flex items-center justify-center text-[var(--lq-amber)] shadow-sm">
              <Users size={24} />
            </div>
            <h3 className="font-bold text-[var(--lq-text-bright)]">Global Support</h3>
            <p className="text-xs text-[var(--lq-text)]">
              24/7 dedicated support for Pro and Enterprise users to ensure zero downtime for your logistics operations.
            </p>
          </div>
        </div>

        {/* Bottom Banner */}
        <div className="bg-gradient-to-r from-[var(--lq-cyan)] to-[var(--lq-purple)] rounded-2xl p-8 text-white flex flex-col md:flex-row items-center justify-between gap-8 shadow-2xl relative overflow-hidden">
          <div className="absolute top-0 right-0 w-64 h-64 bg-white/10 rounded-full -mr-32 -mt-32 blur-3xl" />
          <div className="absolute bottom-0 left-0 w-64 h-64 bg-black/10 rounded-full -ml-32 -mb-32 blur-3xl" />
          
          <div className="space-y-2 relative z-10">
            <h2 className="text-2xl font-bold">Ready to automate your supply chain?</h2>
            <p className="text-white/80 max-w-md">
              Join 200+ global logistics companies using LogistiQ AI to reduce costs by 22% on average.
            </p>
          </div>
          <Button variant="outline" className="bg-white text-[var(--lq-text-bright)] border-none hover:bg-white/90 font-bold px-8 h-12 relative z-10">
            Request Custom Demo <ExternalLink size={16} className="ml-2" />
          </Button>
        </div>
      </div>

      <RazorpayDemoModal 
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={handlePaymentSuccess}
        planName={activePlan?.name || ''}
        amount={activePlan?.price_inr || ''}
      />
    </div>
  );
}
