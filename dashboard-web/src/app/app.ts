import { CommonModule } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ReportOverview, ReportPdfService, ReportSections } from './report-pdf.service';

interface Point { label: string; value: number; }
interface Article {
  id: number; title: string; url: string; source: string; section: string;
  journalist?: string; publishedAt: string; risk: number; tone: string;
  impact: number; keywords: string[]; evidence: string[];
}
interface Overview {
  periodDays: number; generatedAt: string;
  kpis: { articles: number; sources: number; risk10: number; risk5: number; averageImpact: number; instagram: number; };
  byRisk: Point[]; byTone: Point[]; bySource: Point[]; bySection: Point[];
  byKeyword: Point[]; timeline: Point[]; articles: Article[];
}
interface Filters { sources: string[]; sections: string[]; risks: number[]; keywords: string[]; tones: string[]; }

@Component({
  selector: 'app-root',
  imports: [CommonModule, FormsModule],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly reportPdf = inject(ReportPdfService);
  readonly data = signal<Overview | null>(null);
  readonly filters = signal<Filters>({ sources: [], sections: [], risks: [0, 5, 10], keywords: [], tones: [] });
  readonly loading = signal(true);
  readonly error = signal('');
  readonly lastUpdate = computed(() => this.data()?.generatedAt ? this.date(this.data()!.generatedAt) : '—');
  readonly reportOpen = signal(false);
  readonly reportGenerating = signal(false);
  readonly reportError = signal('');

  days = 7;
  keyword = '';
  source = '';
  risk = '';
  tone = '';
  search = '';
  reportSections: ReportSections = {
    summary: true,
    distributions: true,
    relevant: true,
    critical: true,
    journalists: true,
    allNews: false
  };

  ngOnInit(): void {
    this.http.get<Filters>('/dashboard-api/filters').subscribe({ next: value => this.filters.set(value) });
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set('');
    const params = this.params();
    this.http.get<Overview>('/dashboard-api/overview', { params }).subscribe({
      next: value => { this.data.set(value); this.loading.set(false); },
      error: () => { this.error.set('Não foi possível carregar os dados. Tente novamente.'); this.loading.set(false); }
    });
  }

  openReport(): void {
    this.reportError.set('');
    this.reportOpen.set(true);
  }

  closeReport(): void {
    if (!this.reportGenerating()) this.reportOpen.set(false);
  }

  selectedReportSections(): number {
    return Object.values(this.reportSections).filter(Boolean).length;
  }

  generateReport(): void {
    if (!this.selectedReportSections()) {
      this.reportError.set('Selecione pelo menos uma seção para o relatório.');
      return;
    }
    this.reportGenerating.set(true);
    this.reportError.set('');
    const params = this.params().set('includeAll', true);
    this.http.get<ReportOverview>('/dashboard-api/overview', { params }).subscribe({
      next: async value => {
        try {
          await this.reportPdf.generate(value, this.reportSections, {
            periodLabel: `Últimos ${this.days} dias`,
            filters: this.activeFilterLabels()
          });
          this.reportOpen.set(false);
        } catch {
          this.reportError.set('Não foi possível montar o PDF. Tente novamente.');
        } finally {
          this.reportGenerating.set(false);
        }
      },
      error: () => {
        this.reportError.set('Não foi possível carregar os dados completos do relatório.');
        this.reportGenerating.set(false);
      }
    });
  }

  clear(): void { this.days = 7; this.keyword = ''; this.source = ''; this.risk = ''; this.tone = ''; this.search = ''; this.load(); }
  max(points: Point[] | undefined): number { return Math.max(...(points ?? []).map(item => item.value), 1); }
  width(point: Point, points: Point[] | undefined): number { return Math.max(3, point.value / this.max(points) * 100); }
  riskClass(risk: number): string { return risk === 10 ? 'critical' : risk === 5 ? 'attention' : 'neutral'; }
  toneLabel(value: string): string { return value.replaceAll('_', ' '); }
  impactLabel(value: number): string { return value >= 7 ? 'Alto impacto' : value >= 4 ? 'Impacto moderado' : 'Baixo impacto'; }
  impactClass(value: number): string { return value >= 7 ? 'high' : value >= 4 ? 'medium' : 'low'; }
  date(value: string): string { return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)); }
  day(value: string): string { return new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit' }).format(new Date(value + 'T12:00:00')); }
  sourceType(source: string): string { return source.startsWith('Instagram/') ? 'Instagram' : source.includes('.') ? 'Web' : 'RSS'; }
  visibleArticles(): Article[] {
    const term = this.search.trim().toLocaleLowerCase('pt-BR');
    if (!term) return this.data()?.articles ?? [];
    return (this.data()?.articles ?? []).filter(a => [a.title, a.source, a.journalist, ...a.keywords].some(value => value?.toLocaleLowerCase('pt-BR').includes(term)));
  }

  private params(): HttpParams {
    let params = new HttpParams().set('days', this.days);
    if (this.keyword) params = params.set('keyword', this.keyword);
    if (this.source) params = params.set('source', this.source);
    if (this.risk !== '') params = params.set('risk', this.risk);
    if (this.tone) params = params.set('tone', this.tone);
    return params;
  }

  private activeFilterLabels(): string[] {
    const labels: string[] = [];
    if (this.keyword) labels.push(`Palavra-chave: ${this.keyword}`);
    if (this.source) labels.push(`Veículo: ${this.source}`);
    if (this.risk !== '') labels.push(`Risco: ${this.risk}`);
    if (this.tone) labels.push(`Tom: ${this.toneLabel(this.tone)}`);
    return labels;
  }
}
