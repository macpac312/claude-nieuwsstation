import { Plugin, WorkspaceLeaf, ItemView, Notice, TFile } from "obsidian";
import { spawn } from "child_process";
import { BriefingView, BRIEFING_VIEW_TYPE } from "./BriefingView";
import { join } from "path";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "fs";

const VIEW_TYPE = "nieuwsstation-command-center";

interface TopicConfig {
  id: string;
  label: string;
  icon: string;
  desc: string;
  color: string;
  active: boolean;
  custom?: boolean;
}

interface SourceConfig {
  name: string;
  url: string;
  topic: string;
  type: string;
  status: string;
  section: string; // "topics" or "dagkrant_topics"
}

const BRIEFING_TOPICS: TopicConfig[] = [
  { id: "regulatoir", label: "Regulatoir", icon: "📋", desc: "EBA, ECB, DNB, BIS", color: "#89b4fa", active: true },
  { id: "huizenmarkt", label: "Huizenmarkt", icon: "🏠", desc: "Calcasa, NVM, CBS", color: "#a6e3a1", active: true },
  { id: "financieel", label: "Financieel", icon: "📊", desc: "FD, NRC, Bloomberg", color: "#fab387", active: true },
  { id: "tech", label: "Tech & AI", icon: "⚡", desc: "AI nieuws, LLMs, tools", color: "#cba6f7", active: false },
  { id: "sport", label: "Sport", icon: "⚽", desc: "F1, schaken, voetbal", color: "#a6e3a1", active: false },
  { id: "ai_nieuws", label: "AI Nieuws", icon: "🤖", desc: "Papers, benchmarks", color: "#cba6f7", active: false },
];

const DAGKRANT_TOPICS: TopicConfig[] = [
  { id: "nederland",      label: "Nederland",   icon: "🇳🇱", desc: "NOS, FTM, binnenland",          color: "#ea580c", active: true  },
  { id: "wereld",         label: "Wereld",      icon: "🌍", desc: "Al Jazeera, NPR, BBC",           color: "#2563eb", active: true  },
  { id: "financieel_dk",  label: "Financieel",  icon: "📊", desc: "FD, CNBC, markten",              color: "#d97706", active: true  },
  { id: "regulatoir_dk",  label: "Regulatoir",  icon: "📋", desc: "EBA, ECB, DNB, AFM, BIS",        color: "#3b5bdb", active: false },
  { id: "huizenmarkt_dk", label: "Huizenmarkt", icon: "🏠", desc: "NVM, woningmarkt, hypotheek",    color: "#2f9e44", active: false },
  { id: "sport_dk",       label: "Sport",       icon: "⚽", desc: "NOS Sport, F1",                  color: "#16a34a", active: true  },
  { id: "ai_tech",        label: "AI & Tech",   icon: "🤖", desc: "Anthropic, OpenAI, Verge",       color: "#7c3aed", active: true  },
];

/* ═══════════════════════════════════════
   COMMAND CENTER VIEW
   ═══════════════════════════════════════ */

class CommandCenterView extends ItemView {
  private activeTab: "briefing" | "dagkrant" | "bronnen" | "archief" = "briefing";
  private briefingTopics: Record<string, boolean> = {};
  private dagkrantTopics: Record<string, boolean> = {};
  private customDagkrantTopics: TopicConfig[] = [];
  private customPrompt: string = "";
  private dagkrantPrompt: string = "";
  private podcastEnabled: boolean = true;
  private vaultContext: boolean = true;
  private dagkrantWeer: boolean = true;
  private dagkrantVerkeer: boolean = true;
  private dagkrantMarkten: boolean = true;
  private generating: boolean = false;
  private nlmSending: boolean = false;
  private nlmLastUrl: string = "";
  private nlmLastTitle: string = "";
  private nlmShowFocus: boolean = false;
  private nlmFocusText: string = "";
  private nlmFocusLoading: boolean = false;
  private showAddTopic: boolean = false;
  private showAddSource: boolean = false;
  private newTopicName: string = "";
  private newTopicIcon: string = "📌";
  private newTopicDesc: string = "";
  private newSourceName: string = "";
  private newSourceUrl: string = "";
  private newSourceTopic: string = "";
  private newSourceSection: string = "dagkrant_topics";

  constructor(leaf: WorkspaceLeaf) {
    super(leaf);
    BRIEFING_TOPICS.forEach(t => this.briefingTopics[t.id] = t.active);
    DAGKRANT_TOPICS.forEach(t => this.dagkrantTopics[t.id] = t.active);
    this.loadCustomTopics();
  }

  getViewType() { return VIEW_TYPE; }
  getDisplayText() { return "Nieuwsstation"; }
  getIcon() { return "radio"; }

  async onOpen() {
    this.render();
  }

  private loadCustomTopics() {
    try {
      const home = process.env.HOME || "/home/marcel";
      const path = join(home, "nieuwsstation", "data", "custom-topics.json");
      if (existsSync(path)) {
        const data = JSON.parse(readFileSync(path, "utf-8"));
        this.customDagkrantTopics = data;
        data.forEach((t: TopicConfig) => this.dagkrantTopics[t.id] = t.active);
      }
    } catch { /* ignore */ }
  }

  private saveCustomTopics() {
    try {
      const home = process.env.HOME || "/home/marcel";
      const dir = join(home, "nieuwsstation", "data");
      if (!existsSync(dir)) {
        require("fs").mkdirSync(dir, { recursive: true });
      }
      writeFileSync(
        join(dir, "custom-topics.json"),
        JSON.stringify(this.customDagkrantTopics, null, 2)
      );
    } catch (e) {
      console.error("Failed to save custom topics:", e);
    }
  }

  private render() {
    const container = this.containerEl.children[1] as HTMLElement;
    container.empty();
    container.addClass("nieuwsstation-container");

    this.renderHeader(container);
    this.renderContent(container);
    this.renderFooter(container);
  }

  private renderHeader(container: HTMLElement) {
    const header = container.createDiv({ cls: "ns-header" });

    // Title row
    const titleRow = header.createDiv({ cls: "ns-header-title" });
    titleRow.createDiv({ cls: "ns-header-icon", text: "📡" });
    const textDiv = titleRow.createDiv({ cls: "ns-header-text" });
    textDiv.createEl("h3", { text: "Nieuwsstation" });
    textDiv.createDiv({ cls: "ns-subtitle", text: "Claude Code Channels" });

    const status = titleRow.createDiv({ cls: "ns-status" });
    status.createDiv({ cls: "ns-status-dot ok" });
    status.createSpan({ cls: "ns-status-text", text: "Online" });

    // Tabs
    const tabs = header.createDiv({ cls: "ns-tabs" });
    const tabDefs = [
      { id: "briefing" as const, label: "Briefing" },
      { id: "dagkrant" as const, label: "Dagkrant" },
      { id: "bronnen" as const, label: "Bronnen" },
      { id: "archief" as const, label: "Archief" },
    ];
    tabDefs.forEach(t => {
      const btn = tabs.createEl("button", {
        cls: `ns-tab ${this.activeTab === t.id ? "active" : ""}`,
        text: t.label,
      });
      btn.addEventListener("click", () => {
        this.activeTab = t.id;
        this.render();
      });
    });
  }

  private renderContent(container: HTMLElement) {
    const content = container.createDiv({ cls: "ns-content" });

    switch (this.activeTab) {
      case "briefing": this.renderBriefingTab(content); break;
      case "dagkrant": this.renderDagkrantTab(content); break;
      case "bronnen": this.renderBronnenTab(content); break;
      case "archief": this.renderArchiefTab(content); break;
    }
  }

