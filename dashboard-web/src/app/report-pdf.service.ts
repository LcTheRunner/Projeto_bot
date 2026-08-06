import { Injectable } from '@angular/core';
import type { jsPDF as JsPDF } from 'jspdf';
import type { UserOptions } from 'jspdf-autotable';

export interface ReportPoint { label: string; value: number; }
export interface ReportArticle {
  id: number; title: string; url: string; source: string; section: string;
  journalist?: string; publishedAt: string; risk: number; tone: string;
  impact: number; keywords: string[]; evidence: string[];
}
export interface ReportOverview {
  periodDays: number; generatedAt: string;
  kpis: { articles: number; sources: number; risk10: number; risk5: number; averageImpact: number; instagram: number; };
  byRisk: ReportPoint[]; byTone: ReportPoint[]; bySource: ReportPoint[]; bySection: ReportPoint[];
  byKeyword: ReportPoint[]; timeline: ReportPoint[]; articles: ReportArticle[];
}
export interface ReportContext {
  periodLabel: string;
  filters: string[];
  notes?: string;
  dashboardUrl?: string;
}

type PdfColor = readonly [number, number, number];

const COLORS = {
  ink: [20, 38, 45] as PdfColor,
  deepTeal: [20, 82, 83] as PdfColor,
  teal: [38, 126, 122] as PdfColor,
  sand: [194, 143, 74] as PdfColor,
  critical: [177, 52, 66] as PdfColor,
  attention: [190, 123, 30] as PdfColor,
  paper: [247, 246, 242] as PdfColor,
  mist: [233, 240, 237] as PdfColor,
  white: [255, 255, 255] as PdfColor,
  text: [39, 53, 57] as PdfColor,
  muted: [96, 108, 109] as PdfColor,
  border: [213, 222, 219] as PdfColor
};

@Injectable({ providedIn: 'root' })
export class ReportPdfService {
  async generate(data: ReportOverview, context: ReportContext): Promise<void> {
    const doc = await this.build(data, context);
    doc.save(this.fileName());
  }

  async createFile(data: ReportOverview, context: ReportContext): Promise<File> {
    const doc = await this.build(data, context);
    return new File([doc.output('blob')], this.fileName(), { type: 'application/pdf' });
  }

