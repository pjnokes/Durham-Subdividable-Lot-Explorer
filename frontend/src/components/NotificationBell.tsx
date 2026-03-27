import { useState, useRef, useEffect } from "react";

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [subdividableOnly, setSubdividableOnly] = useState(true);
  const [maxPrice, setMaxPrice] = useState("");
  const [subscribed, setSubscribed] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleSubscribe = () => {
    if (!email.trim()) return;
    setSubscribed(true);
    setTimeout(() => setSubscribed(false), 5000);
  };

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        onClick={() => setOpen((p) => !p)}
        className="relative bg-slate-800/80 hover:bg-slate-700 backdrop-blur border border-slate-600 rounded-lg p-1.5 transition-colors"
        title="Listing Alerts"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-slate-300"
        >
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-amber-400 rounded-full" />
      </button>

      {open && (
        <div className="absolute top-full right-0 mt-2 w-80 bg-slate-900/[0.98] backdrop-blur-lg border border-slate-700 rounded-xl shadow-2xl overflow-hidden z-[60]">
          <div className="px-5 py-4">
            <div className="flex items-center gap-2 mb-3">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-amber-400"
              >
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                <path d="M13.73 21a2 2 0 0 1-3.46 0" />
              </svg>
              <h3 className="font-semibold text-white text-sm">
                Listing Alerts
              </h3>
            </div>

            <div className="mb-3 px-2.5 py-1.5 bg-amber-500/10 border border-amber-500/30 rounded-lg flex items-center gap-2">
              <span className="text-amber-400 text-xs font-medium">Demo</span>
              <span className="text-[11px] text-amber-400/80">This feature is not yet connected — UI preview only.</span>
            </div>

            <p className="text-xs text-slate-400 mb-4 leading-relaxed">
              Get notified when new subdividable lots hit the market in Durham.
              We'll send a daily digest of new listings matching your criteria.
            </p>

            {subscribed ? (
              <div className="p-3 bg-green-500/10 border border-green-500/30 rounded-lg text-center">
                <span className="text-green-400 font-medium text-sm">
                  ✓ Subscribed!
                </span>
                <p className="text-[11px] text-green-400/70 mt-1">
                  You'll receive your first digest tomorrow morning.
                </p>
              </div>
            ) : (
              <>
                <div className="space-y-3">
                  <div>
                    <label className="block text-[11px] text-slate-400 mb-1">
                      Email address
                    </label>
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@example.com"
                      className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
                    />
                  </div>

                  <label className="flex items-center gap-2.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={subdividableOnly}
                      onChange={(e) => setSubdividableOnly(e.target.checked)}
                      className="w-4 h-4 rounded border-slate-600 bg-slate-800 accent-amber-500"
                    />
                    <span className="text-xs text-slate-300">
                      Subdividable lots only
                    </span>
                  </label>

                  <div>
                    <label className="block text-[11px] text-slate-400 mb-1">
                      Max price (optional)
                    </label>
                    <input
                      type="text"
                      value={maxPrice}
                      onChange={(e) => setMaxPrice(e.target.value)}
                      placeholder="e.g. 300000"
                      className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
                    />
                  </div>

                  <button
                    onClick={handleSubscribe}
                    disabled={!email.trim()}
                    className="w-full bg-amber-500 hover:bg-amber-400 disabled:bg-slate-700 disabled:text-slate-500 text-black font-medium py-2.5 rounded-lg text-sm transition-colors"
                  >
                    Subscribe to Alerts
                  </button>
                </div>

                <p className="text-[10px] text-slate-500 mt-3 text-center">
                  Daily digest · Unsubscribe anytime
                </p>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
