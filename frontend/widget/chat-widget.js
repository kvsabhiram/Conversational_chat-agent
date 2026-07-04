/**
 * Chat Agent Widget — embeddable chat bubble for client websites.
 *
 * Usage:
 *   <script src="https://your-domain.com/widget/chat-widget.js"
 *           data-api="http://localhost:8000"
 *           data-sector="retail"
 *           data-key="sk-your-api-key"
 *           data-title="ShopEasy Support">
 *   </script>
 */

(function () {
  const script = document.currentScript;
  const API_URL = script.getAttribute("data-api") || "http://localhost:8000";
  const SECTOR = script.getAttribute("data-sector") || "retail";
  const API_KEY = script.getAttribute("data-key") || "";
  const TITLE = script.getAttribute("data-title") || "Chat Support";

  let sessionId = null;
  let isOpen = false;

  // Inject CSS
  const style = document.createElement("style");
  style.textContent = `
    #chat-widget-bubble {
      position: fixed; bottom: 24px; right: 24px; z-index: 99999;
      width: 56px; height: 56px; border-radius: 50%;
      background: #1a1a2e; color: #fff; border: none; cursor: pointer;
      box-shadow: 0 4px 20px rgba(0,0,0,0.25);
      display: flex; align-items: center; justify-content: center;
      font-size: 24px; transition: transform 0.2s;
    }
    #chat-widget-bubble:hover { transform: scale(1.1); }

    #chat-widget-container {
      position: fixed; bottom: 92px; right: 24px; z-index: 99999;
      width: 380px; height: 520px;
      background: #fff; border-radius: 16px;
      box-shadow: 0 8px 40px rgba(0,0,0,0.2);
      display: none; flex-direction: column; overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }
    #chat-widget-container.open { display: flex; }

    .cw-header {
      background: #1a1a2e; color: #fff; padding: 16px 20px;
      font-size: 16px; font-weight: 600;
      display: flex; justify-content: space-between; align-items: center;
    }
    .cw-close { background: none; border: none; color: #fff; font-size: 20px; cursor: pointer; }

    .cw-messages {
      flex: 1; overflow-y: auto; padding: 16px;
      display: flex; flex-direction: column; gap: 12px;
    }

    .cw-msg { max-width: 85%; padding: 10px 14px; border-radius: 12px; font-size: 14px; line-height: 1.5; }
    .cw-msg.user { align-self: flex-end; background: #1a1a2e; color: #fff; border-bottom-right-radius: 4px; }
    .cw-msg.bot { align-self: flex-start; background: #f0f0f5; color: #1a1a2e; border-bottom-left-radius: 4px; }
    .cw-msg.typing { opacity: 0.6; font-style: italic; }

    .cw-input-row {
      display: flex; padding: 12px; border-top: 1px solid #e8e8ed; gap: 8px;
    }
    .cw-input {
      flex: 1; border: 1px solid #ddd; border-radius: 8px; padding: 10px 14px;
      font-size: 14px; outline: none; font-family: inherit;
    }
    .cw-input:focus { border-color: #1a1a2e; }
    .cw-send {
      background: #1a1a2e; color: #fff; border: none; border-radius: 8px;
      padding: 10px 16px; cursor: pointer; font-size: 14px; font-weight: 600;
    }
    .cw-send:disabled { opacity: 0.5; cursor: not-allowed; }
  `;
  document.head.appendChild(style);

  // Build DOM
  const bubble = document.createElement("button");
  bubble.id = "chat-widget-bubble";
  bubble.innerHTML = "💬";
  bubble.onclick = toggleWidget;

  const container = document.createElement("div");
  container.id = "chat-widget-container";
  container.innerHTML = `
    <div class="cw-header">
      <span>${TITLE}</span>
      <button class="cw-close" onclick="document.getElementById('chat-widget-container').classList.remove('open')">✕</button>
    </div>
    <div class="cw-messages" id="cw-messages">
      <div class="cw-msg bot">Hi! How can I help you today?</div>
    </div>
    <div class="cw-input-row">
      <input class="cw-input" id="cw-input" placeholder="Type a message..." onkeydown="if(event.key==='Enter')document.getElementById('cw-send').click()">
      <button class="cw-send" id="cw-send" onclick="window.__cwSend()">Send</button>
    </div>
  `;

  document.body.appendChild(container);
  document.body.appendChild(bubble);

  function toggleWidget() {
    isOpen = !isOpen;
    container.classList.toggle("open", isOpen);
  }

  // Send message
  window.__cwSend = async function () {
    const input = document.getElementById("cw-input");
    const messages = document.getElementById("cw-messages");
    const sendBtn = document.getElementById("cw-send");
    const text = input.value.trim();

    if (!text) return;

    // Show user message
    messages.innerHTML += `<div class="cw-msg user">${escapeHtml(text)}</div>`;
    input.value = "";
    sendBtn.disabled = true;

    // Show typing indicator
    messages.innerHTML += `<div class="cw-msg bot typing" id="cw-typing">Typing...</div>`;
    messages.scrollTop = messages.scrollHeight;

    try {
      const res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
        },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          sector: SECTOR,
        }),
      });

      const data = await res.json();
      sessionId = data.session_id;

      // Remove typing indicator
      const typing = document.getElementById("cw-typing");
      if (typing) typing.remove();

      // Show bot reply
      messages.innerHTML += `<div class="cw-msg bot">${escapeHtml(data.reply)}</div>`;
    } catch (err) {
      const typing = document.getElementById("cw-typing");
      if (typing) typing.remove();
      messages.innerHTML += `<div class="cw-msg bot">Sorry, something went wrong. Please try again.</div>`;
    }

    sendBtn.disabled = false;
    messages.scrollTop = messages.scrollHeight;
    input.focus();
  };

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
})();