  download(file: File): void {
    const url = URL.createObjectURL(file);
    const link = document.createElement('a');
    link.href = url;
    link.download = file.name;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  async build(data: ReportOverview, context: ReportContext): Promise<JsPDF> {
    const [{ jsPDF }, { autoTable }] = await Promise.all([import('jspdf'), import('jspdf-autotable')]);
    const doc = new jsPDF({ unit: 'mm', format: 'a4', compress: true });
    const pageWidth = doc.internal.pageSize.getWidth();
    const margin = 14;
    const contentWidth = pageWidth - margin * 2;

    doc.setProperties({
      title: 'Panorama de impacto midiático',
      subject: `Monitoramento de notícias — ${context.periodLabel}`,
      author: 'Central de Monitoramento do MCS',
      creator: 'Mídia Radar'
    });

    this.header(doc, 'Panorama de impacto midiático', context.periodLabel, data.generatedAt, 'RESUMO EXECUTIVO');
    let y = 48;

    y = this.filterSummary(doc, context.filters, margin, y, contentWidth);
    y += 5;

    const cards = [
      { label: 'Publicações', value: String(data.kpis.articles), hint: 'no recorte', color: COLORS.deepTeal },
      { label: 'Veículos', value: String(data.kpis.sources), hint: 'fontes distintas', color: COLORS.teal },
      { label: 'Risco crítico', value: String(data.kpis.risk10), hint: 'prioridade', color: COLORS.critical },
      { label: 'Atenção', value: String(data.kpis.risk5), hint: 'acompanhar', color: COLORS.attention },
      { label: 'Impacto médio', value: data.kpis.averageImpact.toFixed(1), hint: 'escala 0–10', color: COLORS.sand }
    ];
    const gap = 3;
    const cardWidth = (contentWidth - gap * 4) / 5;
    cards.forEach((card, index) => this.kpiCard(doc, card, margin + index * (cardWidth + gap), y, cardWidth));
    y += 32;

    this.sectionTitle(doc, 'Leitura executiva', 'O que merece atenção neste período', margin, y);
    y += 11;
    const topKeyword = data.byKeyword[0];
    const topSource = data.bySource[0];
    const insights = [
      data.kpis.risk10
        ? `${data.kpis.risk10} ${data.kpis.risk10 === 1 ? 'publicação exige' : 'publicações exigem'} leitura prioritária por risco crítico.`
        : 'Nenhuma publicação foi classificada como risco crítico no período.',
      topKeyword
        ? `“${topKeyword.label}” liderou os assuntos monitorados, com ${topKeyword.value} ${topKeyword.value === 1 ? 'menção' : 'menções'}.`
        : 'Não houve um assunto dominante no recorte analisado.',
      topSource
        ? `${topSource.label} foi o veículo mais presente, com ${topSource.value} ${topSource.value === 1 ? 'publicação' : 'publicações'}.`
        : 'A cobertura ficou distribuída, sem concentração em um único veículo.'
    ];
    y = this.insightPanel(doc, insights, margin, y, contentWidth);

    const notes = context.notes?.trim();
    if (notes) {
      y += 5;
      y = this.technicalOpinion(doc, notes, margin, y, contentWidth);
    }

    const rankingY = Math.max(y + 6, 164);
    const rankingGap = 5;
    const rankingWidth = (contentWidth - rankingGap * 2) / 3;
    this.ranking(doc, 'Nível de risco', data.byRisk.slice(0, 5), margin, rankingY, rankingWidth, COLORS.critical);
    this.ranking(doc, 'Veículos em destaque', data.bySource.slice(0, 5), margin + rankingWidth + rankingGap, rankingY, rankingWidth, COLORS.deepTeal);
    this.ranking(doc, 'Assuntos mais citados', data.byKeyword.slice(0, 5), margin + (rankingWidth + rankingGap) * 2, rankingY, rankingWidth, COLORS.sand);

    const priority = [...data.articles]
      .sort((a, b) => b.risk - a.risk || b.impact - a.impact || Date.parse(b.publishedAt) - Date.parse(a.publishedAt))
      .slice(0, 10);

    if (priority.length) {
      doc.addPage();
      this.header(doc, 'Publicações prioritárias', `${priority.length} destaques selecionados para leitura`, data.generatedAt, 'CADERNO DE NOTÍCIAS');

      doc.setFillColor(...COLORS.mist);
      doc.roundedRect(margin, 47, contentWidth, 13, 1.5, 1.5, 'F');
      doc.setTextColor(...COLORS.deepTeal);
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(7.4);
      doc.text('ORDEM DE LEITURA', margin + 4, 52.5);
      doc.setTextColor(...COLORS.text);
      doc.setFont('helvetica', 'normal');
      doc.text('Risco, impacto e data de publicação definem a prioridade abaixo.', margin + 4, 57);

      const tableOptions: UserOptions = {
        startY: 65,
        head: [['Data', 'Notícia', 'Veículo', 'Risco', 'Impacto']],
        body: priority.map(article => [
          this.shortDate(article.publishedAt),
          this.ellipsis(article.title, 118),
          this.ellipsis(article.source, 34),
          this.riskLabel(article.risk),
          article.impact.toFixed(1)
        ]),
        margin: { left: margin, right: margin, bottom: 19 },
        theme: 'plain',
        pageBreak: 'avoid',
        rowPageBreak: 'avoid',
        styles: {
          font: 'helvetica', fontSize: 7.2, cellPadding: { top: 3, right: 2, bottom: 3, left: 2 },
          overflow: 'linebreak', valign: 'middle', minCellHeight: 11,
          textColor: [...COLORS.text], lineColor: [...COLORS.border], lineWidth: { bottom: 0.2 }
        },
        headStyles: {
          fillColor: [...COLORS.ink], textColor: [...COLORS.white], fontStyle: 'bold',
          fontSize: 6.8, cellPadding: { top: 3, right: 2, bottom: 3, left: 2 }
        },
        alternateRowStyles: { fillColor: [...COLORS.paper] },
        columnStyles: {
          0: { cellWidth: 23, textColor: [...COLORS.muted] },
          1: { cellWidth: 84, fontStyle: 'bold' },
          2: { cellWidth: 39 },
          3: { cellWidth: 18, halign: 'center', fontStyle: 'bold' },
          4: { cellWidth: 18, halign: 'right', fontStyle: 'bold' }
        },
        didParseCell: hook => {
          if (hook.section !== 'body' || hook.column.index !== 3) return;
          const risk = priority[hook.row.index]?.risk ?? 0;
          hook.cell.styles.textColor = [...this.riskColor(risk)];
        },
        didDrawCell: hook => {
          if (hook.section !== 'body' || hook.column.index !== 1) return;
          const article = priority[hook.row.index];
          if (article?.url) doc.link(hook.cell.x, hook.cell.y, hook.cell.width, hook.cell.height, { url: article.url });
        }
      };
      autoTable(doc, tableOptions);

      const finalY = ((doc as unknown as { lastAutoTable?: { finalY: number } }).lastAutoTable?.finalY ?? 65) + 7;
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(7.2);
      doc.setTextColor(...COLORS.muted);
      doc.text('Os títulos são clicáveis e levam à publicação original.', margin, Math.min(finalY, 276));
      if (context.dashboardUrl) {
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(...COLORS.deepTeal);
        doc.textWithLink('CONSULTAR O RECORTE COMPLETO NO DASHBOARD', pageWidth - margin, Math.min(finalY, 276), {
          url: context.dashboardUrl,
          align: 'right'
        });
      }
    }

    while (doc.getNumberOfPages() > 2) doc.deletePage(doc.getNumberOfPages());
    const totalPages = doc.getNumberOfPages();
    for (let page = 1; page <= totalPages; page++) {
      doc.setPage(page);
      this.footer(doc, page, totalPages);
    }
    return doc;
  }

  private header(doc: JsPDF, title: string, subtitle: string, generatedAt: string, edition: string): void {
    const width = doc.internal.pageSize.getWidth();
    doc.setFillColor(...COLORS.ink);
    doc.rect(0, 0, width, 40, 'F');
    doc.setFillColor(...COLORS.deepTeal);
    doc.rect(width - 53, 0, 53, 40, 'F');
    doc.setFillColor(...COLORS.sand);
    doc.rect(0, 40, width, 1.2, 'F');

    doc.setTextColor(170, 204, 200);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(6.5);
    doc.text('CENTRAL DE MONITORAMENTO DO MCS', 14, 8);
    doc.setTextColor(...COLORS.white);
    doc.setFontSize(17);
    doc.text(title, 14, 18);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(8);
    doc.setTextColor(211, 222, 221);
    doc.text(subtitle, 14, 26);
    doc.setFontSize(6.8);
    doc.text(`Atualizado em ${this.date(generatedAt)}`, 14, 33);

    doc.setTextColor(205, 226, 222);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(6.2);
    doc.text(edition, width - 26.5, 9, { align: 'center' });
    doc.setTextColor(...COLORS.white);
    doc.setFontSize(21);
    doc.text('M', width - 26.5, 23, { align: 'center' });
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(6.3);
    doc.setTextColor(202, 225, 221);
    doc.text('MÍDIA RADAR', width - 26.5, 31.5, { align: 'center' });
  }

  private filterSummary(doc: JsPDF, filters: string[], x: number, y: number, width: number): number {
    const summary = filters.length ? filters.join('  •  ') : 'Todos os conteúdos disponíveis no período';
    const lines = doc.splitTextToSize(summary, width - 28).slice(0, 2);
    const height = Math.max(12, lines.length * 3.6 + 6);
    doc.setFillColor(...COLORS.paper);
    doc.roundedRect(x, y, width, height, 1.5, 1.5, 'F');
    doc.setTextColor(...COLORS.sand);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(6.3);
    doc.text('RECORTE', x + 4, y + 5.2);
    doc.setTextColor(...COLORS.text);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7.2);
    doc.text(lines, x + 24, y + 5.2);
    return y + height;
  }

