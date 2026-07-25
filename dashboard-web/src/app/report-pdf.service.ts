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
export interface ReportSections {
  summary: boolean;
  distributions: boolean;
  relevant: boolean;
  critical: boolean;
  journalists: boolean;
  allNews: boolean;
}
export interface ReportContext {
  periodLabel: string;
  filters: string[];
}

@Injectable({ providedIn: 'root' })
export class ReportPdfService {
  async generate(data: ReportOverview, sections: ReportSections, context: ReportContext): Promise<void> {
    const [{ jsPDF }, { autoTable }] = await Promise.all([import('jspdf'), import('jspdf-autotable')]);
    const doc = new jsPDF({ unit: 'mm', format: 'a4' });
    const pageWidth = doc.internal.pageSize.getWidth();
    const margin = 14;
    let y = 18;

    const addPageIfNeeded = (height = 24) => {
      if (y + height > 280) {
        doc.addPage();
        y = 18;
      }
    };
    const title = (text: string) => {
      addPageIfNeeded(18);
      doc.setTextColor(45, 35, 92);
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(14);
      doc.text(text, margin, y);
      y += 7;
    };
    const table = (head: string[], body: (string | number)[][], widths?: Record<number, { cellWidth: number }>) => {
      addPageIfNeeded();
      autoTable(doc, {
        startY: y,
        head: [head],
        body,
        margin: { left: margin, right: margin },
        theme: 'striped',
        styles: { font: 'helvetica', fontSize: 7.5, cellPadding: 2, overflow: 'linebreak' },
        headStyles: { fillColor: [45, 35, 92], textColor: 255 },
        columnStyles: widths,
        didDrawPage: () => this.footer(doc)
      });
      y = ((doc as unknown as { lastAutoTable: { finalY: number } }).lastAutoTable?.finalY ?? y) + 8;
    };

    doc.setFillColor(17, 25, 54);
    doc.rect(0, 0, pageWidth, 42, 'F');
    doc.setTextColor(255);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(20);
    doc.text('Relatório de Impacto Midiático', margin, 18);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    doc.text(`Período: ${context.periodLabel}`, margin, 26);
    doc.text(`Gerado em: ${this.date(data.generatedAt)}`, margin, 32);
    y = 50;

    doc.setTextColor(75, 82, 105);
    doc.setFontSize(8);
    const filterText = context.filters.length ? `Filtros aplicados: ${context.filters.join(' • ')}` : 'Filtros aplicados: nenhum';
    const filterLines = doc.splitTextToSize(filterText, pageWidth - margin * 2);
    doc.text(filterLines, margin, y);
    y += filterLines.length * 4 + 5;

    if (sections.summary) {
      title('Resumo executivo');
      table(
        ['Indicador', 'Resultado'],
        [
          ['Notícias coletadas', data.kpis.articles],
          ['Veículos distintos', data.kpis.sources],
          ['Alertas críticos (risco 10)', data.kpis.risk10],
          ['Alertas de atenção (risco 5)', data.kpis.risk5],
          ['Impacto médio', data.kpis.averageImpact.toFixed(2)]
        ],
        { 0: { cellWidth: 120 } }
      );
    }

    if (sections.distributions) {
      title('Distribuições e cobertura');
      table(['Risco', 'Quantidade'], data.byRisk.map(item => [item.label, item.value]));
      title('Principais veículos');
      table(['Veículo', 'Notícias'], data.bySource.map(item => [item.label, item.value]));
      title('Editorias');
      table(['Editoria', 'Notícias'], data.bySection.map(item => [item.label, item.value]));
      title('Palavras-chave');
      table(['Termo', 'Menções'], data.byKeyword.map(item => [item.label, item.value]));
    }

    if (sections.relevant) {
      const relevant = data.articles.filter(article => article.impact >= 4 || article.risk > 0);
      title(`Notícias relevantes (${relevant.length})`);
      this.articleTable(doc, autoTable, relevant, y, margin);
      y = this.finalY(doc, y);
    }

    if (sections.critical) {
      const critical = data.articles.filter(article => article.risk === 10);
      title(`Notícias de risco crítico (${critical.length})`);
      this.articleTable(doc, autoTable, critical, y, margin);
      y = this.finalY(doc, y);
    }

    if (sections.journalists) {
      title('Análise por jornalista responsável');
      const grouped = new Map<string, { total: number; critical: number; impact: number }>();
      for (const article of data.articles) {
        const journalist = article.journalist?.trim() || 'Autor não identificado';
        const item = grouped.get(journalist) ?? { total: 0, critical: 0, impact: 0 };
        item.total++;
        item.critical += article.risk === 10 ? 1 : 0;
        item.impact += article.impact;
        grouped.set(journalist, item);
      }
      const rows = [...grouped.entries()]
        .sort((a, b) => b[1].total - a[1].total)
        .map(([name, item]) => [name, item.total, item.critical, (item.impact / item.total).toFixed(2)]);
      table(['Jornalista', 'Notícias', 'Críticas', 'Impacto médio'], rows, { 0: { cellWidth: 95 } });
    }

    if (sections.allNews) {
      title(`Relação completa de notícias (${data.articles.length})`);
      this.articleTable(doc, autoTable, data.articles, y, margin);
    }

    const totalPages = doc.getNumberOfPages();
    for (let page = 1; page <= totalPages; page++) {
      doc.setPage(page);
      this.footer(doc, page, totalPages);
    }
    const stamp = new Date().toISOString().slice(0, 10);
    doc.save(`relatorio-impacto-midiatico-${stamp}.pdf`);
  }

  private articleTable(
    doc: JsPDF,
    autoTable: (doc: JsPDF, options: UserOptions) => void,
    articles: ReportArticle[],
    startY: number,
    margin: number
  ): void {
    autoTable(doc, {
      startY,
      head: [['Publicação', 'Notícia', 'Veículo / jornalista', 'Risco', 'Impacto']],
      body: articles.map(article => [
        this.date(article.publishedAt),
        `${article.title}\nTermos: ${article.keywords.join(', ') || '—'}`,
        `${article.source}\n${article.journalist?.trim() || 'Autor não identificado'}`,
        article.risk,
        article.impact.toFixed(1)
      ]),
      margin: { left: margin, right: margin },
      theme: 'grid',
      styles: { font: 'helvetica', fontSize: 6.8, cellPadding: 1.7, overflow: 'linebreak', valign: 'top' },
      headStyles: { fillColor: [45, 35, 92], textColor: 255 },
      columnStyles: {
        0: { cellWidth: 22 },
        1: { cellWidth: 75 },
        2: { cellWidth: 52 },
        3: { cellWidth: 13, halign: 'center' },
        4: { cellWidth: 15, halign: 'right' }
      },
      didDrawPage: () => this.footer(doc)
    });
  }

  private finalY(doc: JsPDF, fallback: number): number {
    return ((doc as unknown as { lastAutoTable: { finalY: number } }).lastAutoTable?.finalY ?? fallback) + 8;
  }

  private footer(doc: JsPDF, page?: number, total?: number): void {
    const width = doc.internal.pageSize.getWidth();
    const height = doc.internal.pageSize.getHeight();
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7);
    doc.setTextColor(130);
    doc.text('Mídia Radar • Inteligência reputacional', 14, height - 7);
    if (page && total) doc.text(`${page}/${total}`, width - 14, height - 7, { align: 'right' });
  }

  private date(value: string): string {
    return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value));
  }
}
