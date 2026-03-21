import { Plugin, WorkspaceLeaf, ItemView, Notice, TFile } from "obsidian";
import { spawn } from "child_process";
import { BriefingView, BRIEFING_VIEW_TYPE } from "./BriefingView";
import { join } from "path";
import { existsSync, readdirSync } from "fs";

const VIEW_TYPE = "nieuwsstation-command-center";

interface TopicConfig {
  id: string;
  label: string;
  icon: string;
  desc: string;
  color: string;
  active: boolean;
}

const TOPICS: TopicConfig[] = [
  { id: "regulatoir", label: "Regulatoir", icon: "📋", desc: "EBA, ECB, DNB, BIS", color: "#89b4fa", active: true },
  { id: "huizenmarkt", label: "Huizenmarkt", icon: "🏠", desc: "Calcasa, NVM, CBS", color: "#a6e3a1", active: true },
  { id: "financieel", label: "Financieel", icon: "📊", desc: "FD, NRC, Bloomberg", color: "#fab387", active: true },
  { id: "tech", label: "Tech & AI", icon: "⚡", desc: "AI nieuws, LLMs, tools", color: "#cba6f7", active: false },
  { id: "sport", label: "Sport", icon: "⚽", desc: "F1, schaken, voetbal", color: "#a6e3a1", active: false },
  { id: "ai_nieuws", label: "AI Nieuws", icon: "🤖", desc: "Papers, benchmarks", color: "#cba6f7", active: false },
];

/* ═══════════════════════════════════════
   COMMAND CENTER VIEW
   ═══════════════════════════════════════ */

class CommandCenterView extends ItemView {
  private activeTab: "briefing" | "bronnen" | "archief" = "briefing";
  private activeTopics: Record<string, boolean> = {};
  private customPrompt: string = "";
  private podcastEnabled: boolean = true;
  private vaultContext: boolean = true;
  private generating: boolean = false;

  constructor(leaf: WorkspaceLeaf) {
    super(leaf);
    TOPICS.forEach(t => this.activeTopics[t.id] = t.active);
  }

  getViewType() { return VIEW_TYPE; }
  getDisplayText() { return "Nieuwsstation"; }
  getIcon() { return "radio"; }

