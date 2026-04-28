import { useState, useEffect, useCallback } from 'react';
import {
  X, ShieldCheck, CreditCard, Smartphone,
  ChevronRight, Building, CheckCircle2, Loader2, ChevronLeft,
} from 'lucide-react';
import {
  Dialog, DialogContent,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

interface RazorpayDemoModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  planName: string;
  amount: string;
}

// ── Try loading the real Razorpay SDK ──
function loadRazorpayScript(): Promise<boolean> {
  return new Promise((resolve) => {
    if ((window as any).Razorpay) { resolve(true); return; }
    const s = document.createElement('script');
    s.src = 'https://checkout.razorpay.com/v1/checkout.js';
    s.onload = () => resolve(true);
    s.onerror = () => resolve(false);
    document.body.appendChild(s);
  });
}

type Step = 'methods' | 'card' | 'upi' | 'netbanking' | 'processing' | 'success';

const BANKS = [
  'State Bank of India', 'HDFC Bank', 'ICICI Bank', 'Axis Bank',
  'Kotak Mahindra Bank', 'Bank of Baroda', 'Punjab National Bank', 'Yes Bank',
];

export function RazorpayDemoModal({
  isOpen, onClose, onSuccess, planName, amount,
}: RazorpayDemoModalProps) {
  const [step, setStep] = useState<Step>('methods');
  const [cardNum, setCardNum] = useState('');
  const [cardExp, setCardExp] = useState('');
  const [cardCvv, setCardCvv] = useState('');
  const [cardName, setCardName] = useState('');
  const [upiId, setUpiId] = useState('');
  const [selectedBank, setSelectedBank] = useState('');

  // Reset state when modal opens/closes
  useEffect(() => {
    if (!isOpen) {
      setStep('methods');
      setCardNum(''); setCardExp(''); setCardCvv(''); setCardName('');
      setUpiId(''); setSelectedBank('');
    }
  }, [isOpen]);

  // Try real Razorpay SDK first
  const tryRealRazorpay = useCallback(async () => {
    const key = import.meta.env.VITE_RAZORPAY_KEY_ID as string | undefined;
    if (!key) return false;

    const loaded = await loadRazorpayScript();
    if (!loaded || !(window as any).Razorpay) return false;

    const numericAmount = parseInt(amount.replace(/[^\d]/g, ''), 10) * 100; // paise
    return new Promise<boolean>((resolve) => {
      const rzp = new (window as any).Razorpay({
        key,
        amount: numericAmount || 1500000,
        currency: 'INR',
        name: 'LogistiQ AI',
        description: `${planName} Subscription`,
        handler: () => { resolve(true); },
        modal: { ondismiss: () => resolve(false) },
        prefill: { name: 'Test User', email: 'test@logistiq.ai' },
        theme: { color: '#0891b2' },
      });
      rzp.open();
    });
  }, [amount, planName]);

  // Attempt real Razorpay on open
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    (async () => {
      const used = await tryRealRazorpay();
      if (cancelled) return;
      if (used) {
        onSuccess();
        onClose();
      }
      // If not used, the demo modal UI is shown (already visible)
    })();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const processPayment = () => {
    setStep('processing');
    setTimeout(() => {
      setStep('success');
      setTimeout(() => {
        onSuccess();
        onClose();
      }, 2000);
    }, 2500);
  };

  // Card number formatter
  const formatCardNum = (val: string) => {
    const digits = val.replace(/\D/g, '').slice(0, 16);
    return digits.replace(/(\d{4})/g, '$1 ').trim();
  };
  const formatExp = (val: string) => {
    const digits = val.replace(/\D/g, '').slice(0, 4);
    if (digits.length >= 3) return digits.slice(0, 2) + '/' + digits.slice(2);
    return digits;
  };

  const canPayCard = cardNum.replace(/\s/g, '').length >= 15 && cardExp.length >= 4 && cardCvv.length >= 3 && cardName.length > 2;
  const canPayUpi = /^[\w.-]+@[\w]+$/.test(upiId);

  const methods = [
    { id: 'card' as Step, name: 'Card', icon: <CreditCard size={18} />, sub: 'Visa, Mastercard, RuPay' },
    { id: 'upi' as Step, name: 'UPI', icon: <Smartphone size={18} />, sub: 'Google Pay, PhonePe, BHIM' },
    { id: 'netbanking' as Step, name: 'Netbanking', icon: <Building size={18} />, sub: 'All Indian Banks' },
  ];

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[420px] p-0 overflow-hidden border-none shadow-2xl rounded-xl">

        {/* ── Razorpay-style Header ── */}
        <div className="bg-[#1e2330] p-5 text-white relative">
          <button
            onClick={onClose}
            className="absolute top-4 right-4 text-white/50 hover:text-white transition-colors"
          >
            <X size={18} />
          </button>

          <div className="flex items-center gap-3 mb-5">
            <div className="w-9 h-9 bg-[#0891b2] rounded flex items-center justify-center font-bold text-lg">L</div>
            <div>
              <h3 className="font-bold text-base leading-tight">LogistiQ AI</h3>
              <p className="text-[9px] text-white/50 uppercase tracking-[0.15em] font-mono">Subscription Payment</p>
            </div>
          </div>

          <div className="flex justify-between items-end">
            <div>
              <p className="text-[9px] text-white/40 uppercase tracking-wider mb-0.5">Paying for</p>
              <p className="font-medium text-sm">{planName} Plan</p>
            </div>
            <div className="text-right">
              <p className="text-[9px] text-white/40 uppercase tracking-wider mb-0.5">Amount</p>
              <p className="font-bold text-xl">{amount}<span className="text-xs text-white/50 ml-1">/mo</span></p>
            </div>
          </div>
        </div>

        {/* ── Body ── */}
        <div className="bg-white min-h-[360px] flex flex-col">

          {/* ── Method Selection ── */}
          {step === 'methods' && (
            <div className="p-5 space-y-3 flex-1 flex flex-col">
              <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">Select Payment Method</h4>
              {methods.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setStep(m.id)}
                  className="w-full flex items-center justify-between p-4 rounded-lg border border-slate-100 hover:border-[#0891b2]/40 hover:bg-[#0891b2]/5 transition-all text-left group"
                >
                  <div className="flex items-center gap-4">
                    <div className="text-slate-400 group-hover:text-[#0891b2] transition-colors">{m.icon}</div>
                    <div>
                      <p className="text-sm font-bold text-slate-800">{m.name}</p>
                      <p className="text-[10px] text-slate-400">{m.sub}</p>
                    </div>
                  </div>
                  <ChevronRight size={16} className="text-slate-300 group-hover:text-[#0891b2]" />
                </button>
              ))}
              <div className="mt-auto flex items-center justify-center gap-2 pt-4 text-[10px] text-slate-400">
                <ShieldCheck size={12} className="text-green-500" />
                <span>Secured by <strong>Razorpay</strong> · 256-bit SSL</span>
              </div>
            </div>
          )}

          {/* ── Card Form ── */}
          {step === 'card' && (
            <div className="p-5 flex-1 flex flex-col">
              <button onClick={() => setStep('methods')} className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 mb-4 self-start">
                <ChevronLeft size={14} /> Back
              </button>
              <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-4">Enter Card Details</h4>
              <div className="space-y-3 flex-1">
                <div>
                  <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Card Number</label>
                  <input
                    type="text"
                    placeholder="4111 1111 1111 1111"
                    value={cardNum}
                    onChange={(e) => setCardNum(formatCardNum(e.target.value))}
                    className="w-full mt-1 px-3 py-2.5 border border-slate-200 rounded-lg text-sm font-mono text-slate-800 focus:outline-none focus:border-[#0891b2] focus:ring-2 focus:ring-[#0891b2]/20"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Cardholder Name</label>
                  <input
                    type="text"
                    placeholder="Test User"
                    value={cardName}
                    onChange={(e) => setCardName(e.target.value)}
                    className="w-full mt-1 px-3 py-2.5 border border-slate-200 rounded-lg text-sm text-slate-800 focus:outline-none focus:border-[#0891b2] focus:ring-2 focus:ring-[#0891b2]/20"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Expiry</label>
                    <input
                      type="text"
                      placeholder="12/28"
                      value={cardExp}
                      onChange={(e) => setCardExp(formatExp(e.target.value))}
                      className="w-full mt-1 px-3 py-2.5 border border-slate-200 rounded-lg text-sm font-mono text-slate-800 focus:outline-none focus:border-[#0891b2] focus:ring-2 focus:ring-[#0891b2]/20"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">CVV</label>
                    <input
                      type="password"
                      placeholder="•••"
                      maxLength={4}
                      value={cardCvv}
                      onChange={(e) => setCardCvv(e.target.value.replace(/\D/g, ''))}
                      className="w-full mt-1 px-3 py-2.5 border border-slate-200 rounded-lg text-sm font-mono text-slate-800 focus:outline-none focus:border-[#0891b2] focus:ring-2 focus:ring-[#0891b2]/20"
                    />
                  </div>
                </div>
              </div>
              <button
                disabled={!canPayCard}
                onClick={processPayment}
                className="w-full mt-4 bg-[#3395ff] hover:bg-[#2d84e4] disabled:opacity-40 disabled:cursor-not-allowed text-white h-11 font-bold text-sm rounded-lg shadow-lg shadow-blue-500/20 transition-all"
              >
                Pay {amount}
              </button>
              <p className="text-[9px] text-slate-400 text-center mt-2">Test card: 4111 1111 1111 1111 · Exp: 12/28 · CVV: 123</p>
            </div>
          )}

          {/* ── UPI Form ── */}
          {step === 'upi' && (
            <div className="p-5 flex-1 flex flex-col">
              <button onClick={() => setStep('methods')} className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 mb-4 self-start">
                <ChevronLeft size={14} /> Back
              </button>
              <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-4">Enter UPI ID</h4>
              <div className="space-y-4 flex-1">
                <div>
                  <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">UPI ID / VPA</label>
                  <input
                    type="text"
                    placeholder="testuser@upi"
                    value={upiId}
                    onChange={(e) => setUpiId(e.target.value)}
                    className="w-full mt-1 px-3 py-2.5 border border-slate-200 rounded-lg text-sm font-mono text-slate-800 focus:outline-none focus:border-[#0891b2] focus:ring-2 focus:ring-[#0891b2]/20"
                  />
                </div>
                <div className="flex items-center gap-3 px-3 py-2.5 bg-slate-50 rounded-lg border border-slate-100">
                  <Smartphone size={16} className="text-slate-400" />
                  <p className="text-[10px] text-slate-500">A payment request will be sent to your UPI app for approval.</p>
                </div>
              </div>
              <button
                disabled={!canPayUpi}
                onClick={processPayment}
                className="w-full mt-4 bg-[#3395ff] hover:bg-[#2d84e4] disabled:opacity-40 disabled:cursor-not-allowed text-white h-11 font-bold text-sm rounded-lg shadow-lg shadow-blue-500/20 transition-all"
              >
                Verify & Pay {amount}
              </button>
              <p className="text-[9px] text-slate-400 text-center mt-2">Test UPI: testuser@upi</p>
            </div>
          )}

          {/* ── Netbanking ── */}
          {step === 'netbanking' && (
            <div className="p-5 flex-1 flex flex-col">
              <button onClick={() => setStep('methods')} className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 mb-4 self-start">
                <ChevronLeft size={14} /> Back
              </button>
              <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-3">Select Your Bank</h4>
              <div className="space-y-1.5 flex-1 overflow-y-auto max-h-[220px]">
                {BANKS.map((bank) => (
                  <button
                    key={bank}
                    onClick={() => setSelectedBank(bank)}
                    className={cn(
                      "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border text-left text-sm transition-all",
                      selectedBank === bank
                        ? 'border-[#0891b2] bg-[#0891b2]/5 text-[#0891b2] font-semibold'
                        : 'border-slate-100 text-slate-700 hover:border-slate-300'
                    )}
                  >
                    <Building size={14} className={selectedBank === bank ? 'text-[#0891b2]' : 'text-slate-400'} />
                    {bank}
                  </button>
                ))}
              </div>
              <button
                disabled={!selectedBank}
                onClick={processPayment}
                className="w-full mt-4 bg-[#3395ff] hover:bg-[#2d84e4] disabled:opacity-40 disabled:cursor-not-allowed text-white h-11 font-bold text-sm rounded-lg shadow-lg shadow-blue-500/20 transition-all"
              >
                Pay via {selectedBank || 'Netbanking'}
              </button>
            </div>
          )}

          {/* ── Processing ── */}
          {step === 'processing' && (
            <div className="flex-1 flex flex-col items-center justify-center space-y-5 p-8">
              <div className="relative">
                <div className="w-16 h-16 border-4 border-slate-100 rounded-full" />
                <Loader2 className="w-16 h-16 text-[#3395ff] animate-spin absolute top-0 left-0" />
              </div>
              <div className="text-center">
                <h4 className="font-bold text-slate-800 text-lg mb-1">Processing Payment</h4>
                <p className="text-xs text-slate-400">Verifying with your bank...</p>
              </div>
              <div className="w-full max-w-[200px] h-1 bg-slate-100 rounded-full overflow-hidden">
                <div className="h-full bg-[#3395ff] rounded-full animate-pulse" style={{ width: '70%' }} />
              </div>
            </div>
          )}

          {/* ── Success ── */}
          {step === 'success' && (
            <div className="flex-1 flex flex-col items-center justify-center space-y-5 p-8">
              <div className="w-16 h-16 bg-green-100 text-green-500 rounded-full flex items-center justify-center">
                <CheckCircle2 size={32} />
              </div>
              <div className="text-center">
                <h4 className="font-bold text-slate-800 text-lg mb-1">Payment Successful!</h4>
                <p className="text-xs text-slate-400 mb-2">Transaction ID: TXN{Date.now().toString().slice(-8)}</p>
                <p className="text-xs text-slate-500">{amount} charged to your account</p>
              </div>
              <div className="flex items-center gap-2 text-[10px] text-green-600 font-semibold bg-green-50 px-3 py-1.5 rounded-full">
                <ShieldCheck size={12} />
                Verified by Razorpay
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