  /* ═══ BRIEFING TAB ═══ */
  private renderBriefingTab(parent: HTMLElement) {
    const panel = parent.createDiv({ cls: "ns-panel" });

    // Topic selector
    const topicSection = panel.createDiv();
    topicSection.createDiv({ cls: "ns-section-title", text: "Topics" });
    const topicList = topicSection.createDiv({ cls: "ns-topic-list" });

    BRIEFING_TOPICS.forEach(t => {
      this.renderTopicItem(topicList, t, this.briefingTopics, (id) => {
        this.briefingTopics[id] = !this.briefingTopics[id];
        this.render();
      });
    });

    // Focus prompt
    this.renderFocusPrompt(panel, this.customPrompt, (val) => this.customPrompt = val,
      "Bijv. 'Focus op CRR3 leverage ratio impact' of 'Vergelijk ECB en EBA standpunten'");

    // Options
    const optionsSection = panel.createDiv();
    optionsSection.style.display = "flex";
    optionsSection.style.flexDirection = "column";
    optionsSection.style.gap = "8px";

    this.renderOption(optionsSection, "🎙️", "Podcast paper genereren", this.podcastEnabled, "#fab387", () => {
      this.podcastEnabled = !this.podcastEnabled;
      this.render();
    });
    this.renderOption(optionsSection, "🔗", "Vault context meenemen", this.vaultContext, "#94e2d5", () => {
      this.vaultContext = !this.vaultContext;
      this.render();
    });

    // Generate button
    this.renderGenerateButton(panel, "Genereer briefing", () => this.generateBriefing());

    // Telegram hint
    const hint = panel.createDiv({ cls: "ns-hint" });
    hint.createDiv({ cls: "ns-hint-label", text: "Terminal shortcut" });
    hint.createEl("code", { cls: "ns-hint-code", text: "/briefing regulatoir huizenmarkt" });

    // Recent briefings
    this.renderRecentBriefings(panel);
  }

  /* ═══ DAGKRANT TAB ═══ */
  private renderDagkrantTab(parent: HTMLElement) {
    const panel = parent.createDiv({ cls: "ns-panel" });

    // Dagkrant description
    const desc = panel.createDiv({ cls: "ns-dagkrant-desc" });
    desc.innerHTML = `<span style="font-size:18px">📰</span> <strong>De Dagkrant</strong> — Interactieve HTML-nieuwssite met breaking news, achtergrondartikelen, weer, verkeer en markten.`;

    // Topic selector
    const topicSection = panel.createDiv();
    topicSection.createDiv({ cls: "ns-section-title", text: "Secties" });
    const topicList = topicSection.createDiv({ cls: "ns-topic-list" });

    // Built-in dagkrant topics
    DAGKRANT_TOPICS.forEach(t => {
      this.renderTopicItem(topicList, t, this.dagkrantTopics, (id) => {
        this.dagkrantTopics[id] = !this.dagkrantTopics[id];
        this.render();
      });
    });

    // Custom topics
    this.customDagkrantTopics.forEach(t => {
      this.renderTopicItem(topicList, t, this.dagkrantTopics, (id) => {
        this.dagkrantTopics[id] = !this.dagkrantTopics[id];
        this.render();
      }, true);
    });

    // Add custom topic button/form
    if (this.showAddTopic) {
      this.renderAddTopicForm(topicSection);
    } else {
      const addBtn = topicSection.createEl("button", { cls: "ns-add-source", text: "+ Custom sectie toevoegen" });
      addBtn.addEventListener("click", () => {
        this.showAddTopic = true;
        this.render();
      });
    }

    // Focus prompt
    this.renderFocusPrompt(panel, this.dagkrantPrompt, (val) => this.dagkrantPrompt = val,
      "Bijv. 'Extra aandacht voor Iran-conflict' of 'Voeg schaaknieuws toe'");

    // Widgets options
    const widgetSection = panel.createDiv();
    widgetSection.createDiv({ cls: "ns-section-title", text: "Widgets" });
    const widgetOpts = widgetSection.createDiv();
    widgetOpts.style.display = "flex";
    widgetOpts.style.flexDirection = "column";
    widgetOpts.style.gap = "8px";

    this.renderOption(widgetOpts, "🌤️", "Weer (Hilversum)", this.dagkrantWeer, "#0891b2", () => {
      this.dagkrantWeer = !this.dagkrantWeer;
      this.render();
    });
    this.renderOption(widgetOpts, "🚗", "Verkeer (A27/A28)", this.dagkrantVerkeer, "#ea580c", () => {
      this.dagkrantVerkeer = !this.dagkrantVerkeer;
      this.render();
    });
    this.renderOption(widgetOpts, "📈", "Markten (AEX, S&P)", this.dagkrantMarkten, "#d97706", () => {
      this.dagkrantMarkten = !this.dagkrantMarkten;
      this.render();
    });

    // Generate buttons
    const btnRow = panel.createDiv({ cls: "ns-btn-row" });
    btnRow.style.cssText = "display:flex;gap:8px;flex-wrap:wrap;margin-top:12px";
    this.renderGenerateButton(btnRow, "🔄 Vernieuw dagkrant", () => this.generateDagkrant());

    // "Sectie toevoegen" knop — alleen tonen als er actieve custom topics zijn
    const activeCustom = this.customDagkrantTopics.filter(t => this.dagkrantTopics[t.id]);
    if (activeCustom.length > 0) {
      activeCustom.forEach(ct => {
        const addBtn = btnRow.createEl("button", {
          cls: "ns-generate-btn",
          text: `+ ${ct.icon || ""} ${ct.label} toevoegen`.trim(),
        });
        addBtn.style.cssText = "background:var(--interactive-accent);color:var(--text-on-accent);border:none;border-radius:6px;padding:8px 14px;cursor:pointer;font-size:13px;";
        if (this.generating) { addBtn.disabled = true; addBtn.style.opacity = "0.5"; }
        addBtn.addEventListener("click", () => {
          if (!this.generating) this.appendSection(ct.id, ct.label);
        });
      });
    }

    // ── NotebookLM sectie ──────────────────────────────────────────────
    const nlmSection = panel.createDiv({ cls: "ns-nlm-section" });
    nlmSection.style.cssText = "margin-top:1.2rem;padding-top:1rem;border-top:1px solid var(--background-modifier-border)";

    // Toon welke dagkrant actief is
    const { date: activeDate, hasPodcast: activeHasPodcast } = this.findActiveDagkrant();
    const nlmHeader = nlmSection.createDiv();
    nlmHeader.style.cssText = "display:flex;align-items:center;justify-content:space-between;margin-bottom:8px";
    const nlmTitle = nlmHeader.createDiv();
    nlmTitle.style.cssText = "display:flex;align-items:center;gap:6px";
    nlmTitle.createSpan({ text: "📤" });
    nlmTitle.createEl("strong", { text: "NotebookLM Podcast" });
    const nlmMeta = nlmHeader.createDiv();
    nlmMeta.style.cssText = "font-size:0.72rem;color:var(--text-muted)";
    if (this.nlmShowFocus) {
      nlmMeta.textContent = activeDate + (activeHasPodcast ? " ✓" : " — wordt gegenereerd");
    } else {
      nlmMeta.textContent = activeDate + (activeHasPodcast ? " ✓" : " — nog niet gegenereerd");
    }

    if (this.nlmShowFocus) {
      // ── Focus-bewerkscherm ──────────────────────────────────────────
      const focusLabel = nlmSection.createDiv();
      focusLabel.style.cssText = "font-size:0.75rem;color:var(--text-muted);margin-bottom:6px";
      focusLabel.textContent = activeHasPodcast
        ? "Optioneel: waar moeten de AI-hosts op focussen?"
        : "Optioneel: script wordt automatisch gegenereerd bij verzenden.";

      const focusArea = nlmSection.createEl("textarea");
      focusArea.style.cssText = "width:100%;min-height:80px;font-size:0.8rem;padding:8px;border-radius:6px;resize:vertical;background:var(--background-primary);color:var(--text-normal);border:1px solid var(--background-modifier-border);box-sizing:border-box";
      if (this.nlmFocusLoading) {
        focusArea.value = "Focus suggestie wordt geladen…";
        focusArea.disabled = true;
      } else {
        focusArea.value = this.nlmFocusText;
        focusArea.addEventListener("input", () => { this.nlmFocusText = focusArea.value; });
      }

      const btnRow = nlmSection.createDiv();
      btnRow.style.cssText = "display:flex;gap:8px;margin-top:8px";

      const sendBtn = btnRow.createEl("button", {
        cls: `ns-generate-btn ${this.nlmSending ? "generating" : ""}`,
        attr: { style: "flex:1;background:linear-gradient(135deg,#4285f4,#34a853)" }
      });
      if (this.nlmSending) {
        sendBtn.innerHTML = activeHasPodcast
          ? `<span class="ns-spinner"></span> Uploaden…`
          : `<span class="ns-spinner"></span> Script genereren + uploaden…`;
      } else {
        sendBtn.textContent = activeHasPodcast
          ? "Verstuur naar NotebookLM →"
          : "Genereer script + verstuur naar NotebookLM →";
      }
      sendBtn.addEventListener("click", () => { if (!this.nlmSending && !this.nlmFocusLoading) this.sendToNotebookLM(); });

      const cancelBtn = btnRow.createEl("button", { text: "✕", cls: "ns-cancel-btn" });
      cancelBtn.style.cssText = "padding:6px 12px;border-radius:6px;border:1px solid var(--background-modifier-border);background:var(--background-secondary);cursor:pointer";
      cancelBtn.addEventListener("click", () => { this.nlmShowFocus = false; this.render(); });

    } else {
      // ── Standaard knop ─────────────────────────────────────────────
      const nlmBtn = nlmSection.createEl("button", {
        cls: "ns-generate-btn",
        attr: { style: "background:linear-gradient(135deg,#4285f4,#34a853);width:100%" }
      });
      nlmBtn.textContent = activeHasPodcast
        ? `Upload podcast ${activeDate} naar NotebookLM`
        : `Genereer + upload podcast ${activeDate}`;
      nlmBtn.addEventListener("click", () => this.prepareNotebookLM());
    }

    if (this.nlmLastUrl) {
      const nlmLast = nlmSection.createDiv({ cls: "ns-hint" });
      nlmLast.style.marginTop = "6px";
      const lbl = nlmLast.createDiv({ cls: "ns-hint-label", text: `Laatste: ${this.nlmLastTitle} ↗` });
      lbl.style.cssText = "cursor:pointer;color:var(--text-accent)";
      lbl.addEventListener("click", () => window.open(this.nlmLastUrl, "_blank"));
    }

    // Terminal hint
    const hint = panel.createDiv({ cls: "ns-hint" });
    hint.createDiv({ cls: "ns-hint-label", text: "Terminal shortcut" });
    hint.createEl("code", { cls: "ns-hint-code", text: "/dagkrant" });

    // Recent dagkranten
    this.renderRecentDagkranten(panel);
  }

