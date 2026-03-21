import { ItemView, WorkspaceLeaf, TFile, Notice } from "obsidian";
import { readFileSync, existsSync } from "fs";
import { join } from "path";

const BRIEFING_VIEW_TYPE = "nieuwsstation-briefing-view";

interface Article {
  title: string;
  summary: string;
  link: string;
  published: string;
  source_name: string;
  source_type: string;
  source_url: string;
  extended_summary: string;
  impact_analysis: string;
  action_items: string[];
  vault_links: string[];
  tags: string[];
}

interface Topic {
  id: string;
  label: string;
  icon: string;
  color: string;
  article_count: number;
  articles: Article[];
}

interface VaultNote {
  title: string;
  path: string;
  score: number;
  excerpt: string;
  tags: string[];
}

interface BriefingData {
  version: number;
  date: string;
  date_nl: string;
  generated: string;
  focus: string | null;
  total_sources: number;
  topics: Topic[];
  vault_notes: VaultNote[];
  cross_analysis: string;
}

/* ═══════════════════════════════════════
   CATPPUCCIN MOCHA COLORS
   ═══════════════════════════════════════ */
const C = {
  base: "#1e1e2e", mantle: "#181825", crust: "#11111b",
  surface0: "#313244", surface1: "#45475a", surface2: "#585b70",
  overlay0: "#6c7086", overlay1: "#7f849c",
  text: "#cdd6f4", subtext0: "#a6adc8", subtext1: "#bac2de",
  lavender: "#b4befe", blue: "#89b4fa", sapphire: "#74c7ec",
  teal: "#94e2d5", green: "#a6e3a1", yellow: "#f9e2af",
  peach: "#fab387", red: "#f38ba8", mauve: "#cba6f7",
  pink: "#f5c2e7", flamingo: "#f2cdcd", rosewater: "#f5e0dc",
};

const TYPE_COLORS: Record<string, string> = {
  article: C.sapphire, paper: C.mauve, data: C.green,
  regulation: C.blue, news_api: C.peach,
};

const TYPE_LABELS: Record<string, string> = {
  article: "Artikel", paper: "Paper", data: "Dataset",
  regulation: "Regulering", news_api: "Nieuws",
};

export { BRIEFING_VIEW_TYPE };

export class BriefingView extends ItemView {
  private data: BriefingData | null = null;
  private activeTab: string = "";
  private expandedArticles: Set<string> = new Set();
  private jsonPath: string = "";

  constructor(leaf: WorkspaceLeaf) {
    super(leaf);
  }

  getViewType() { return BRIEFING_VIEW_TYPE; }
  getDisplayText() { return this.data ? `Briefing ${this.data.date}` : "Briefing"; }
  getIcon() { return "newspaper"; }

  async loadFile(jsonPath: string) {
    this.jsonPath = jsonPath;
    try {
      const content = readFileSync(jsonPath, "utf-8");
      this.data = JSON.parse(content);
      if (this.data && this.data.topics.length > 0) {
        this.activeTab = this.data.topics[0].id;
      }
      this.render();
    } catch (e) {
      console.error("Failed to load briefing:", e);
    }
  }

  async onOpen() {
    this.render();
  }

  private render() {
    const container = this.containerEl.children[1] as HTMLElement;
    container.empty();
    container.addClass("nb-root");

    if (!this.data) {
      container.createDiv({ text: "Geen briefing data geladen.", cls: "nb-empty" });
      return;
    }

    this.renderTabBar(container);
    this.renderBreadcrumb(container);
    this.renderContent(container);
  }

  /* ─── Tab Bar ─── */
  private renderTabBar(parent: HTMLElement) {
    const bar = parent.createDiv({ cls: "nb-tabbar" });

    this.data!.topics.forEach(topic => {
      const tab = bar.createDiv({
        cls: `nb-tab ${this.activeTab === topic.id ? "active" : ""}`,
      });
      tab.createSpan({ text: `${topic.icon} ${topic.label}` });
      if (this.activeTab === topic.id) {
        const close = tab.createSpan({ cls: "nb-tab-close", text: "×" });
        close.addEventListener("click", (e) => { e.stopPropagation(); });
      }
      tab.addEventListener("click", () => {
        this.activeTab = topic.id;
        this.render();
      });
    });

    // Extra context tabs from vault
    this.data!.vault_notes.slice(0, 2).forEach(note => {
      const tab = bar.createDiv({ cls: "nb-tab dim" });
      tab.createSpan({ text: note.title.slice(0, 20) });
      tab.addEventListener("click", async () => {
        const file = this.app.vault.getAbstractFileByPath(note.path);
        if (file instanceof TFile) {
          await this.app.workspace.getLeaf().openFile(file);
        }
      });
    });
  }