  async onOpen() {
    this.render();
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
      case "bronnen": this.renderBronnenTab(content); break;
      case "archief": this.renderArchiefTab(content); break;
    }
  }

  private renderBriefingTab(parent: HTMLElement) {
    const panel = parent.createDiv({ cls: "ns-panel" });

    // Topic selector
    const topicSection = panel.createDiv();
    topicSection.createDiv({ cls: "ns-section-title", text: "Topics" });
    const topicList = topicSection.createDiv({ cls: "ns-topic-list" });

    TOPICS.forEach(t => {
      const item = topicList.createDiv({
        cls: `ns-topic-item ${this.activeTopics[t.id] ? "active" : ""}`,
      });
      if (this.activeTopics[t.id]) {
        item.style.borderColor = t.color + "33";
      }

      item.createSpan({ cls: "ns-topic-icon", text: t.icon });
      const info = item.createDiv({ cls: "ns-topic-info" });
      const name = info.createDiv({ cls: "ns-topic-name", text: t.label });
      name.style.color = this.activeTopics[t.id] ? "var(--text-normal)" : "var(--text-muted)";
      info.createDiv({ cls: "ns-topic-desc", text: t.desc });

      const toggle = item.createDiv({
        cls: `ns-toggle ${this.activeTopics[t.id] ? "on" : "off"}`,
      });
      if (this.activeTopics[t.id]) {
        toggle.style.background = t.color + "88";
      }
      const knob = toggle.createDiv({ cls: "ns-toggle-knob" });
      knob.style.background = this.activeTopics[t.id] ? t.color : "var(--text-faint)";
      if (this.activeTopics[t.id]) {
        knob.style.boxShadow = `0 0 8px ${t.color}44`;
      }

      item.addEventListener("click", () => {
        this.activeTopics[t.id] = !this.activeTopics[t.id];
        this.render();
      });
    });

    // Focus prompt
    const focusSection = panel.createDiv();
    focusSection.createDiv({ cls: "ns-section-title", text: "Focus (optioneel)" });
    const textarea = focusSection.createEl("textarea", { cls: "ns-textarea" });
    textarea.placeholder = "Bijv. 'Focus op CRR3 leverage ratio impact' of 'Vergelijk ECB en EBA standpunten'";
    textarea.value = this.customPrompt;
    textarea.addEventListener("input", (e) => {
      this.customPrompt = (e.target as HTMLTextAreaElement).value;
    });

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
    const genBtn = panel.createEl("button", {
      cls: `ns-generate-btn ${this.generating ? "generating" : ""}`,
    });
    if (this.generating) {
      genBtn.innerHTML = `<span class="ns-spinner"></span> Briefing genereren...`;
    } else {
      genBtn.textContent = "Genereer briefing";
    }
    genBtn.addEventListener("click", () => {
      if (!this.generating) this.generateBriefing();
    });

    // Telegram hint
    const hint = panel.createDiv({ cls: "ns-hint" });
    hint.createDiv({ cls: "ns-hint-label", text: "Telegram shortcut" });
    hint.createEl("code", { cls: "ns-hint-code", text: "/briefing regulatoir huizenmarkt" });

    // Recent briefings
    this.renderRecentBriefings(panel);
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

  private async renderRecentBriefings(parent: HTMLElement) {
    const section = parent.createDiv();
    section.createDiv({ cls: "ns-section-title", text: "Recente briefings" });
    const list = section.createDiv();
    list.style.display = "flex";
    list.style.flexDirection = "column";
    list.style.gap = "4px";

    // Zoek briefing bestanden in de vault
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

          // Probeer titel uit frontmatter of eerste heading
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

  private renderBronnenTab(parent: HTMLElement) {
    const panel = parent.createDiv({ cls: "ns-panel" });
    panel.createDiv({ cls: "ns-section-title", text: "RSS & Data bronnen" });

    // Laad bronnen uit sources.yaml via een shell command
    this.loadSources().then(sources => {
      sources.forEach(s => {
        const item = panel.createDiv({ cls: "ns-source-item" });
        item.createDiv({ cls: `ns-status-dot ${s.status}` });
        const info = item.createDiv({ cls: "ns-source-info" });
        info.createDiv({ cls: "ns-source-name", text: s.name });
        info.createDiv({ cls: "ns-source-url", text: s.url });
        item.createSpan({ cls: "ns-source-time", text: s.topic });
      });

      const addBtn = panel.createEl("button", { cls: "ns-add-source", text: "+ Bron toevoegen" });
      addBtn.addEventListener("click", () => {
        new Notice("Open sources.yaml om bronnen toe te voegen:\n~/nieuwsstation/src/config/sources.yaml");
      });
    });
  }

  private async loadSources(): Promise<{ name: string; url: string; topic: string; status: string }[]> {
    return new Promise((resolve) => {
      const proc = spawn("python3", ["-c", `
import yaml, sys
with open("${process.env.HOME}/nieuwsstation/src/config/sources.yaml") as f:
    config = yaml.safe_load(f)
import json
sources = []
for topic, data in config.get("topics", {}).items():
    for feed in data.get("feeds", []):
        sources.append({"name": feed["name"], "url": feed["url"].replace("https://","").split("/")[0], "topic": topic, "status": "ok"})
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

  private renderArchiefTab(parent: HTMLElement) {
    const panel = parent.createDiv({ cls: "ns-panel" });

    const searchRow = panel.createDiv();
    searchRow.style.display = "flex";
    searchRow.style.alignItems = "center";
    searchRow.style.gap = "8px";
    searchRow.style.marginBottom = "8px";

    const input = searchRow.createEl("input", { cls: "ns-search-input" });
    input.placeholder = "Zoek in briefings...";

    const list = panel.createDiv();
    list.style.display = "flex";
    list.style.flexDirection = "column";
    list.style.gap = "4px";

    this.findBriefings().then(briefings => {
      if (briefings.length === 0) {
        list.createDiv({
          text: "Nog geen briefings in het archief.",
          attr: { style: "font-size: 12px; color: var(--text-muted); padding: 10px; text-align: center;" }
        });
        return;
      }

      let filtered = briefings;

      const renderList = () => {
        list.empty();
        filtered.forEach(b => {
          const item = list.createDiv({ cls: "ns-archive-item" });
          item.createSpan({ cls: "ns-archive-date", text: b.date });
          item.createDiv({ cls: "ns-archive-title", text: b.title });
          item.createSpan({ cls: "ns-archive-icon", text: "📄" });

          item.addEventListener("click", async () => {
            const file = this.app.vault.getAbstractFileByPath(b.path);
            if (file instanceof TFile) {
              await this.app.workspace.getLeaf().openFile(file);
            }
          });
        });
      };

      renderList();

      input.addEventListener("input", () => {
        const query = input.value.toLowerCase();
        filtered = briefings.filter(b =>
          b.title.toLowerCase().includes(query) || b.date.toLowerCase().includes(query)
        );
        renderList();
      });
    });
  }

  private renderFooter(container: HTMLElement) {
    const footer = container.createDiv({ cls: "ns-footer" });
    footer.createDiv({ cls: "ns-status-dot ok" });
    footer.createSpan({ text: "Claude Code sessie" });
    footer.createSpan({ cls: "ns-footer-sep", text: "·" });
    footer.createSpan({ text: "Nieuwsstation v0.1" });
  }

  private async generateBriefing() {
    this.generating = true;
    this.render();

    const selectedTopics = Object.entries(this.activeTopics)
      .filter(([, v]) => v)
      .map(([k]) => k);

    if (selectedTopics.length === 0) {
      new Notice("Selecteer minstens één topic");
      this.generating = false;
      this.render();
      return;
    }

    const topicArgs = selectedTopics.join(" ");
    const focusArg = this.customPrompt ? ` "${this.customPrompt}"` : "";
    const promptParts = [`/briefing ${topicArgs}${focusArg}`];

    if (!this.podcastEnabled) promptParts.push("--no-podcast");
    if (!this.vaultContext) promptParts.push("--no-vault");

    const prompt = promptParts.join(" ");

    new Notice(`Briefing starten: ${topicArgs}...`);

    try {
      // Find claude binary
      const claudePath = await this.findClaudeBinary();

      const home = process.env.HOME || "/home/marcel";
      const proc = spawn(claudePath, ["-p", `Genereer een briefing voor de volgende topics: ${topicArgs}.${this.customPrompt ? ` Focus: ${this.customPrompt}` : ""} Volg het /briefing command in ~/.claude/commands/briefing.md.`], {
        cwd: `${home}/nieuwsstation`,
        env: {
          ...process.env,
          PATH: `${home}/.local/bin:/usr/local/bin:/usr/bin:/bin:${process.env.PATH || ""}`,
          HOME: home,
        },
      });

      let output = "";
      proc.stdout?.on("data", (d: Buffer) => output += d.toString());
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
        new Notice(`Kon Claude niet starten: ${err.message}`);
      });
    } catch (err) {
      this.generating = false;
      this.render();
      new Notice(`Fout: ${err}`);
    }
  }

  private findClaudeBinary(): Promise<string> {
    const fs = require("fs");
    // Bekende locaties voor claude binary
    const candidates = [
      `${process.env.HOME}/.local/bin/claude`,
      `${process.env.HOME}/.claude/local/claude`,
      "/usr/local/bin/claude",
      "/usr/bin/claude",
    ];

    for (const candidate of candidates) {
      try {
        fs.accessSync(candidate, fs.constants.X_OK);
        return Promise.resolve(candidate);
      } catch { /* try next */ }
    }

    // Fallback: probeer via shell
    return new Promise((resolve, reject) => {
      const proc = spawn("/bin/bash", ["-l", "-c", "which claude"]);
      let path = "";
      proc.stdout?.on("data", (d: Buffer) => path += d.toString().trim());
      proc.on("close", (code: number | null) => {
        if (code === 0 && path) {
          resolve(path);
        } else {
          reject("Claude binary niet gevonden. Installeer Claude Code of stel het pad in.");
        }
      });
    });
  }
}

/* ═══════════════════════════════════════
   PLUGIN
   ═══════════════════════════════════════ */

export default class NieuwsstationPlugin extends Plugin {
  async onload() {
    // Register views
    this.registerView(VIEW_TYPE, (leaf) => new CommandCenterView(leaf));
    this.registerView(BRIEFING_VIEW_TYPE, (leaf) => new BriefingView(leaf));

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