  private kpiCard(
    doc: JsPDF,
    card: { label: string; value: string; hint: string; color: PdfColor },
    x: number,
    y: number,
    width: number
  ): void {
    doc.setFillColor(...COLORS.white);
    doc.setDrawColor(...COLORS.border);
    doc.roundedRect(x, y, width, 26, 1.5, 1.5, 'FD');
    doc.setFillColor(...card.color);
    doc.roundedRect(x, y, width, 1.6, 1, 1, 'F');
    doc.setTextColor(...COLORS.muted);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(5.7);
    doc.text(card.label.toUpperCase(), x + 3.5, y + 7);
    doc.setTextColor(...COLORS.ink);
    doc.setFontSize(14.5);
    doc.text(card.value, x + 3.5, y + 17);
    doc.setTextColor(...COLORS.muted);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(5.7);
    doc.text(card.hint, x + 3.5, y + 22.5);
  }

  private sectionTitle(doc: JsPDF, title: string, subtitle: string, x: number, y: number): void {
    doc.setTextColor(...COLORS.ink);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(10.5);
    doc.text(title, x, y);
    doc.setTextColor(...COLORS.muted);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(6.5);
    doc.text(subtitle, x, y + 4.5);
  }

  private insightPanel(doc: JsPDF, insights: string[], x: number, y: number, width: number): number {
    const prepared = insights.map(insight => doc.splitTextToSize(insight, width - 18).slice(0, 2));
    const height = Math.max(31, prepared.reduce((sum, lines) => sum + Math.max(6.5, lines.length * 3.5), 0) + 6);
    doc.setFillColor(...COLORS.mist);
    doc.roundedRect(x, y, width, height, 2, 2, 'F');
    let rowY = y + 7;
    prepared.forEach((lines, index) => {
      doc.setFillColor(...COLORS.deepTeal);
      doc.circle(x + 5.2, rowY - 1.3, 2.2, 'F');
      doc.setTextColor(...COLORS.white);
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(6.2);
      doc.text(String(index + 1), x + 5.2, rowY - 0.3, { align: 'center' });
      doc.setTextColor(...COLORS.text);
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(7.5);
      doc.text(lines, x + 11, rowY);
      rowY += Math.max(6.5, lines.length * 3.5);
    });
    return y + height;
  }