  private renderAddTopicForm(parent: HTMLElement) {
    const form = parent.createDiv({ cls: "ns-add-topic-form" });

    const row1 = form.createDiv({ cls: "ns-form-row" });
    const iconInput = row1.createEl("input", { cls: "ns-input-small" });
    iconInput.placeholder = "📌";
    iconInput.value = this.newTopicIcon;
    iconInput.style.width = "40px";
    iconInput.style.textAlign = "center";
    iconInput.addEventListener("input", (e) => this.newTopicIcon = (e.target as HTMLInputElement).value);

    const nameInput = row1.createEl("input", { cls: "ns-input" });
    nameInput.placeholder = "Naam (bijv. Wetenschap)";
    nameInput.value = this.newTopicName;
    nameInput.addEventListener("input", (e) => this.newTopicName = (e.target as HTMLInputElement).value);

    const descInput = form.createEl("input", { cls: "ns-input" });
    descInput.placeholder = "Beschrijving (bijv. Nature, CERN, ruimtevaart)";
    descInput.value = this.newTopicDesc;
    descInput.addEventListener("input", (e) => this.newTopicDesc = (e.target as HTMLInputElement).value);

    const btnRow = form.createDiv({ cls: "ns-form-buttons" });
    const saveBtn = btnRow.createEl("button", { cls: "ns-btn-save", text: "Toevoegen" });
    saveBtn.addEventListener("click", () => {
      if (!this.newTopicName.trim()) {
        new Notice("Vul een naam in");
        return;
      }
      const id = this.newTopicName.toLowerCase().replace(/[^a-z0-9]/g, "_");
      const newTopic: TopicConfig = {
        id,
        label: this.newTopicName,
        icon: this.newTopicIcon || "📌",
        desc: this.newTopicDesc || "",
        color: "#94e2d5",
        active: true,
        custom: true,
      };
      this.customDagkrantTopics.push(newTopic);
      this.dagkrantTopics[id] = true;
      this.saveCustomTopics();
      this.newTopicName = "";
      this.newTopicIcon = "📌";
      this.newTopicDesc = "";
      this.showAddTopic = false;
      this.render();
      new Notice(`Sectie "${newTopic.label}" toegevoegd`);
    });

    const cancelBtn = btnRow.createEl("button", { cls: "ns-btn-cancel", text: "Annuleren" });
    cancelBtn.addEventListener("click", () => {
      this.showAddTopic = false;
      this.render();
    });
  }