  /* ─── Breadcrumb ─── */
  private renderBreadcrumb(parent: HTMLElement) {
    const topic = this.data!.topics.find(t => t.id === this.activeTab);
    if (!topic) return;

    const bc = parent.createDiv({ cls: "nb-breadcrumb" });
    bc.innerHTML = `WorkMvMOBS / Briefings / ${this.data!.date.slice(0, 7).replace("-", " / ")} / ${topic.label}`;
  }

  /* ─── Content ─── */
  private renderContent(parent: HTMLElement) {
    const topic = this.data!.topics.find(t => t.id === this.activeTab);
    if (!topic) return;

    const content = parent.createDiv({ cls: "nb-content" });

    // Topic header
    const header = content.createDiv({ cls: "nb-topic-header" });
    header.innerHTML = `
      <span class="nb-topic-icon" style="color: ${topic.color}">${topic.icon}</span>
      <span class="nb-topic-label" style="color: ${topic.color}">${topic.label}</span>
      <span class="nb-topic-count">${topic.article_count} artikelen</span>
    `;

    // Articles
    topic.articles.forEach((article, idx) => {
      this.renderArticle(content, article, `${topic.id}-${idx}`, topic.color);
    });

    // Cross analysis (show on first tab)
    if (this.activeTab === this.data!.topics[0]?.id) {
      this.renderCrossAnalysis(content);
      this.renderVaultNotes(content);
    }
  }

  /* ─── Article Card ─── */
  private renderArticle(parent: HTMLElement, article: Article, key: string, topicColor: string) {
    const isExpanded = this.expandedArticles.has(key);
    const card = parent.createDiv({ cls: `nb-article ${isExpanded ? "expanded" : ""}` });
    card.style.borderLeftColor = topicColor;

    // Header (always visible)
    const header = card.createDiv({ cls: "nb-article-header" });

    const titleRow = header.createDiv({ cls: "nb-article-title-row" });
    const title = titleRow.createDiv({ cls: "nb-article-title" });
    title.textContent = article.title;

    const chevron = titleRow.createDiv({ cls: `nb-chevron ${isExpanded ? "open" : ""}` });
    chevron.innerHTML = "▾";

    // Summary (always visible)
    if (article.summary) {
      const summary = header.createDiv({ cls: "nb-article-summary" });
      summary.textContent = article.summary;
    }

    // Source + time (always visible)
    const meta = header.createDiv({ cls: "nb-article-meta" });
    const sourceType = TYPE_LABELS[article.source_type] || "Artikel";
    const sourceColor = TYPE_COLORS[article.source_type] || C.sapphire;
    meta.innerHTML = `
      <span class="nb-source-badge" style="background: ${sourceColor}22; color: ${sourceColor}">${sourceType}</span>
      <span class="nb-source-name">${article.source_name}</span>
      ${article.published ? `<span class="nb-time">${_timeAgo(article.published)}</span>` : ""}
    `;

    // Toggle
    header.addEventListener("click", () => {
      if (isExpanded) {
        this.expandedArticles.delete(key);
      } else {
        this.expandedArticles.add(key);
      }
      this.render();
    });

    // Expanded content
    if (isExpanded) {
      this.renderExpandedContent(card, article, topicColor);
    }
  }

