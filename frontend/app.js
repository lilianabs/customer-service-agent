/* ============================================================
   AnyCompany Hair Care — front-end logic (starter)

   This is the STARTER storefront for a build-along tutorial.
   The support chat widget is intentionally NOT connected to any
   backend yet: sending a message shows a friendly placeholder.

   Over the series you'll wire this widget to a LangGraph +
   Amazon Bedrock backend, adding streaming replies, conversation
   memory, retrieval from a product knowledge base, and a
   human-in-the-loop refund flow. When you get there, point
   CHAT_API_URL at your backend's /chat endpoint.
   ============================================================ */

/* ---------- Config ----------
   Points at the local FastAPI backend (backend/app.py). If the
   backend is down, the widget falls back to OFFLINE_REPLY. Set to
   null to force the offline placeholder. */
const CHAT_API_URL = "http://localhost:8000/chat";

// Shown when the backend is unset or unreachable.
const OFFLINE_REPLY =
  "Thanks for reaching out! This AI assistant isn't connected yet — this repo is the " +
  "starter storefront for a build-along tutorial. Over the series it'll answer from " +
  "AnyCompany Hair Care's real product knowledge base, built with LangGraph and Amazon " +
  "Bedrock. For now, email hello@anycompanyhair.com and a human will help.";

/* ---------- Product data ----------
   These fields double as the source content for the product
   knowledge base you'll build later. Keep them in sync. */
const PRODUCTS = [
  {
    id: "define-curl-cream",
    name: "Define Curl Cream",
    desc: "Lightweight curl-defining cream for bouncy, frizz-free coils.",
    price: "$24",
    size: "8 fl oz",
    rating: "4.9 ★",
    reviews: 1840,
    tag: "Bestseller",
    color: "#b5654a",
    hairTypes: ["Curly", "Coily", "Wavy"],
    keyIngredients: ["Shea Butter", "Flaxseed Extract", "Glycerin"],
    usage: "Rake through soaking-wet hair, scrunch upward, then air-dry or diffuse.",
    safety: "Color-safe. Sulfate-, silicone-, and paraben-free. Vegan & cruelty-free.",
  },
  {
    id: "repair-bond-oil",
    name: "Repair Bond Oil",
    desc: "Strengthening treatment oil that rebuilds damaged, over-processed hair.",
    price: "$32",
    size: "3.4 fl oz",
    rating: "4.8 ★",
    reviews: 1210,
    tag: "New",
    color: "#2f6f5f",
    hairTypes: ["Damaged", "Color-treated", "Chemically processed"],
    keyIngredients: ["Bond-building Complex", "Argan Oil", "Vitamin E"],
    usage: "Apply 2–3 drops to damp mid-lengths and ends before styling, or to dry hair as a finisher.",
    safety: "Color-safe and bleach-safe. Sulfate- and paraben-free. Vegan & cruelty-free.",
  },
  {
    id: "hydra-wash-shampoo",
    name: "Hydra Wash Shampoo",
    desc: "Sulfate-free hydrating shampoo that cleanses without stripping moisture.",
    price: "$22",
    size: "10 fl oz",
    rating: "4.7 ★",
    reviews: 2050,
    tag: null,
    color: "#7b9bd1",
    hairTypes: ["Dry", "Normal", "Color-treated"],
    keyIngredients: ["Aloe Vera", "Coconut-derived Cleansers", "Panthenol"],
    usage: "Massage into wet scalp, lather, and rinse. Follow with Silk Slip Conditioner.",
    safety: "Color-safe, sulfate-free, pH-balanced. Vegan & cruelty-free.",
  },
  {
    id: "silk-slip-conditioner",
    name: "Silk Slip Conditioner",
    desc: "Deeply nourishing conditioner for easy detangling and lasting softness.",
    price: "$23",
    size: "10 fl oz",
    rating: "4.9 ★",
    reviews: 1760,
    tag: null,
    color: "#c79bd1",
    hairTypes: ["Dry", "Curly", "Color-treated"],
    keyIngredients: ["Slip-rich Conditioning Blend", "Shea Butter", "Hydrolyzed Quinoa"],
    usage: "Work through clean, wet hair, comb to detangle, leave 1–2 minutes, then rinse.",
    safety: "Color-safe, silicone-free. Vegan & cruelty-free.",
  },
  {
    id: "scalp-reset-serum",
    name: "Scalp Reset Serum",
    desc: "Soothing pre-wash serum that balances the scalp and supports healthy growth.",
    price: "$28",
    size: "2 fl oz",
    rating: "4.6 ★",
    reviews: 690,
    tag: "New",
    color: "#d1a94f",
    hairTypes: ["Oily scalp", "Sensitive scalp", "All types"],
    keyIngredients: ["Niacinamide", "Tea Tree", "Peptide Blend"],
    usage: "Massage into a dry or damp scalp 10 minutes before washing. Use 2–3 times a week.",
    safety: "Fragrance-free option available. Sulfate- and paraben-free. Vegan & cruelty-free.",
  },
  {
    id: "air-dry-styling-gel",
    name: "Air-Dry Styling Gel",
    desc: "Flexible-hold gel for soft, crunch-free definition on wash-and-go days.",
    price: "$20",
    size: "8 fl oz",
    rating: "4.7 ★",
    reviews: 980,
    tag: null,
    color: "#d18b6f",
    hairTypes: ["Wavy", "Curly", "Coily"],
    keyIngredients: ["Flaxseed Gel", "Marshmallow Root", "Glycerin"],
    usage: "Smooth over wet hair in sections, scrunch, and air-dry. Scrunch out any cast when dry.",
    safety: "Color-safe, alcohol-free, no flaking. Vegan & cruelty-free.",
  },
  {
    id: "weekly-repair-mask",
    name: "Weekly Repair Mask",
    desc: "Intensive deep-conditioning mask for dry, frizzy, and damaged hair.",
    price: "$30",
    size: "8 fl oz",
    rating: "4.8 ★",
    reviews: 1430,
    tag: "Bestseller",
    color: "#6a8f7d",
    hairTypes: ["Dry", "Frizzy", "Damaged", "Color-treated"],
    keyIngredients: ["Murumuru Butter", "Hyaluronic Acid", "Rice Protein"],
    usage: "Apply to clean, damp hair once a week, leave 5–10 minutes, then rinse well.",
    safety: "Color-safe, silicone-free. Vegan & cruelty-free.",
  },
  {
    id: "heat-shield-mist",
    name: "Heat Shield Mist",
    desc: "Weightless thermal protection up to 450°F before heat styling.",
    price: "$19",
    size: "5 fl oz",
    rating: "4.6 ★",
    reviews: 870,
    tag: null,
    color: "#9a8fd1",
    hairTypes: ["All types", "Fine", "Color-treated"],
    keyIngredients: ["Heat-activated Polymers", "Bamboo Extract", "Provitamin B5"],
    usage: "Mist evenly over damp or dry hair before blow-drying, flat-ironing, or curling.",
    safety: "Color-safe, non-sticky, lightweight. Vegan & cruelty-free.",
  },
];