  /* ═══ BRONNEN TAB ═══ */
  private renderBronnenTab(parent: HTMLElement) {
    const panel = parent.createDiv({ cls: "ns-panel" });

    // Section selector
    const sectionToggle = panel.createDiv({ cls: "ns-section-toggle" });
    const briefingBtn = sectionToggle.createEl("button", {
      cls: `ns-section-btn ${this.newSourceSection === "topics" ? "active" : ""}`,
      text: "Briefing bronnen",
    });
    briefingBtn.addEventListener("click", () => {
      this.newSourceSection = "topics";
      this.render();
    });
    const dagkrantBtn = sectionToggle.createEl("button", {
      cls: `ns-section-btn ${this.newSourceSection === "dagkrant_topics" ? "active" : ""}`,
      text: "Dagkrant bronnen",
    });
    dagkrantBtn.addEventListener("click", () => {
      this.newSourceSection = "dagkrant_topics";
      this.render();
    });

    panel.createDiv({ cls: "ns-section-title", text: "RSS & Data bronnen" });

    // Load and display sources
    this.loadSources().then(sources => {
      const filtered = sources.filter(s => s.section === this.newSourceSection);

      // Group by topic
      const grouped: Record<string, SourceConfig[]> = {};
      filtered.forEach(s => {
        if (!grouped[s.topic]) grouped[s.topic] = [];
        grouped[s.topic].push(s);
      });

      Object.entries(grouped).forEach(([topic, feeds]) => {
        const topicHeader = panel.createDiv({ cls: "ns-source-topic-header" });
        topicHeader.textContent = topic;

        feeds.forEach(s => {
          const item = panel.createDiv({ cls: "ns-source-item" });
          item.createDiv({ cls: `ns-status-dot ${s.status}` });
          const info = item.createDiv({ cls: "ns-source-info" });
          info.createDiv({ cls: "ns-source-name", text: s.name });
          info.createDiv({ cls: "ns-source-url", text: s.url });

          // Delete button
          const delBtn = item.createEl("button", { cls: "ns-source-delete", text: "✕" });
          delBtn.title = "Verwijder bron";
          delBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            this.removeSource(s.name, s.topic, s.section);
          });
        });
      });

      // Add source form
      if (this.showAddSource) {
        this.renderAddSourceForm(panel, Object.keys(grouped));
      } else {
        const addBtn = panel.createEl("button", { cls: "ns-add-source", text: "+ Bron toevoegen" });
        addBtn.addEventListener("click", () => {
          this.showAddSource = true;
          this.render();
        });
      }
    });
  }

  private renderAddSourceForm(parent: HTMLElement, existingTopics: string[]) {
    const form = parent.createDiv({ cls: "ns-add-topic-form" });

    const nameInput = form.createEl("input", { cls: "ns-input" });
    nameInput.placeholder = "Bronnaam (bijv. Reuters)";
    nameInput.value = this.newSourceName;
    nameInput.addEventListener("input", (e) => this.newSourceName = (e.target as HTMLInputElement).value);

    const urlInput = form.createEl("input", { cls: "ns-input" });
    urlInput.placeholder = "RSS URL (bijv. https://feeds.reuters.com/...)";
    urlInput.value = this.newSourceUrl;
    urlInput.addEventListener("input", (e) => this.newSourceUrl = (e.target as HTMLInputElement).value);

    const topicInput = form.createEl("input", { cls: "ns-input" });
    topicInput.placeholder = `Topic (bijv. ${existingTopics[0] || "nederland"})`;
    topicInput.value = this.newSourceTopic;
    topicInput.addEventListener("input", (e) => this.newSourceTopic = (e.target as HTMLInputElement).value);

    const btnRow = form.createDiv({ cls: "ns-form-buttons" });
    const saveBtn = btnRow.createEl("button", { cls: "ns-btn-save", text: "Toevoegen" });
    saveBtn.addEventListener("click", () => {
      if (!this.newSourceName.trim() || !this.newSourceUrl.trim() || !this.newSourceTopic.trim()) {
        new Notice("Vul alle velden in");
        return;
      }
      this.addSource(this.newSourceName, this.newSourceUrl, this.newSourceTopic, this.newSourceSection);
      this.newSourceName = "";
      this.newSourceUrl = "";
      this.newSourceTopic = "";
      this.showAddSource = false;
    });

    const cancelBtn = btnRow.createEl("button", { cls: "ns-btn-cancel", text: "Annuleren" });
    cancelBtn.addEventListener("click", () => {
      this.showAddSource = false;
      this.render();
    });
  }

  private addSource(name: string, url: string, topic: string, section: string) {
    const home = process.env.HOME || "/home/marcel";
    const script = `
import yaml
path = "${home}/nieuwsstation/src/config/sources.yaml"
with open(path) as f:
    config = yaml.safe_load(f)
section = config.setdefault("${section}", {})
t = section.setdefault("${topic}", {"icon": "📌", "color": "#94e2d5", "feeds": [], "keywords": []})
feeds = t.setdefault("feeds", [])
feeds.append({"name": "${name}", "url": "${url}", "type": "article"})
with open(path, "w") as f:
    yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
print("OK")
`;
    const proc = spawn("python3", ["-c", script]);
    proc.on("close", (code) => {
      if (code === 0) {
        new Notice(`Bron "${name}" toegevoegd aan ${topic}`);
        this.render();
      } else {
        new Notice("Fout bij toevoegen bron");
      }
    });
  }

  private removeSource(name: string, topic: string, section: string) {
    const home = process.env.HOME || "/home/marcel";
    const escapedName = name.replace(/'/g, "\\'");
    const script = `
import yaml
path = "${home}/nieuwsstation/src/config/sources.yaml"
with open(path) as f:
    config = yaml.safe_load(f)
sec = config.get("${section}", {})
t = sec.get("${topic}", {})
feeds = t.get("feeds", [])
t["feeds"] = [f for f in feeds if f["name"] != '${escapedName}']
with open(path, "w") as f:
    yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
print("OK")
`;
    const proc = spawn("python3", ["-c", script]);
    proc.on("close", (code) => {
      if (code === 0) {
        new Notice(`Bron "${name}" verwijderd`);
        this.render();
      } else {
        new Notice("Fout bij verwijderen bron");
      }
    });
  }

  /* ═══ ARCHIEF TAB ═══ */
  private renderArchiefTab(parent: HTMLElement) {
    const panel = parent.createDiv({ cls: "ns-panel" });

    const searchRow = panel.createDiv();
    searchRow.style.display = "flex";
    searchRow.style.alignItems = "center";
    searchRow.style.gap = "8px";
    searchRow.style.marginBottom = "8px";

    const input = searchRow.createEl("input", { cls: "ns-search-input" });
    input.placeholder = "Zoek in briefings & dagkranten...";

    const list = panel.createDiv();
    list.style.display = "flex";
    list.style.flexDirection = "column";
    list.style.gap = "4px";

    // Combine briefings and dagkranten
    Promise.all([this.findBriefings(), this.findDagkranten()]).then(([briefings, dagkranten]) => {
      const all = [
        ...briefings.map(b => ({ ...b, type: "briefing" as const })),
        ...dagkranten.map(d => ({ ...d, type: "dagkrant" as const })),
      ].sort((a, b) => b.path.localeCompare(a.path));

      if (all.length === 0) {
        list.createDiv({
          text: "Nog geen briefings of dagkranten in het archief.",
          attr: { style: "font-size: 12px; color: var(--text-muted); padding: 10px; text-align: center;" }
        });
        return;
      }

      let filtered = all;

      const renderList = () => {
        list.empty();
        filtered.forEach(b => {
          const item = list.createDiv({ cls: "ns-archive-item" });
          item.createSpan({ cls: "ns-archive-date", text: b.date });
          item.createDiv({ cls: "ns-archive-title", text: b.title });
          item.createSpan({ cls: "ns-archive-icon", text: b.type === "dagkrant" ? "📰" : "📄" });

          item.addEventListener("click", async () => {
            if (b.type === "dagkrant") {
              // Open HTML in default browser or Obsidian
              const file = this.app.vault.getAbstractFileByPath(b.path);
              if (file instanceof TFile) {
                await this.app.workspace.getLeaf().openFile(file);
              }
            } else {
              const file = this.app.vault.getAbstractFileByPath(b.path);
              if (file instanceof TFile) {
                await this.app.workspace.getLeaf().openFile(file);
              }
            }
          });
        });
      };

      renderList();

      input.addEventListener("input", () => {
        const query = input.value.toLowerCase();
        filtered = all.filter(b =>
          b.title.toLowerCase().includes(query) || b.date.toLowerCase().includes(query)
        );
        renderList();
      });
    });
  }

  /* ═══ SHARED RENDER HELPERS ═══ */
  private renderTopicItem(
    parent: HTMLElement,
    topic: TopicConfig,
    activeMap: Record<string, boolean>,
    onToggle: (id: string) => void,
    showDelete: boolean = false,
  ) {
    const item = parent.createDiv({
      cls: `ns-topic-item ${activeMap[topic.id] ? "active" : ""}`,
    });
    if (activeMap[topic.id]) {
      item.style.borderColor = topic.color + "33";
    }

    item.createSpan({ cls: "ns-topic-icon", text: topic.icon });
    const info = item.createDiv({ cls: "ns-topic-info" });
    const name = info.createDiv({ cls: "ns-topic-name", text: topic.label });
    name.style.color = activeMap[topic.id] ? "var(--text-normal)" : "var(--text-muted)";
    info.createDiv({ cls: "ns-topic-desc", text: topic.desc });

    if (showDelete) {
      const del = item.createEl("button", { cls: "ns-topic-delete", text: "✕" });
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        this.customDagkrantTopics = this.customDagkrantTopics.filter(t => t.id !== topic.id);
        delete this.dagkrantTopics[topic.id];
        this.saveCustomTopics();
        this.render();
        new Notice(`Sectie "${topic.label}" verwijderd`);
      });
    }

    const toggle = item.createDiv({
      cls: `ns-toggle ${activeMap[topic.id] ? "on" : "off"}`,
    });
    if (activeMap[topic.id]) {
      toggle.style.background = topic.color + "88";
    }
    const knob = toggle.createDiv({ cls: "ns-toggle-knob" });
    knob.style.background = activeMap[topic.id] ? topic.color : "var(--text-faint)";
    if (activeMap[topic.id]) {
      knob.style.boxShadow = `0 0 8px ${topic.color}44`;
    }

    item.addEventListener("click", () => onToggle(topic.id));
  }

  private renderFocusPrompt(parent: HTMLElement, value: string, onChange: (val: string) => void, placeholder: string) {
    const focusSection = parent.createDiv();
    focusSection.createDiv({ cls: "ns-section-title", text: "Focus (optioneel)" });
    const textarea = focusSection.createEl("textarea", { cls: "ns-textarea" });
    textarea.placeholder = placeholder;
    textarea.value = value;
    textarea.addEventListener("input", (e) => {
      onChange((e.target as HTMLTextAreaElement).value);
    });
  }

  private renderOption(parent: HTMLElement, icon: string, label: string, active: boolean, color: string, onClick: () => void) {
    const option = parent.createDiv({ cls: "ns-option" });
    const labelDiv = option.createDiv({ cls: "ns-option-label" });
    labelDiv.createSpan({ text: icon });
    labelDiv.createSpan({ text: label });

    const toggle = option.createDiv({ cls: `ns-toggle ${active ? "on" : "off"}` });
    if (active) toggle.style.background = color + "88";
    const knob = toggle.createDiv({ cls: "ns-toggle-knob" });
    knob.style.background = active ? color : "var(--text-faint)";

    option.addEventListener("click", onClick);
  }

  private renderGenerateButton(parent: HTMLElement, label: string, onClick: () => void) {
    const genBtn = parent.createEl("button", {
      cls: `ns-generate-btn ${this.generating ? "generating" : ""}`,
    });
    if (this.generating) {
      genBtn.innerHTML = `<span class="ns-spinner"></span> Genereren...`;
    } else {
      genBtn.textContent = label;
    }
    genBtn.addEventListener("click", () => {
      if (!this.generating) onClick();
    });
  }

  /* ═══ RECENT ITEMS ═══ */
  private async renderRecentBriefings(parent: HTMLElement) {
    const section = parent.createDiv();
    section.createDiv({ cls: "ns-section-title", text: "Recente briefings" });
    const list = section.createDiv();
    list.style.display = "flex";
    list.style.flexDirection = "column";
    list.style.gap = "4px";

    const briefings = await this.findBriefings();

    if (briefings.length === 0) {
      const empty = list.createDiv();
      empty.style.cssText = "font-size: 12px; color: var(--text-muted); padding: 10px; text-align: center;";
      empty.textContent = "Nog geen briefings. Klik op 'Genereer briefing' om te starten.";
      return;
    }

    briefings.slice(0, 6).forEach(b => {
      const item = list.createDiv({ cls: "ns-briefing-item" });
      const header = item.createDiv({ cls: "ns-briefing-header" });
      header.createSpan({ cls: "ns-briefing-date", text: b.date });
      item.createDiv({ cls: "ns-briefing-title", text: b.title });

      item.addEventListener("click", async () => {
        const file = this.app.vault.getAbstractFileByPath(b.path);
        if (file instanceof TFile) {
          await this.app.workspace.getLeaf().openFile(file);
        }
      });
    });
  }

  private async renderRecentDagkranten(parent: HTMLElement) {
    const section = parent.createDiv();
    section.createDiv({ cls: "ns-section-title", text: "Recente dagkranten" });
    const list = section.createDiv();
    list.style.display = "flex";
    list.style.flexDirection = "column";
    list.style.gap = "4px";

    const dagkranten = await this.findDagkranten();

    if (dagkranten.length === 0) {
      const empty = list.createDiv();
      empty.style.cssText = "font-size: 12px; color: var(--text-muted); padding: 10px; text-align: center;";
      empty.textContent = "Nog geen dagkranten. Klik op 'Genereer dagkrant' om te starten.";
      return;
    }

    dagkranten.slice(0, 6).forEach(b => {
      const item = list.createDiv({ cls: "ns-briefing-item" });
      item.style.borderLeftColor = "#ea580c44";
      const header = item.createDiv({ cls: "ns-briefing-header" });
      header.createSpan({ cls: "ns-briefing-date", text: b.date });
      item.createDiv({ cls: "ns-briefing-title", text: `📰 ${b.title}` });

      item.addEventListener("click", async () => {
        const file = this.app.vault.getAbstractFileByPath(b.path);
        if (file instanceof TFile) {
          await this.app.workspace.getLeaf().openFile(file);
        }
      });
    });
  }

  /* ═══ FILE DISCOVERY ═══ */
  private async findBriefings(): Promise<{ date: string; title: string; path: string }[]> {
    const briefings: { date: string; title: string; path: string }[] = [];
    const files = this.app.vault.getMarkdownFiles();

    for (const file of files) {
      if (file.path.startsWith("Briefings/") && !file.path.includes("podcast/") && !file.path.includes("archief/")) {
        const match = file.basename.match(/^(\d{4}-\d{2}-\d{2})$/);
        if (match) {
          const dateStr = match[1];
          const parts = dateStr.split("-");
          const months = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
          const shortDate = `${parseInt(parts[2])} ${months[parseInt(parts[1]) - 1]}`;

          let title = dateStr;
          try {
            const content = await this.app.vault.read(file);
            const headingMatch = content.match(/^#\s+(.+)$/m);
            if (headingMatch) title = headingMatch[1];
          } catch { /* ignore */ }

          briefings.push({ date: shortDate, title, path: file.path });
        }
      }
    }

    briefings.sort((a, b) => b.path.localeCompare(a.path));
    return briefings;
  }

  private async findDagkranten(): Promise<{ date: string; title: string; path: string }[]> {
    const dagkranten: { date: string; title: string; path: string }[] = [];
    const allFiles = this.app.vault.getFiles();

    for (const file of allFiles) {
      if (file.path.startsWith("Briefings/") && file.basename.match(/^\d{4}-\d{2}-\d{2}-dagkrant$/)) {
        const dateMatch = file.basename.match(/^(\d{4})-(\d{2})-(\d{2})/);
        if (dateMatch) {
          const months = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
          const shortDate = `${parseInt(dateMatch[3])} ${months[parseInt(dateMatch[2]) - 1]}`;

          let title = `Dagkrant ${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]}`;
          try {
            const content = await this.app.vault.read(file);
            const titleMatch = content.match(/<title>De Dagkrant — (.+?)<\/title>/);
            if (titleMatch) title = titleMatch[1];
          } catch { /* ignore */ }

          dagkranten.push({ date: shortDate, title, path: file.path });
        }
      }
    }

    dagkranten.sort((a, b) => b.path.localeCompare(a.path));
    return dagkranten;
  }

  /* ═══ SOURCES ═══ */
  private async loadSources(): Promise<SourceConfig[]> {
    return new Promise((resolve) => {
      const home = process.env.HOME || "/home/marcel";
      const proc = spawn("python3", ["-c", `
import yaml, sys, json
with open("${home}/nieuwsstation/src/config/sources.yaml") as f:
    config = yaml.safe_load(f)
sources = []
for section_key in ["topics", "dagkrant_topics"]:
    section = config.get(section_key, {})
    for topic, data in section.items():
        if not isinstance(data, dict):
            continue
        for feed in data.get("feeds", []):
            sources.append({
                "name": feed["name"],
                "url": feed["url"].replace("https://","").split("/")[0],
                "topic": topic,
                "type": feed.get("type", "article"),
                "status": "ok",
                "section": section_key
            })
print(json.dumps(sources))
`]);
      let output = "";
      proc.stdout?.on("data", (d: Buffer) => output += d.toString());
      proc.on("close", () => {
        try {
          resolve(JSON.parse(output));
        } catch {
          resolve([]);
        }
      });
      proc.on("error", () => resolve([]));
    });
  }

  /* ═══ FOOTER ═══ */
  private renderFooter(container: HTMLElement) {
    const footer = container.createDiv({ cls: "ns-footer" });
    footer.createDiv({ cls: "ns-status-dot ok" });
    footer.createSpan({ text: "Claude Code sessie" });
    footer.createSpan({ cls: "ns-footer-sep", text: "·" });
    footer.createSpan({ text: "Nieuwsstation v0.2" });
  }

  /* ═══ GENERATION ═══ */
  private async generateBriefing() {
    this.generating = true;
    this.render();

    const selectedTopics = Object.entries(this.briefingTopics)
      .filter(([, v]) => v)
      .map(([k]) => k);

    if (selectedTopics.length === 0) {
      new Notice("Selecteer minstens één topic");
      this.generating = false;
      this.render();
      return;
    }

    const topicArgs = selectedTopics.join(" ");

    new Notice(`Briefing starten: ${topicArgs}...`);

    try {
      const home = process.env.HOME || "/home/marcel";
      const scriptPath = `${home}/nieuwsstation/scripts/generate-briefing.sh`;
      const args = [`--topics`, topicArgs, `--hours`, `24`];

      const proc = spawn("/bin/bash", [scriptPath, ...args], {
        cwd: `${home}/nieuwsstation`,
        env: {
          ...process.env,
          PATH: `${home}/.local/bin:/usr/local/bin:/usr/bin:/bin:${process.env.PATH || ""}`,
          HOME: home,
        },
      });

      let output = "";
      proc.stdout?.on("data", (d: Buffer) => {
        const line = d.toString();
        output += line;
        const match = line.match(/\[(\d)\/4\]/);
        if (match) {
          new Notice(line.trim(), 3000);
        }
      });
      proc.stderr?.on("data", (d: Buffer) => output += d.toString());

      proc.on("close", (code: number | null) => {
        this.generating = false;
        this.render();
        if (code === 0) {
          new Notice("Briefing gereed! Check de Briefings map.", 5000);
        } else {
          new Notice(`Briefing fout (code ${code}). Check de console.`, 5000);
          console.error("Nieuwsstation output:", output);
        }
      });

      proc.on("error", (err: Error) => {
        this.generating = false;
        this.render();
        new Notice(`Kon generate-briefing.sh niet starten: ${err.message}`);
      });
    } catch (err) {
      this.generating = false;
      this.render();
      new Notice(`Fout: ${err}`);
    }
  }

  private async generateDagkrant() {
    this.generating = true;
    this.render();

    // Zorg dat api_server draait voordat we beginnen
    const { spawn: _spawn } = require("child_process");
    const _home = process.env.HOME || "/home/marcel";
    const _check = _spawn("nc", ["-z", "-w1", "127.0.0.1", "7432"], { stdio: "ignore" });
    _check.on("close", (code: number) => {
      if (code !== 0) {
        const _proc = _spawn("python3", [`${_home}/nieuwsstation/src/api_server.py`], {
          detached: true, stdio: "ignore",
          env: { ...process.env, PYTHONUNBUFFERED: "1" }
        });
        _proc.unref();
      }
    });

    const selectedTopics = Object.entries(this.dagkrantTopics)
      .filter(([, v]) => v)
      .map(([k]) => k);

    if (selectedTopics.length === 0) {
      new Notice("Selecteer minstens één sectie");
      this.generating = false;
      this.render();
      return;
    }

    // Build the prompt for Claude Code
    const topicList = selectedTopics.join(", ");
    const focusArg = this.dagkrantPrompt ? ` Focus: ${this.dagkrantPrompt}` : "";

    new Notice(`Dagkrant starten: ${topicList}...`);

    const home = process.env.HOME || "/home/marcel";

    // Map topic-IDs naar canonieke sectie-IDs voor de planner
    const topicToCanonical: Record<string, string> = {
      "nederland":       "nederland",
      "wereld":          "wereld",
      "financieel_dk":   "financieel",
      "regulatoir_dk":   "regulatoir",
      "huizenmarkt_dk":  "huizenmarkt",
      "sport_dk":        "sport",
      "voetbal_dk":      "voetbal",
      "ai_tech":         "aitech",
    };
    // Custom topics mappen op zichzelf
    this.customDagkrantTopics.forEach(t => {
      topicToCanonical[t.id] = t.id;
      topicToCanonical[`${t.id}_dk`] = t.id;
    });
    const canonicalSections = [...new Set(
      selectedTopics.map(t => topicToCanonical[t] || t)
    )];

    const pyEnv = {
      ...process.env,
      PATH: `${home}/.local/bin:/usr/local/bin:/usr/bin:/bin:${process.env.PATH || ""}`,
      HOME: home,
      DAGKRANT_SECTIONS: canonicalSections.join(","),
      DAGKRANT_CUSTOM_TOPICS: JSON.stringify(this.customDagkrantTopics),
    };

    /** Hulpfunctie: spawn een commando, return exit-code als Promise */
    const runProc = (cmd: string, args: string[], cwd: string, label: string): Promise<number> =>
      new Promise((resolve) => {
        const proc = spawn(cmd, args, { cwd, env: pyEnv });
        proc.stdout?.on("data", (d: Buffer) => new Notice(d.toString().trim(), 2000));
        proc.stderr?.on("data", (d: Buffer) => console.error(`[${label}]`, d.toString()));
        proc.on("close", (code) => resolve(code ?? 1));
        proc.on("error", (err) => { console.error(`[${label}] error:`, err); resolve(1); });
      });

    try {
      // ── Stap 1: Fetch nieuwsdata ────────────────────────────────────────
      new Notice("Stap 1/5: nieuws ophalen...", 3000);
      const fetchCode = await runProc(
        "/bin/bash",
        [`${home}/nieuwsstation/scripts/fetch-dagkrant-data.sh`],
        `${home}/nieuwsstation`,
        "fetch"
      );
      if (fetchCode !== 0) {
        new Notice(`Data ophalen mislukt (code ${fetchCode})`, 5000);
        this.generating = false; this.render(); return;
      }

      // ── Stap 1b: Custom topics ophalen (Google News RSS) ───────────────
      if (this.customDagkrantTopics.some(t => this.dagkrantTopics[t.id])) {
        new Notice("Custom secties ophalen...", 2000);
        await runProc(
          "python3",
          [`${home}/nieuwsstation/src/fetch_custom_topics.py`],
          `${home}/nieuwsstation`,
          "custom-topics"
        ); // niet fataal
      }

      // ── Stap 2: Pre-selectie (180 → ~40 artikelen) ─────────────────────
      new Notice("Stap 2/5: artikelen selecteren...", 2000);
      const preselectCode = await runProc(
        "python3",
        [`${home}/nieuwsstation/src/preselect_articles.py`],
        `${home}/nieuwsstation`,
        "preselect"
      );
      if (preselectCode !== 0) {
        new Notice("Pre-selectie mislukt, doorgaan met alle data...", 3000);
        // Niet fataal: dagkrant-ready.json wordt direct gebruikt als fallback
      }

      // ── Stap 3: Pre-fetch widgets (weer + markten) ────────────────────────
      new Notice("Stap 3/5: weer en markten ophalen...", 2000);
      await runProc(
        "python3",
        [`${home}/nieuwsstation/src/fetch_widgets.py`],
        `${home}/nieuwsstation`,
        "widgets"
      ); // niet fataal: Claude gebruikt placeholders als het mislukt

      // ── Stap 4: Claude genereert JSON-plan via Python planner ───────────
      new Notice("Stap 4/5: Claude maakt redactioneel plan...", 4000);
      const focusArg2 = this.dagkrantPrompt ? `Focus: ${this.dagkrantPrompt}` : "";
      const plannerArgs = [`${home}/nieuwsstation/src/dagkrant_planner.py`];
      if (focusArg2) plannerArgs.push(focusArg2);

      // Voortgangs-notices elke 2 minuten
      const startTime = Date.now();
      const progressInterval = setInterval(() => {
        const mins = Math.round((Date.now() - startTime) / 60000);
        new Notice(`Claude aan het werk... (${mins} min)`, 3000);
      }, 120000);

      const claudeProc = spawn("python3", plannerArgs, {
        cwd: `${home}/Documents/WorkMvMOBS`,
        env: pyEnv,
      });

      let claudeOutput = "";
      claudeProc.stdout?.on("data", (d: Buffer) => { claudeOutput += d.toString(); console.log("[planner]", d.toString().trim()); });
      claudeProc.stderr?.on("data", (d: Buffer) => { claudeOutput += d.toString(); console.error("[planner]", d.toString().trim()); });

      // Timeout: 25 minuten (planner heeft zelf 2 pogingen van 12 min + 60s wacht)
      const timeout = setTimeout(() => {
        clearInterval(progressInterval);
        try { claudeProc.kill(); } catch {}
        this.generating = false; this.render();
        new Notice("Dagkrant timeout (25 min). Probeer opnieuw zonder actieve Claude Code sessie.", 8000);
      }, 1500000);

      const claudeCode = await new Promise<number>((resolve) => {
        claudeProc.on("close", (code) => resolve(code ?? 1));
        claudeProc.on("error", (err) => { console.error("[planner]", err); resolve(1); });
      });
      clearTimeout(timeout);
      clearInterval(progressInterval);

      if (claudeCode !== 0) {
        new Notice(`Planner mislukt (code ${claudeCode}).`, 5000);
        console.error("Planner output:", claudeOutput);
        this.generating = false; this.render(); return;
      }

      // ── Stap 4: Renderer JSON → HTML ─────────────────────────────────────
      new Notice("Stap 5/5: HTML renderen...", 2000);
      const renderCode = await runProc(
        "python3",
        [`${home}/nieuwsstation/src/dagkrant_renderer.py`],
        `${home}/Documents/WorkMvMOBS`,
        "renderer"
      );

      this.generating = false; this.render();

      if (renderCode === 0) {
        new Notice("✓ Dagkrant gereed! Check de Briefings map.", 8000);
      } else {
        new Notice(`Renderer mislukt (code ${renderCode}).`, 5000);
      }

    } catch (err) {
      this.generating = false; this.render();
      new Notice(`Fout: ${err}`);
    }
  }

  /**
   * Voeg één custom sectie toe aan de bestaande dagkrant.
   * Voert de volledige pipeline uit maar met alleen die sectie,
   * en laat de renderer appenden aan het bestaande HTML-bestand.
   */
  private async appendSection(sectionId: string, sectionLabel: string) {
    this.generating = true;
    this.render();
    new Notice(`Sectie "${sectionLabel}" toevoegen…`, 3000);

    const home = process.env.HOME || "/home/marcel";
    const pyEnv = {
      ...process.env,
      PATH: `${home}/.local/bin:/usr/local/bin:/usr/bin:/bin:${process.env.PATH || ""}`,
      HOME: home,
      DAGKRANT_SECTIONS: sectionId,
      DAGKRANT_CUSTOM_TOPICS: JSON.stringify(this.customDagkrantTopics),
      DAGKRANT_APPEND_MODE: "true",
    };

    const runProc = (cmd: string, args: string[], cwd: string, label: string): Promise<number> =>
      new Promise((resolve) => {
        const proc = spawn(cmd, args, { cwd, env: pyEnv });
        proc.stdout?.on("data", (d: Buffer) => new Notice(d.toString().trim(), 2000));
        proc.stderr?.on("data", (d: Buffer) => console.error(`[${label}]`, d.toString()));
        proc.on("close", (code) => resolve(code ?? 1));
        proc.on("error", (err) => { console.error(`[${label}] error:`, err); resolve(1); });
      });

    try {
      // Stap 1: Fetch (hergebruik bestaande data als die er al is, anders opnieuw)
      new Notice("Nieuws ophalen…", 2000);
      await runProc("/bin/bash", [`${home}/nieuwsstation/scripts/fetch-dagkrant-data.sh`], `${home}/nieuwsstation`, "fetch");

      // Stap 1b: Custom topics ophalen (Google News RSS) — niet fataal
      await runProc("python3", [`${home}/nieuwsstation/src/fetch_custom_topics.py`], `${home}/nieuwsstation`, "custom-topics");

      // Stap 2: Preselect
      await runProc("python3", [`${home}/nieuwsstation/src/preselect_articles.py`], `${home}/nieuwsstation`, "preselect");

      // Stap 3: Claude plannet alleen de nieuwe sectie
      new Notice(`Claude selecteert ${sectionLabel}…`, 4000);
      const plannerArgs = [`${home}/nieuwsstation/src/dagkrant_planner.py`];
      const claudeProc = spawn("python3", plannerArgs, { cwd: `${home}/Documents/WorkMvMOBS`, env: pyEnv });
      let claudeOut = "";
      claudeProc.stdout?.on("data", (d: Buffer) => { claudeOut += d.toString(); });
      claudeProc.stderr?.on("data", (d: Buffer) => { claudeOut += d.toString(); });
      const claudeCode = await new Promise<number>((resolve) => {
        claudeProc.on("close", (code) => resolve(code ?? 1));
        claudeProc.on("error", () => resolve(1));
      });
      if (claudeCode !== 0) {
        new Notice(`Planner mislukt: ${claudeOut.slice(-200)}`, 5000);
        this.generating = false; this.render(); return;
      }

      // Stap 4: Renderer voegt de sectie toe aan bestaand HTML
      new Notice("Sectie renderen…", 2000);
      const renderCode = await runProc(
        "python3",
        [`${home}/nieuwsstation/src/dagkrant_renderer.py`],
        `${home}/Documents/WorkMvMOBS`,
        "renderer"
      );

      this.generating = false; this.render();
      if (renderCode === 0) {
        new Notice(`✓ Sectie "${sectionLabel}" toegevoegd!`, 5000);
      } else {
        new Notice(`Renderer mislukt (code ${renderCode})`, 5000);
      }
    } catch (err) {
      this.generating = false; this.render();
      new Notice(`Fout: ${err}`);
    }
  }

  /** Zoek de meest recente dagkrant en geef datum + podcast-pad terug */
  private findActiveDagkrant(): { date: string; podcastFile: string; hasPodcast: boolean } {
    const { readdirSync, existsSync } = require("fs");
    const home = process.env.HOME || "/home/marcel";
    const briefDir = `${home}/Documents/WorkMvMOBS/Briefings`;
    const podcastDir = `${briefDir}/podcast`;

    // Zoek alle YYYY-MM-DD-dagkrant.html bestanden, sorteer aflopend
    let date = new Date().toISOString().slice(0, 10);
    try {
      const files = readdirSync(briefDir) as string[];
      const dagkranten = files
        .filter((f: string) => /^\d{4}-\d{2}-\d{2}-dagkrant\.html$/.test(f))
        .sort()
        .reverse();
      if (dagkranten.length > 0) {
        date = dagkranten[0].slice(0, 10); // YYYY-MM-DD
      }
    } catch {}

    const podcastFile = `${podcastDir}/${date}.md`;
    const hasPodcast = existsSync(podcastFile);
    return { date, podcastFile, hasPodcast };
  }

  private async prepareNotebookLM() {
    const { date, hasPodcast } = this.findActiveDagkrant();

    this.nlmShowFocus = true;
    this.nlmFocusLoading = true;
    this.nlmFocusText = "";
    this.render();

    // Haal focus-suggestie op (gebaseerd op bestaand script of nieuwsdata)
    try {
      const resp = await fetch(
        `http://127.0.0.1:7432/podcast-focus?date=${date}`, { method: "GET" }
      );
      if (resp.ok) {
        const data = await resp.json() as { focus?: string };
        this.nlmFocusText = data.focus || "";
      }
    } catch { /* api_server niet actief – veld blijft leeg */ }

    this.nlmFocusLoading = false;
    this.render();
  }

  private async sendToNotebookLM() {
    this.nlmSending = true;
    this.render();

    const home = process.env.HOME || "/home/marcel";
    const { date, podcastFile, hasPodcast } = this.findActiveDagkrant();

    try {
      // ── Stap 1: podcast script genereren indien ontbreekt ──────────────
      if (!hasPodcast) {
        new Notice(`Podcast script ${date} genereren…`, 4000);
        const claudeBin = await this.findClaudeBinary().catch(() => "claude");

        // Bouw nieuwscontext op vanuit beschikbare data
        let newsItems = "";
        try {
          const dataFile = "/tmp/dagkrant-ready.json";
          const { existsSync, readFileSync } = require("fs");
          if (existsSync(dataFile)) {
            const raw = JSON.parse(readFileSync(dataFile, "utf-8"));
            const lines: string[] = [];
            for (const td of Object.values(raw.topics || {}) as any[]) {
              for (const a of (td.items || td.articles || []).slice(0, 3)) {
                if (a.title) lines.push(`- ${a.title}: ${(a.summary || "").slice(0, 120)}`);
              }
              if (lines.length >= 18) break;
            }
            newsItems = lines.join("\n");
          }
        } catch {}

        // claude -p genereert de tekst → wij schrijven hem zelf naar schijf
        const prompt = `Schrijf een podcast paper van 2000-2500 woorden in vloeiend Nederlands.
Datum: ${date}. Dit is bronmateriaal voor NotebookLM Audio Overview.

Structuur (verplicht):
# Podcast Paper — ${date}
## [Thema 1 — geef een concrete titel]
[~600 woorden lopende tekst]
## [Thema 2 — geef een concrete titel]
[~600 woorden lopende tekst]
## [Thema 3 — geef een concrete titel]
[~500 woorden lopende tekst]
## Synthese: de rode draad van vandaag
[~300 woorden conclusie]

Regels: alleen lopende tekst, geen opsommingen, analytisch en verbanden leggen, schrijf voor intelligent niet-specialist publiek.
${newsItems ? `\nNieuwsitems van ${date}:\n${newsItems}` : ""}

Geef ALLEEN de tekst terug. Geen uitleg, geen code blocks.`;

        const content = await new Promise<string>((resolve) => {
          let out = "";
          const proc = spawn(claudeBin, ["-p", prompt, "--dangerously-skip-permissions", "--model", "claude-sonnet-4-6"], {
            env: { ...process.env, PATH: `${home}/.local/bin:/usr/local/bin:/usr/bin:/bin:${process.env.PATH || ""}`, HOME: home },
          });
          proc.stdout?.on("data", (d: Buffer) => { out += d.toString(); });
          const t = setTimeout(() => { proc.kill(); resolve(""); }, 600000);
          proc.on("close", () => { clearTimeout(t); resolve(out.trim()); });
          proc.on("error", () => { clearTimeout(t); resolve(""); });
        });

        if (content.length < 500) {
          new Notice(`Podcast generatie mislukt voor ${date}. Probeer opnieuw.`, 8000);
          this.nlmSending = false;
          this.render();
          return;
        }

        // Verwijder eventuele markdown code-fences
        const clean = content.replace(/^```\w*\n?/m, "").replace(/\n?```$/m, "").trim();
        const { mkdirSync, writeFileSync, dirname } = require("fs");
        mkdirSync(require("path").dirname(podcastFile), { recursive: true });
        writeFileSync(podcastFile, clean, "utf-8");
        new Notice(`Podcast script ${date} gegenereerd ✓`, 3000);
      }

      // ── Stap 2: direct spawnen van uploader (met DISPLAY) ───────────────
      new Notice("Uploaden naar NotebookLM…", 5000);
      const uploaderPath = `${home}/nieuwsstation/src/notebooklm_uploader.py`;
      const uploaderArgs = ["--file", podcastFile];
      if (this.nlmFocusText.trim()) uploaderArgs.push("--focus", this.nlmFocusText.trim());

      const nlmResult = await new Promise<{ url?: string; title?: string; error?: string }>(
        (resolve) => {
          let stdout = "";
          const proc = spawn("python3", [uploaderPath, ...uploaderArgs], {
            env: {
              ...process.env,
              PATH: `${home}/.local/bin:/usr/local/bin:/usr/bin:/bin:${process.env.PATH || ""}`,
              HOME: home,
              DISPLAY: process.env.DISPLAY || ":1",
            },
          });
          proc.stdout?.on("data", (d: Buffer) => { stdout += d.toString(); });
          proc.stderr?.on("data", (d: Buffer) => { console.log("[NLM]", d.toString().trim()); });
          const t = setTimeout(() => { proc.kill(); resolve({ error: "Timeout (5 min)" }); }, 300000);
          proc.on("close", (code: number | null) => {
            clearTimeout(t);
            try { resolve(JSON.parse(stdout.trim())); }
            catch { resolve({ error: `Uploader fout (code ${code}). Stdout: ${stdout.slice(0, 100)}` }); }
          });
          proc.on("error", (e: Error) => { clearTimeout(t); resolve({ error: e.message }); });
        }
      );

      if (nlmResult.error) {
        const msg = nlmResult.error;
        new Notice(`NotebookLM fout: ${msg}`, 8000);
        if (msg.toLowerCase().includes("ingelogd") || msg.toLowerCase().includes("setup")) {
          new Notice("Voer eenmalig uit: python3 ~/nieuwsstation/src/notebooklm_uploader.py --setup", 12000);
        }
      } else {
        this.nlmLastUrl = nlmResult.url || "";
        this.nlmLastTitle = nlmResult.title || `Dagkrant ${date}`;
        this.nlmShowFocus = false;
        new Notice("Podcast klaar in NotebookLM! Klik om te openen.", 8000);
        if (this.nlmLastUrl) window.open(this.nlmLastUrl, "_blank");
      }
    } catch (e) {
      new Notice("Onverwachte fout: " + String(e), 6000);
    }

    this.nlmSending = false;
    this.render();
  }

  private findClaudeBinary(): Promise<string> {
    const candidates = [
      `${process.env.HOME}/.local/bin/claude`,
      `${process.env.HOME}/.claude/local/claude`,
      "/usr/local/bin/claude",
      "/usr/bin/claude",
    ];

    for (const candidate of candidates) {
      try {
        require("fs").accessSync(candidate, require("fs").constants.X_OK);
        return Promise.resolve(candidate);
      } catch { /* try next */ }
    }

    return new Promise((resolve, reject) => {
      const proc = spawn("/bin/bash", ["-l", "-c", "which claude"]);
      let path = "";
      proc.stdout?.on("data", (d: Buffer) => path += d.toString().trim());
      proc.on("close", (code: number | null) => {
        if (code === 0 && path) {
          resolve(path);
        } else {
          reject("Claude binary niet gevonden");
        }
      });
    });
  }
}