  /* ─── Expanded Article Content ─── */
  private renderExpandedContent(card: HTMLElement, article: Article, topicColor: string) {
    const expanded = card.createDiv({ cls: "nb-expanded" });

    // Sources section
    const sourcesSection = expanded.createDiv({ cls: "nb-section" });
    sourcesSection.createDiv({ cls: "nb-section-title", text: "BRONNEN" });

    const sourceLink = sourcesSection.createEl("a", { cls: "nb-source-link", href: article.link });
    sourceLink.target = "_blank";
    const sourceColor = TYPE_COLORS[article.source_type] || C.sapphire;
    const sourceLabel = TYPE_LABELS[article.source_type] || "Artikel";
    sourceLink.innerHTML = `
      <span class="nb-sl-badge" style="background: ${sourceColor}22; color: ${sourceColor}; border: 1px solid ${sourceColor}33">${sourceLabel}</span>
      <span class="nb-sl-name">${article.source_name}: ${article.title.slice(0, 50)}${article.title.length > 50 ? "..." : ""}</span>
      <span class="nb-sl-url">${article.source_url}</span>
      <span class="nb-sl-arrow">↗</span>
    `;

    // Extended summary
    if (article.extended_summary || article.summary) {
      const summarySection = expanded.createDiv({ cls: "nb-section" });
      summarySection.createDiv({ cls: "nb-section-title", text: "UITGEBREIDE SAMENVATTING" });
      const summaryBox = summarySection.createDiv({ cls: "nb-summary-box" });
      summaryBox.textContent = article.extended_summary || article.summary;
    }

    // Impact analysis
    if (article.impact_analysis) {
      const impactSection = expanded.createDiv({ cls: "nb-section" });
      impactSection.createDiv({ cls: "nb-section-title", text: "IMPACT ANALYSE" });
      const impactBox = impactSection.createDiv({ cls: "nb-impact-box" });
      impactBox.style.borderLeftColor = topicColor;
      impactBox.textContent = article.impact_analysis;
    }

    // Action items
    if (article.action_items && article.action_items.length > 0) {
      const actionTitle = expanded.createDiv({ cls: "nb-action-title" });
      actionTitle.style.color = C.peach;
      actionTitle.textContent = "Actiepunten";
      const actionList = expanded.createEl("ol", { cls: "nb-action-list" });
      article.action_items.forEach(item => {
        actionList.createEl("li", { text: item });
      });
    }

    // Vault links
    if (article.vault_links && article.vault_links.length > 0) {
      const vaultSection = expanded.createDiv({ cls: "nb-section" });
      vaultSection.createDiv({ cls: "nb-section-title", text: "GERELATEERDE VAULT NOTES" });
      const pills = vaultSection.createDiv({ cls: "nb-vault-pills" });
      article.vault_links.forEach(link => {
        const pill = pills.createEl("span", { cls: "nb-vault-pill", text: `[[${link}]]` });
        pill.addEventListener("click", async () => {
          // Try to open the vault note
          const files = this.app.vault.getMarkdownFiles();
          const match = files.find(f => f.basename === link);
          if (match) {
            await this.app.workspace.getLeaf().openFile(match);
          }
        });
      });
    }

    // Action buttons
    const buttons = expanded.createDiv({ cls: "nb-action-buttons" });

    this.createActionButton(buttons, "💾", "Opslaan als note in vault", C.teal, () => {
      new Notice("Artikel opgeslagen in vault");
    });
    this.createActionButton(buttons, "🔍", "Diepere analyse genereren", C.sapphire, () => {
      new Notice("Diepere analyse wordt gegenereerd...");
    });
    this.createActionButton(buttons, "🎙️", "Podcast paper maken", C.peach, () => {
      new Notice("Podcast paper wordt aangemaakt...");
    });
    this.createActionButton(buttons, "📋", "Kopieer samenvatting", C.overlay1, () => {
      navigator.clipboard.writeText(`${article.title}\n\n${article.summary}`);
      new Notice("Gekopieerd naar klembord");
    });
  }

  private createActionButton(parent: HTMLElement, icon: string, label: string, color: string, onClick: () => void) {
    const btn = parent.createEl("button", { cls: "nb-action-btn" });
    btn.style.setProperty("--btn-color", color);
    btn.innerHTML = `<span>${icon}</span> ${label}`;
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      onClick();
      btn.innerHTML = `<span>✓</span> Klaar!`;
      setTimeout(() => {
        btn.innerHTML = `<span>${icon}</span> ${label}`;
      }, 1500);
    });
  }

  /* ─── Cross Analysis ─── */
  private renderCrossAnalysis(parent: HTMLElement) {
    const section = parent.createDiv({ cls: "nb-cross-section" });

    const header = section.createDiv({ cls: "nb-topic-header" });
    header.innerHTML = `
      <span class="nb-topic-icon" style="color: ${C.lavender}">🔗</span>
      <span class="nb-topic-label" style="color: ${C.lavender}">Kruisverband-analyse</span>
    `;

    const box = section.createDiv({ cls: "nb-cross-box" });
    if (this.data!.cross_analysis) {
      box.textContent = this.data!.cross_analysis;
    } else {
      box.innerHTML = `<em style="color: ${C.overlay0}">Kruisverband-analyse wordt gegenereerd door Claude bij het aanmaken van de briefing.</em>`;
    }
  }

  /* ─── Vault Notes ─── */
  private renderVaultNotes(parent: HTMLElement) {
    if (!this.data!.vault_notes || this.data!.vault_notes.length === 0) return;

    const section = parent.createDiv({ cls: "nb-section" });
    section.createDiv({ cls: "nb-section-title", text: "GERELATEERDE VAULT NOTES" });
    const pills = section.createDiv({ cls: "nb-vault-pills" });

    this.data!.vault_notes.forEach(note => {
      const pill = pills.createEl("span", { cls: "nb-vault-pill" });
      pill.textContent = `[[${note.title}]]`;
      pill.title = `Score: ${note.score} — ${note.excerpt.slice(0, 100)}...`;
      pill.addEventListener("click", async () => {
        const file = this.app.vault.getAbstractFileByPath(note.path);
        if (file instanceof TFile) {
          await this.app.workspace.getLeaf().openFile(file);
        }
      });
    });
  }
}

/* ─── Helpers ─── */
function _timeAgo(isoDate: string): string {
  try {
    const date = new Date(isoDate);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 60) return `${diffMins} min`;
    if (diffHours < 24) return `${diffHours} uur`;
    return `${diffDays}d`;
  } catch {
    return "";
  }
}