function renderProducts() {
  const grid = document.getElementById("product-grid");
  if (!grid) return;
  grid.innerHTML = PRODUCTS.map((p) => `
    <article class="product-card" data-product="${p.id}" tabindex="0" role="button" aria-label="View details for ${p.name}">
      <div class="product-media" style="background: linear-gradient(160deg, #f6e3d8, #efe7f3);">
        ${p.tag ? `<span class="product-tag">${p.tag}</span>` : ""}
        <div class="product-bottle" style="--bottle:${p.color}"></div>
      </div>
      <div class="product-body">
        <h3 class="product-name">${p.name}</h3>
        <p class="product-desc">${p.desc}</p>
        <div class="product-meta">
          <span class="product-price">${p.price}</span>
          <span class="product-rating">${p.rating}</span>
        </div>
        <button class="product-add" data-add="${p.name}">Add to cart</button>
      </div>
    </article>
  `).join("");
}

/* ---------- Product detail modal ---------- */
const Modal = {
  el: null,
  lastFocused: null,

  ensure() {
    if (this.el) return this.el;
    const el = document.createElement("div");
    el.className = "modal-overlay";
    el.id = "product-modal";
    el.setAttribute("aria-hidden", "true");
    el.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <button class="modal-close" aria-label="Close details">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </button>
        <div class="modal-body"></div>
      </div>`;
    document.body.appendChild(el);

    el.addEventListener("click", (e) => { if (e.target === el) this.close(); });
    el.querySelector(".modal-close").addEventListener("click", () => this.close());
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && el.classList.contains("is-open")) this.close();
    });
    this.el = el;
    return el;
  },

  open(productId) {
    const p = PRODUCTS.find((x) => x.id === productId);
    if (!p) return;
    const el = this.ensure();
    this.lastFocused = document.activeElement;

    el.querySelector(".modal-body").innerHTML = `
      <div class="modal-hero">
        <div class="modal-bottle" style="--bottle:${p.color}"></div>
        ${p.tag ? `<span class="product-tag">${p.tag}</span>` : ""}
      </div>
      <div class="modal-info">
        <h2 id="modal-title">${p.name}</h2>
        <div class="modal-meta">
          <span class="product-price">${p.price}</span>
          <span class="modal-size">${p.size}</span>
          <span class="product-rating">${p.rating} (${p.reviews.toLocaleString()})</span>
        </div>
        <p class="modal-desc">${p.desc}</p>

        <div class="modal-section">
          <h4>Best for</h4>
          <div class="chips">${p.hairTypes.map((h) => `<span class="chip">${h}</span>`).join("")}</div>
        </div>
        <div class="modal-section">
          <h4>Key ingredients</h4>
          <div class="chips">${p.keyIngredients.map((i) => `<span class="chip">${i}</span>`).join("")}</div>
        </div>
        <div class="modal-section">
          <h4>How to use</h4>
          <p>${p.usage}</p>
        </div>
        <div class="modal-section">
          <h4>Good to know</h4>
          <p>${p.safety}</p>
        </div>

        <div class="modal-actions">
          <button class="btn btn-primary" data-add="${p.name}">Add to cart — ${p.price}</button>
          <button class="btn btn-ghost" data-ask="${p.name}">Ask the assistant about this</button>
        </div>
      </div>`;

    el.classList.add("is-open");
    el.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    setTimeout(() => el.querySelector(".modal-close").focus(), 50);
  },

  close() {
    if (!this.el) return;
    this.el.classList.remove("is-open");
    this.el.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    if (this.lastFocused) this.lastFocused.focus();
  },
};

/* ---------- Cart (tiny demo behavior) ---------- */
function setupCart() {
  const countEl = document.querySelector(".cart-count");
  let count = 0;
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-add]");
    if (!btn) return;
    count += 1;
    if (countEl) countEl.textContent = String(count);
    const original = btn.textContent;
    btn.textContent = "Added ✓";
    btn.disabled = true;
    setTimeout(() => { btn.textContent = original; btn.disabled = false; }, 1200);
  });
}

/* ---------- Product interactions (open modal, ask assistant) ---------- */
function setupProductInteractions() {
  document.addEventListener("click", (e) => {
    // "Ask the assistant about this" — opens chat with a prefilled question
    const askBtn = e.target.closest("[data-ask]");
    if (askBtn) {
      const name = askBtn.getAttribute("data-ask");
      Modal.close();
      Chat.open();
      Chat.prefill(`Is the ${name} right for my hair type?`);
      return;
    }
    // Add-to-cart shouldn't open the modal
    if (e.target.closest("[data-add]")) return;

    // Open product detail modal from a card
    const card = e.target.closest("[data-product]");
    if (card) Modal.open(card.getAttribute("data-product"));
  });

  // Keyboard: Enter/Space opens the focused product card
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const card = e.target.closest("[data-product]");
    if (card) { e.preventDefault(); Modal.open(card.getAttribute("data-product")); }
  });
}

/* ============================================================
   Chat widget

   UI only for now. `send()` shows a local placeholder because
   CHAT_API_URL is null. Later phases replace this with a real
   fetch to the LangGraph backend and stream the reply.
   ============================================================ */
const Chat = {
  panel: null, launcher: null, messages: null, form: null,
  input: null, suggestions: null, isOpen: false, greeted: false,

  init() {
    this.panel = document.getElementById("chat-panel");
    this.launcher = document.getElementById("chat-launcher");
    this.messages = document.getElementById("chat-messages");
    this.form = document.getElementById("chat-form");
    this.input = document.getElementById("chat-text");
    this.suggestions = document.getElementById("chat-suggestions");
    if (!this.panel) return;

    this.launcher.addEventListener("click", () => this.toggle());
    document.getElementById("chat-close").addEventListener("click", () => this.close());

    document.querySelectorAll("[data-open-chat]").forEach((el) => {
      el.addEventListener("click", (e) => { e.preventDefault(); this.open(); });
    });

    this.form.addEventListener("submit", (e) => {
      e.preventDefault();
      const text = this.input.value.trim();
      if (text) this.send(text);
    });

    this.suggestions.addEventListener("click", (e) => {
      const chip = e.target.closest(".suggestion-chip");
      if (chip) this.send(chip.textContent.trim());
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this.isOpen) this.close();
    });
  },

  toggle() { this.isOpen ? this.close() : this.open(); },

  open() {
    this.isOpen = true;
    this.panel.classList.add("is-open");
    this.panel.setAttribute("aria-hidden", "false");
    this.launcher.classList.add("is-open");
    this.launcher.setAttribute("aria-expanded", "true");
    if (!this.greeted) {
      this.greeted = true;
      this.addBot("Hi there! 👋 I'm the AnyCompany Hair Care support assistant. Ask me about products, ingredients, or what's right for your hair type.");
    }
    setTimeout(() => this.input.focus(), 250);
  },

  close() {
    this.isOpen = false;
    this.panel.classList.remove("is-open");
    this.panel.setAttribute("aria-hidden", "true");
    this.launcher.classList.remove("is-open");
    this.launcher.setAttribute("aria-expanded", "false");
  },

  prefill(text) {
    this.input.value = text;
    setTimeout(() => this.input.focus(), 300);
  },

  scrollToBottom() { this.messages.scrollTop = this.messages.scrollHeight; },

  addUser(text) {
    const el = document.createElement("div");
    el.className = "msg msg-user";
    el.textContent = text;
    this.messages.appendChild(el);
    this.scrollToBottom();
  },

  addBot(text) {
    const el = document.createElement("div");
    el.className = "msg msg-bot";
    el.textContent = text;
    this.messages.appendChild(el);
    this.scrollToBottom();
    return el;
  },

  showTyping() {
    const el = document.createElement("div");
    el.className = "msg msg-bot msg-typing";
    el.innerHTML = "<span></span><span></span><span></span>";
    this.messages.appendChild(el);
    this.scrollToBottom();
    return el;
  },

  // One conversation per browser tab: the backend keys memory on this id.
  threadId() {
    try {
      const existing = sessionStorage.getItem("achc_thread_id");
      if (existing) return existing;
      const fresh =
        (crypto.randomUUID && crypto.randomUUID()) ||
        `t-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      sessionStorage.setItem("achc_thread_id", fresh);
      return fresh;
    } catch {
      // sessionStorage unavailable (e.g. privacy mode): use an in-memory id.
      if (!this._fallbackThreadId) {
        this._fallbackThreadId = `t-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      }
      return this._fallbackThreadId;
    }
  },

  async send(text) {
    this.input.value = "";
    this.addUser(text);

    const typing = this.showTyping();
    const botEl = this.addBot("");
    let typingRemoved = false;
    const removeTyping = () => {
      if (!typingRemoved && typing && typing.isConnected) typing.remove();
      typingRemoved = true;
    };

    try {
      if (!CHAT_API_URL) throw new Error("no backend configured");
      const res = await fetch(CHAT_API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, thread_id: this.threadId() }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      // Stream the reply as it arrives instead of waiting for the full text.
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        removeTyping();
        botEl.textContent += decoder.decode(value, { stream: true });
        this.scrollToBottom();
      }
      botEl.textContent += decoder.decode();
      removeTyping();
      if (!botEl.textContent) botEl.textContent = OFFLINE_REPLY;
    } catch (err) {
      // Backend unreachable or misconfigured: show the placeholder so the widget still answers.
      console.warn("Chat backend unavailable:", err);
      removeTyping();
      botEl.textContent = "";
      await simulateStream(OFFLINE_REPLY, (token) => {
        botEl.textContent += token;
        this.scrollToBottom();
      });
    }
  },
};

// Simulated token stream for the placeholder (word by word).
async function simulateStream(text, onToken) {
  if (!onToken) return;
  const words = text.split(" ");
  for (let i = 0; i < words.length; i++) {
    onToken((i === 0 ? "" : " ") + words[i]);
    await new Promise((r) => setTimeout(r, 28));
  }
}

/* ---------- Boot ---------- */
document.addEventListener("DOMContentLoaded", () => {
  renderProducts();
  setupCart();
  setupProductInteractions();
  Chat.init();
});