/* ═══════════════════════════════════════
   PLUGIN
   ═══════════════════════════════════════ */

export default class NieuwsstationPlugin extends Plugin {
  private ensureApiServer() {
    const home = process.env.HOME || "/home/marcel";
    const { spawn } = require("child_process");

    // Gebruik nc (netcat) om snel te checken of poort 7432 open is
    const check = spawn("nc", ["-z", "-w1", "127.0.0.1", "7432"], { stdio: "ignore" });
    check.on("close", (code: number) => {
      if (code !== 0) {
        // Poort dicht — start api_server
        const proc = spawn("python3", [`${home}/nieuwsstation/src/api_server.py`], {
          detached: true, stdio: "ignore",
          env: { ...process.env, PYTHONUNBUFFERED: "1" }
        });
        proc.unref();
        console.log("[Nieuwsstation] api_server gestart (PID:", proc.pid, ")");
      }
    });
    check.on("error", () => {
      // nc niet beschikbaar — probeer direct te starten (idempotent)
      const proc = spawn("python3", [`${home}/nieuwsstation/src/api_server.py`], {
        detached: true, stdio: "ignore",
        env: { ...process.env, PYTHONUNBUFFERED: "1" }
      });
      proc.unref();
    });
  }

  async onload() {
    // Register views
    this.registerView(VIEW_TYPE, (leaf) => new CommandCenterView(leaf));
    this.registerView(BRIEFING_VIEW_TYPE, (leaf) => new BriefingView(leaf));

    // Auto-start api_server bij opstarten
    this.ensureApiServer();

    // Watchdog: controleer elke 2 minuten of de server nog draait
    const watchdog = window.setInterval(() => this.ensureApiServer(), 2 * 60 * 1000);
    this.register(() => window.clearInterval(watchdog));

    // Ribbon icon
    this.addRibbonIcon("radio", "Nieuwsstation", () => {
      this.activateView();
    });

    // Command palette
    this.addCommand({
      id: "open-command-center",
      name: "Open command center",
      callback: () => this.activateView(),
    });

    this.addCommand({
      id: "open-latest-briefing",
      name: "Open laatste briefing",
      callback: () => this.openLatestBriefing(),
    });

    this.addCommand({
      id: "generate-briefing",
      name: "Genereer briefing (alle topics)",
      callback: () => {
        this.activateView().then(() => {
          const leaves = this.app.workspace.getLeavesOfType(VIEW_TYPE);
          if (leaves.length > 0) {
            (leaves[0].view as any).generateBriefing();
          }
        });
      },
    });

    // Protocol handler: obsidian://nieuwsstation-vault?file=pad/naar/note.md
    this.registerObsidianProtocolHandler("nieuwsstation-vault", async (params) => {
      const filePath = params.file;
      if (!filePath) return;
      const abstractFile = this.app.vault.getAbstractFileByPath(filePath);
      if (abstractFile && abstractFile instanceof TFile) {
        // Open in split-right naast de actieve leaf (dagkrant)
        const newLeaf = this.app.workspace.getLeaf("split", "vertical");
        await newLeaf.openFile(abstractFile);
      }
    });

    this.addCommand({
      id: "generate-dagkrant",
      name: "Genereer dagkrant",
      callback: () => {
        this.activateView().then(() => {
          const leaves = this.app.workspace.getLeavesOfType(VIEW_TYPE);
          if (leaves.length > 0) {
            (leaves[0].view as any).activeTab = "dagkrant";
            (leaves[0].view as any).render();
            (leaves[0].view as any).generateDagkrant();
          }
        });
      },
    });
  }

