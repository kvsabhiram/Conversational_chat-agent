import { useState, useRef, useEffect } from "react";

const API_URL = "http://localhost:5000";

const SECTORS = [
  { id: "retail", name: "Retail", icon: "🛒", agent: "Priya" },
  { id: "education", name: "Education", icon: "🎓", agent: "Arjun" },
  { id: "medical", name: "Medical", icon: "🏥", agent: "Dr. Meera" },
  { id: "real_estate", name: "Real Estate", icon: "🏠", agent: "Vikram" },
  { id: "banking", name: "Banking", icon: "🏦", agent: "Ananya" },
  { id: "tourism", name: "Tourism", icon: "✈️", agent: "Riya" },
];

const SUGGESTIONS = {
  retail: ["Where is my order #12345?", "I want a refund", "Return policy?"],
  education: ["What courses do you offer?", "How do I apply?", "Scholarship info"],
  medical: ["Book appointment with cardiologist", "Is Dr. Sharma available?", "Collect my reports"],
  real_estate: ["2BHK in Gachibowli under 80L", "Schedule site visit", "EMI for 60L loan"],
  banking: ["Home loan EMI for 50 lakhs", "Loan eligibility check", "Dispute a transaction"],
  tourism: ["5-day trip to Goa", "Hotels in Manali under 5000", "Visa for Thailand?"],
};

