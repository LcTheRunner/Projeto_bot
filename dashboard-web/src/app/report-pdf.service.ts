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

@Injectable({ providedIn: 'root' })
export class ReportPdfService {
  async generate(data: ReportOverview, context: ReportContext): Promise<void> {
    const doc = await this.build(data, context);
    const stamp = new Date().toISOString().slice(0, 10);
    doc.save(`resumo-executivo-midia-${stamp}.pdf`);
  }

  async build(data: ReportOverview, context: ReportContext): Promise<JsPDF> {
    const [{ jsPDF }, { autoTable }] = await Promise.all([import('jspdf'), import('jspdf-autotable')]);
    const doc = new jsPDF({ unit: 'mm', format: 'a4' });
    const pageWidth = doc.internal.pageSize.getWidth();
    const margin = 14;
    const contentWidth = pageWidth - margin * 2;

    this.header(doc, 'Resumo executivo de impacto midiático', context.periodLabel, data.generatedAt);
    let y = 47;

    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7.5);
    doc.setTextColor(91, 99, 121);
    const filterText = context.filters.length ? `Filtros: ${context.filters.join(' • ')}` : 'Abrangência: todos os conteúdos do período';
    const filterLines = doc.splitTextToSize(filterText, contentWidth).slice(0, 2);
    doc.text(filterLines, margin, y);
    y += filterLines.length * 3.6 + 4;

    const cards = [
      { label: 'Notícias', value: String(data.kpis.articles), color: [124, 92, 255] as const },
      { label: 'Veículos', value: String(data.kpis.sources), color: [63, 145, 255] as const },
      { label: 'Risco 10', value: String(data.kpis.risk10), color: [232, 71, 99] as const },
      { label: 'Risco 5', value: String(data.kpis.risk5), color: [235, 158, 39] as const },
      { label: 'Impacto médio', value: data.kpis.averageImpact.toFixed(2), color: [69, 190, 154] as const }
    ];
    const gap = 3;
    const cardWidth = (contentWidth - gap * 4) / 5;
    cards.forEach((card, index) => {
      const x = margin + index * (cardWidth + gap);
      doc.setFillColor(246, 247, 251);
      doc.setDrawColor(224, 227, 237);
      doc.roundedRect(x, y, cardWidth, 24, 2, 2, 'FD');
      doc.setFillColor(card.color[0], card.color[1], card.color[2]);
      doc.rect(x, y, 1.7, 24, 'F');
      doc.setTextColor(118, 126, 148);
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(6.4);
      doc.text(card.label.toUpperCase(), x + 4, y + 7);
      doc.setTextColor(28, 37, 62);
      doc.setFontSize(15);
      doc.text(card.value, x + 4, y + 17);
    });
    y += 32;

    this.sectionTitle(doc, 'Leitura executiva', margin, y);
    y += 7;
    const topKeyword = data.byKeyword[0];
    const topSource = data.bySource[0];
    const insights = [
      data.kpis.risk10
        ? `${data.kpis.risk10} notícias foram classificadas como risco 10 e devem ser lidas com prioridade.`
        : 'O período não apresentou notícias classificadas como risco 10.',
      topKeyword
        ? `O assunto com maior presença foi “${topKeyword.label}”, com ${topKeyword.value} menções.`
        : 'Não houve um assunto dominante no período analisado.',
      topSource
        ? `${topSource.label} concentrou a maior cobertura, com ${topSource.value} notícias relevantes.`
        : 'A cobertura ficou distribuída sem um veículo dominante.'
    ];
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(8.3);
    doc.setTextColor(56, 64, 85);
    for (const insight of insights) {
      doc.setFillColor(124, 92, 255);
      doc.circle(margin + 1.3, y - 1, 0.8, 'F');
      const lines = doc.splitTextToSize(insight, contentWidth - 7).slice(0, 2);
      doc.text(lines, margin + 5, y);
      y += Math.max(5, lines.length * 4);
    }

    const notes = context.notes?.trim();
    if (notes) {
      y += 2;
      this.sectionTitle(doc, 'Nota do analista', margin, y);
      y += 6;
      doc.setFillColor(249, 247, 255);
      doc.setDrawColor(226, 220, 249);
      const noteLines = doc.splitTextToSize(notes.replace(/\s+/g, ' ').slice(0, 700), contentWidth - 8).slice(0, 5);
      const noteHeight = Math.max(15, noteLines.length * 4 + 6);
      doc.roundedRect(margin, y - 3, contentWidth, noteHeight, 2, 2, 'FD');
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(7.7);
      doc.setTextColor(69, 60, 101);
      doc.text(noteLines, margin + 4, y + 2);
      y += noteHeight + 4;
    }

    const rankingY = Math.max(y + 3, 156);
    const rankingGap = 5;
    const rankingWidth = (contentWidth - rankingGap * 2) / 3;
    this.ranking(doc, 'Risco', data.byRisk.slice(0, 5), margin, rankingY, rankingWidth);
    this.ranking(doc, 'Principais veículos', data.bySource.slice(0, 5), margin + rankingWidth + rankingGap, rankingY, rankingWidth);
    this.ranking(doc, 'Palavras-chave', data.byKeyword.slice(0, 5), margin + (rankingWidth + rankingGap) * 2, rankingY, rankingWidth);