  async activateView() {
    const { workspace } = this.app;
    let leaf = workspace.getLeavesOfType(VIEW_TYPE)[0];

    if (!leaf) {
      const rightLeaf = workspace.getRightLeaf(false);
      if (rightLeaf) {
        leaf = rightLeaf;
        await leaf.setViewState({ type: VIEW_TYPE, active: true });
      }
    }

    if (leaf) {
      workspace.revealLeaf(leaf);
    }
  }

  async openBriefing(jsonPath: string) {
    const { workspace } = this.app;
    const leaf = workspace.getLeaf();
    await leaf.setViewState({ type: BRIEFING_VIEW_TYPE, active: true });
    const view = leaf.view as BriefingView;
    await view.loadFile(jsonPath);
  }

  async openLatestBriefing() {
    const home = process.env.HOME || "/home/marcel";
    const dataDir = join(home, "Documents", "WorkMvMOBS", "Briefings", "data");

    if (!existsSync(dataDir)) {
      new Notice("Geen briefings gevonden. Genereer eerst een briefing.");
      return;
    }

    try {
      const files = readdirSync(dataDir)
        .filter((f: string) => f.endsWith(".json"))
        .sort()
        .reverse();

      if (files.length === 0) {
        new Notice("Geen briefings gevonden. Genereer eerst een briefing.");
        return;
      }

      await this.openBriefing(join(dataDir, files[0]));
    } catch (e) {
      new Notice(`Fout bij openen briefing: ${e}`);
    }
  }

  onunload() {}
}