export default function ChatPlayground() {
  const [sector, setSector] = useState(SECTORS[0]);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [stats, setStats] = useState({});
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);
  useEffect(() => { inputRef.current?.focus(); }, [sector]);

  const switchSector = (s) => {
    setSector(s);
    setMessages([]);
    setSessionId(null);
    setStats({});
  };

  const send = async (text) => {
    const msg = (text || input).trim();
    if (!msg || loading) return;
    setInput("");
    setMessages((p) => [...p, { role: "user", text: msg }]);
    setLoading(true);
    // eslint-disable-next-line react-hooks/purity -- runs only inside this event handler, never during render
    const t0 = performance.now();

    let botIndex = -1;
    const ensureBotMessage = () => {
      if (botIndex !== -1) return;
      setMessages((p) => {
        botIndex = p.length;
        return [...p, { role: "bot", text: "" }];
      });
    };
    const patchBotMessage = (patch) => {
      setMessages((p) => {
        if (botIndex === -1 || !p[botIndex]) return p;
        const next = [...p];
        next[botIndex] = { ...next[botIndex], ...patch };
        return next;
      });
    };

    try {
      const res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, session_id: sessionId, sector: sector.id, stream: true }),
      });
      if (!res.ok || !res.body) throw new Error("bad response");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let replyText = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const raw = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const line = raw.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;

          let evt;
          try {
            evt = JSON.parse(line.slice(5).trim());
          } catch {
            continue;
          }

          if (evt.type === "start") {
            if (evt.session_id) setSessionId(evt.session_id);
          } else if (evt.type === "chunk") {
            replyText += (replyText ? " " : "") + evt.text;
            ensureBotMessage();
            patchBotMessage({ text: replyText });
          } else if (evt.type === "done") {
            // eslint-disable-next-line react-hooks/purity -- runs only inside this event handler, never during render
            const lat = Math.round(performance.now() - t0);
            if (evt.session_id) setSessionId(evt.session_id);
            setStats({ intent: evt.intent, confidence: evt.confidence, latency: lat, sources: evt.sources });
            ensureBotMessage();
            patchBotMessage({ text: evt.reply, intent: evt.intent, confidence: evt.confidence, escalated: evt.escalated });
          } else if (evt.type === "error") {
            ensureBotMessage();
            patchBotMessage({ text: replyText || "Something went wrong. Please try again.", error: true });
          }
        }
      }
    } catch {
      if (botIndex === -1) {
        setMessages((p) => [...p, { role: "bot", text: "Connection error. Is the server running on localhost:5000?", error: true }]);
      } else {
        patchBotMessage({ text: "Connection error. Is the server running on localhost:5000?", error: true });
      }
    }
    setLoading(false);
    inputRef.current?.focus();
  };

  const clearChat = async () => {
    if (sessionId) { try { await fetch(`${API_URL}/api/session/${sessionId}`, { method: "DELETE" }); } catch { /* best-effort, ignore */ } }
    setMessages([]);
    setSessionId(null);
    setStats({});
  };

  return (
    <div style={S.root}>
      <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />

      {sidebarOpen && (
        <div style={S.sidebar}>
          <div style={S.sidebarHead}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={S.logo}>A</div>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: "#1F2937" }}>Agent Platform</div>
                <div style={{ fontSize: 11, color: "#9CA3AF" }}>6 sector AI agents</div>
              </div>
            </div>
          </div>

          <div style={{ padding: 10, flex: 1 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: "0.08em", padding: "8px 12px" }}>Sectors</div>
            {SECTORS.map((s) => {
              const active = sector.id === s.id;
              return (
                <button key={s.id} onClick={() => switchSector(s)} style={{ ...S.sectorBtn, ...(active ? S.sectorActive : {}) }}>
                  <span style={{ fontSize: 16, width: 26, textAlign: "center" }}>{s.icon}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: active ? 600 : 400 }}>{s.name}</div>
                    <div style={{ fontSize: 11, color: active ? "#7C5CFC" : "#9CA3AF", opacity: 0.8 }}>{s.agent}</div>
                  </div>
                  {active && <div style={{ width: 6, height: 6, borderRadius: 3, background: "#22C55E" }} />}
                </button>
              );
            })}
          </div>

          <div style={S.sidebarFoot}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 7, height: 7, borderRadius: 4, background: "#22C55E" }} />
              <span style={{ fontSize: 11, color: "#6B7280" }}>LLM connected</span>
            </div>
            <span style={{ fontSize: 10, color: "#9CA3AF" }}>Phase 3</span>
          </div>
        </div>
      )}

      <div style={S.main}>
        <div style={S.header}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <button onClick={() => setSidebarOpen(!sidebarOpen)} style={S.toggleBtn}>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 4h12M2 8h12M2 12h12" stroke="#6B7280" strokeWidth="1.5" strokeLinecap="round"/></svg>
            </button>
            <div style={S.headerDot}>{sector.icon}</div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, color: "#1F2937" }}>{sector.name}</div>
              <div style={{ fontSize: 12, color: "#9CA3AF" }}>Chatting with {sector.agent}</div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {sessionId && <div style={S.sessionTag}>{sessionId.slice(0, 8)}</div>}
            <button onClick={clearChat} style={S.newChatBtn}>New chat</button>
          </div>
        </div>

        <div style={S.chatArea}>
          {messages.length === 0 && (
            <div style={S.emptyState}>
              <div style={S.emptyIcon}>{sector.icon}</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: "#1F2937", marginBottom: 6 }}>Chat with {sector.agent}</div>
              <div style={{ fontSize: 14, color: "#9CA3AF", maxWidth: 380, lineHeight: 1.6 }}>
                {sector.id === "retail" && "Ask about orders, refunds, returns, or product inquiries"}
                {sector.id === "education" && "Ask about courses, admissions, fees, or placements"}
                {sector.id === "medical" && "Book appointments, check availability, or ask about services"}
                {sector.id === "real_estate" && "Search properties, schedule visits, or calculate EMI"}
                {sector.id === "banking" && "Check loan eligibility, EMI, cards, or account queries"}
                {sector.id === "tourism" && "Plan trips, find hotels, get visa guidance, or budgets"}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center", marginTop: 20 }}>
                {(SUGGESTIONS[sector.id] || []).map((q) => (
                  <button key={q} onClick={() => send(q)} style={S.suggestBtn}>{q}</button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start", marginBottom: 16 }}>
              <div style={{ maxWidth: "72%" }}>
                {m.role === "bot" && (
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5 }}>
                    <div style={S.botAvatar}>{sector.icon}</div>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "#6B7280" }}>{sector.agent}</span>
                  </div>
                )}
                <div style={{
                  padding: "12px 16px",
                  borderRadius: m.role === "user" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
                  background: m.role === "user" ? "#7C5CFC" : "#e7e7ee",
                  color: m.role === "user" ? "#fff" : "#1F2937",
                  fontSize: 14, lineHeight: 1.7,
                  ...(m.error && { background: "#FEF2F2", color: "#991B1B", border: "1px solid #FECACA" }),
                  ...(m.escalated && { background: "#FFFBEB", color: "#92400E", border: "1px solid #FDE68A" }),
                }}>
                  {m.text}
                </div>
                {m.role === "bot" && m.intent && (
                  <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                    <span style={S.intentTag}>{m.intent}</span>
                    <span style={S.confTag}>{(m.confidence * 100).toFixed(0)}%</span>
                    {m.escalated && <span style={S.escTag}>escalated</span>}
                  </div>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div style={{ display: "flex", marginBottom: 16 }}>
              <div style={{ maxWidth: "72%" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5 }}>
                  <div style={S.botAvatar}>{sector.icon}</div>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "#6B7280" }}>{sector.agent}</span>
                </div>
                <div style={{ padding: "14px 18px", borderRadius: "14px 14px 14px 4px", background: "#e7e7ee" }}>
                  <div style={{ display: "flex", gap: 5 }}>
                    {[0, 1, 2].map((d) => (
                      <div key={d} style={{ width: 8, height: 8, borderRadius: 4, background: "#9CA3AF", animation: `dotPulse 1.4s ease-in-out ${d * 0.2}s infinite` }} />
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        <div style={S.inputArea}>
          {stats.intent && (
            <div style={S.statsBar}>
              <span>intent: <b style={{ color: "#7C5CFC" }}>{stats.intent}</b></span>
              <span>confidence: <b>{(stats.confidence * 100).toFixed(0)}%</b></span>
              {stats.latency && <span>latency: <b>{stats.latency}ms</b></span>}
              {stats.sources && <span>sources: <b>{stats.sources.length}</b></span>}
            </div>
          )}
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder={`Message ${sector.agent}...`}
              style={S.input}
            />
            <button onClick={() => send()} disabled={loading || !input.trim()} style={{ ...S.sendBtn, opacity: loading || !input.trim() ? 0.4 : 1 }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M5 12h14M13 6l6 6-6 6" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </button>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes dotPulse { 0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; } 40% { transform: scale(1); opacity: 1; } }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #E5E7EB; border-radius: 3px; }
        input::placeholder { color: #9CA3AF; }
        input:focus { border-color: #7C5CFC !important; box-shadow: 0 0 0 3px #EDE9FE !important; }
        button:hover { opacity: 0.85; }
      `}</style>
    </div>
  );
}

const S = {
  root: { display: "flex", height: "100vh", fontFamily: "'Plus Jakarta Sans', sans-serif", background: "#F9FAFB" },
  sidebar: { width: 256, background: "#fff", borderRight: "1px solid #E5E7EB", display: "flex", flexDirection: "column" },
  sidebarHead: { padding: "18px 16px", borderBottom: "1px solid #E5E7EB" },
  logo: { width: 34, height: 34, borderRadius: 10, background: "#7C5CFC", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 16 },
  sidebarFoot: { padding: "12px 16px", borderTop: "1px solid #E5E7EB", display: "flex", justifyContent: "space-between", alignItems: "center" },
  sectorBtn: { width: "100%", display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", border: "none", borderRadius: 10, cursor: "pointer", background: "transparent", color: "#6B7280", fontFamily: "inherit", fontSize: 13, textAlign: "left", transition: "all 0.12s", marginBottom: 2 },
  sectorActive: { background: "#EDE9FE", color: "#7C5CFC" },
  main: { flex: 1, display: "flex", flexDirection: "column", background: "#fff" },
  header: { display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 20px", borderBottom: "1px solid #E5E7EB" },
  headerDot: { width: 36, height: 36, borderRadius: 10, background: "#EDE9FE", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 },
  toggleBtn: { background: "none", border: "1px solid #E5E7EB", borderRadius: 8, padding: "7px 9px", cursor: "pointer", display: "flex", alignItems: "center" },
  sessionTag: { fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: "#9CA3AF", padding: "4px 10px", background: "#F3F4F6", borderRadius: 6, border: "1px solid #E5E7EB" },
  newChatBtn: { background: "#7C5CFC", border: "none", borderRadius: 8, color: "#fff", padding: "8px 16px", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit" },
  chatArea: { flex: 1, overflowY: "auto", padding: "24px 24px" },
  emptyState: { textAlign: "center", marginTop: 60 },
  emptyIcon: { width: 64, height: 64, borderRadius: 20, background: "#EDE9FE", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 28, margin: "0 auto 16px" },
  suggestBtn: { background: "#F9FAFB", border: "1px solid #E5E7EB", borderRadius: 20, color: "#6B7280", padding: "8px 16px", fontSize: 13, cursor: "pointer", fontFamily: "inherit", transition: "all 0.12s" },
  botAvatar: { width: 22, height: 22, borderRadius: 7, background: "#EDE9FE", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11 },
  inputArea: { padding: "12px 20px 16px", borderTop: "1px solid #E5E7EB" },
  statsBar: { display: "flex", gap: 18, marginBottom: 10, fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: "#9CA3AF" },
  input: { flex: 1, background: "#F9FAFB", border: "1px solid #E5E7EB", borderRadius: 12, padding: "13px 18px", color: "#1F2937", fontSize: 14, fontFamily: "inherit", outline: "none", transition: "all 0.15s" },
  sendBtn: { background: "#7C5CFC", border: "none", borderRadius: 12, padding: "13px 18px", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", transition: "all 0.12s" },
  intentTag: { fontSize: 10, fontFamily: "'JetBrains Mono', monospace", padding: "2px 8px", borderRadius: 4, background: "#EDE9FE", color: "#7C5CFC", fontWeight: 500 },
  confTag: { fontSize: 10, fontFamily: "'JetBrains Mono', monospace", padding: "2px 8px", borderRadius: 4, background: "#F3F4F6", color: "#6B7280" },
  escTag: { fontSize: 10, fontFamily: "'JetBrains Mono', monospace", padding: "2px 8px", borderRadius: 4, background: "#FFFBEB", color: "#92400E" },
};