  private technicalOpinion(doc: JsPDF, notes: string, x: number, y: number, width: number): number {
    const lines = doc.splitTextToSize(notes.replace(/\s+/g, ' ').slice(0, 1200), width - 12).slice(0, 5);
    const height = Math.max(20, lines.length * 3.8 + 10);
    doc.setFillColor(...COLORS.paper);
    doc.setDrawColor(...COLORS.border);
    doc.roundedRect(x, y, width, height, 2, 2, 'FD');
    doc.setFillColor(...COLORS.sand);
    doc.rect(x, y, 2, height, 'F');
    doc.setTextColor(...COLORS.deepTeal);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(6.4);
    doc.text('PARECER TÉCNICO', x + 6, y + 6);
    doc.setTextColor(...COLORS.text);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7.3);
    doc.text(lines, x + 6, y + 11.5);
    return y + height;
  }

  private ranking(doc: JsPDF, title: string, items: ReportPoint[], x: number, y: number, width: number, accent: PdfColor): void {
    const height = 88;
    doc.setFillColor(...COLORS.white);
    doc.setDrawColor(...COLORS.border);
    doc.roundedRect(x, y, width, height, 2, 2, 'FD');
    doc.setFillColor(...accent);
    doc.rect(x, y, width, 1.4, 'F');
    doc.setTextColor(...COLORS.ink);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(7.4);
    doc.text(title.toUpperCase(), x + 4, y + 8);
    const max = Math.max(...items.map(item => item.value), 1);
    items.forEach((item, index) => {
      const rowY = y + 18 + index * 13;
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(6.5);
      doc.setTextColor(...COLORS.text);
      doc.text(this.ellipsis(item.label.replaceAll('_', ' '), 25), x + 4, rowY);
      doc.setFont('helvetica', 'bold');
      doc.text(String(item.value), x + width - 4, rowY, { align: 'right' });
      doc.setFillColor(...COLORS.mist);
      doc.roundedRect(x + 4, rowY + 2.5, width - 8, 2.2, 1, 1, 'F');
      doc.setFillColor(...accent);
      doc.roundedRect(x + 4, rowY + 2.5, Math.max(1.2, (width - 8) * item.value / max), 2.2, 1, 1, 'F');
    });
    if (!items.length) {
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(7);
      doc.setTextColor(...COLORS.muted);
      doc.text('Sem dados no período.', x + 4, y + 20);
    }
  }

  private footer(doc: JsPDF, page: number, total: number): void {
    const width = doc.internal.pageSize.getWidth();
    const height = doc.internal.pageSize.getHeight();
    doc.setDrawColor(...COLORS.border);
    doc.line(14, height - 12, width - 14, height - 12);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(6.5);
    doc.setTextColor(...COLORS.muted);
    doc.text('CENTRAL DE MONITORAMENTO DO MCS  •  DOCUMENTO DE APOIO À ANÁLISE', 14, height - 7);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(...COLORS.deepTeal);
    doc.text(`PÁGINA ${page} DE ${total}`, width - 14, height - 7, { align: 'right' });
  }

  private riskLabel(risk: number): string {
    return risk === 10 ? 'Crítico' : risk === 5 ? 'Atenção' : 'Regular';
  }

  private riskColor(risk: number): PdfColor {
    return risk === 10 ? COLORS.critical : risk === 5 ? COLORS.attention : COLORS.deepTeal;
  }

  private ellipsis(value: string, max: number): string {
    const clean = value.trim().replace(/\s+/g, ' ');
    return clean.length > max ? `${clean.slice(0, max - 1).trim()}…` : clean;
  }

  private date(value: string): string {
    return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value));
  }

  private shortDate(value: string): string {
    return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short' }).format(new Date(value));
  }

  private fileName(): string {
    const stamp = new Date().toISOString().slice(0, 10);
    return `panorama-midiatico-${stamp}.pdf`;
  }
}