    const priority = [...data.articles]
      .sort((a, b) => b.risk - a.risk || b.impact - a.impact || Date.parse(b.publishedAt) - Date.parse(a.publishedAt))
      .slice(0, 12);

    if (priority.length) {
      doc.addPage();
      this.header(doc, 'Notícias prioritárias', `${priority.length} destaques para leitura`, data.generatedAt);
      const tableOptions: UserOptions = {
        startY: 44,
        head: [['Publicação', 'Notícia', 'Veículo', 'Risco', 'Impacto']],
        body: priority.map(article => [
          this.shortDate(article.publishedAt),
          this.ellipsis(article.title, 125),
          this.ellipsis(article.source, 38),
          article.risk,
          article.impact.toFixed(1)
        ]),
        margin: { left: margin, right: margin, bottom: 18 },
        theme: 'grid',
        pageBreak: 'avoid',
        rowPageBreak: 'avoid',
        styles: { font: 'helvetica', fontSize: 7, cellPadding: 2, overflow: 'linebreak', valign: 'middle', minCellHeight: 9 },
        headStyles: { fillColor: [45, 35, 92], textColor: 255, fontStyle: 'bold' },
        alternateRowStyles: { fillColor: [248, 249, 252] },
        columnStyles: {
          0: { cellWidth: 25 },
          1: { cellWidth: 88 },
          2: { cellWidth: 42 },
          3: { cellWidth: 13, halign: 'center' },
          4: { cellWidth: 15, halign: 'right' }
        },
        didDrawCell: hook => {
          if (hook.section !== 'body' || hook.column.index !== 1) return;
          const article = priority[hook.row.index];
          if (article?.url) doc.link(hook.cell.x, hook.cell.y, hook.cell.width, hook.cell.height, { url: article.url });
        }
      };
      autoTable(doc, tableOptions);
      const finalY = ((doc as unknown as { lastAutoTable?: { finalY: number } }).lastAutoTable?.finalY ?? 44) + 7;
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(7.5);
      doc.setTextColor(91, 99, 121);
      doc.text('Clique no título de uma notícia para abrir a publicação original.', margin, Math.min(finalY, 276));
      if (context.dashboardUrl) {
        doc.setTextColor(92, 70, 190);
        doc.textWithLink('Abrir todas as notícias no Mídia Radar', pageWidth - margin, Math.min(finalY, 276), {
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

  private header(doc: JsPDF, title: string, subtitle: string, generatedAt: string): void {
    const width = doc.internal.pageSize.getWidth();
    doc.setFillColor(17, 25, 54);
    doc.rect(0, 0, width, 38, 'F');
    doc.setTextColor(255);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(18);
    doc.text(title, 14, 16);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(8);
    doc.text(subtitle, 14, 24);
    doc.setTextColor(177, 185, 207);
    doc.text(`Atualizado em ${this.date(generatedAt)}`, 14, 31);
    doc.setTextColor(169, 153, 255);
    doc.setFont('helvetica', 'bold');
    doc.text('MÍDIA RADAR • MCS', width - 14, 18, { align: 'right' });
  }

  private sectionTitle(doc: JsPDF, text: string, x: number, y: number): void {
    doc.setTextColor(45, 35, 92);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(11);
    doc.text(text, x, y);
  }

  private ranking(doc: JsPDF, title: string, items: ReportPoint[], x: number, y: number, width: number): void {
    doc.setFillColor(246, 247, 251);
    doc.setDrawColor(224, 227, 237);
    doc.roundedRect(x, y, width, 75, 2, 2, 'FD');
    doc.setTextColor(45, 35, 92);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(8.2);
    doc.text(title, x + 4, y + 7);
    const max = Math.max(...items.map(item => item.value), 1);
    items.forEach((item, index) => {
      const rowY = y + 16 + index * 11;
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(6.7);
      doc.setTextColor(63, 71, 92);
      doc.text(this.ellipsis(item.label.replaceAll('_', ' '), 26), x + 4, rowY);
      doc.setFont('helvetica', 'bold');
      doc.text(String(item.value), x + width - 4, rowY, { align: 'right' });
      doc.setFillColor(226, 228, 237);
      doc.roundedRect(x + 4, rowY + 2, width - 8, 2, 1, 1, 'F');
      doc.setFillColor(124, 92, 255);
      doc.roundedRect(x + 4, rowY + 2, Math.max(1, (width - 8) * item.value / max), 2, 1, 1, 'F');
    });
    if (!items.length) {
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(7);
      doc.setTextColor(120);
      doc.text('Sem dados no período.', x + 4, y + 18);
    }
  }

  private footer(doc: JsPDF, page: number, total: number): void {
    const width = doc.internal.pageSize.getWidth();
    const height = doc.internal.pageSize.getHeight();
    doc.setDrawColor(224, 227, 237);
    doc.line(14, height - 11, width - 14, height - 11);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7);
    doc.setTextColor(130);
    doc.text('Mídia Radar • Resumo executivo', 14, height - 6);
    doc.text(`${page}/${total}`, width - 14, height - 6, { align: 'right' });
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
}
