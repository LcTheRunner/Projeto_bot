import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { App } from './app';
import { ReportPdfService } from './report-pdf.service';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting()]
    }).compileComponents();
  });

  it('cria o painel e exibe o título', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/auth-api/me').flush({ id: 1, username: 'equipe', displayName: 'Administrador MCS', email: 'equipe@example.com', admin: true });
    http.expectOne('/dashboard-api/filters').flush({ sources: [], sections: [], risks: [0, 5, 10], keywords: [], tones: [], municipalities: [] });
    http.expectOne(request => request.url === '/dashboard-api/overview').flush({
      periodDays: 7, generatedAt: new Date().toISOString(),
      kpis: { articles: 0, sources: 0, risk10: 0, risk5: 0, averageImpact: 0, instagram: 0 },
      byRisk: [], byTone: [], bySource: [], bySection: [], byKeyword: [], timeline: [], articles: []
    });
    fixture.detectChanges();
    expect(fixture.componentInstance).toBeTruthy();
    expect((fixture.nativeElement as HTMLElement).querySelector('h1')?.textContent).toContain('Panorama de impacto midiático');
    const reportButton = [...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('.utility-button')]
      .find(button => button.textContent?.includes('PDF'));
    reportButton?.click();
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('#report-title')?.textContent).toContain('Emitir relatório em PDF');
    expect((fixture.nativeElement as HTMLElement).querySelectorAll('.report-plan article').length).toBe(2);
    expect((fixture.nativeElement as HTMLElement).querySelector('.report-modal-actions')?.textContent).toContain('Máximo de 2 páginas');

    const newsLink = (fixture.nativeElement as HTMLElement).querySelector<HTMLAnchorElement>('.sidebar a[href="/noticias"]');
    newsLink?.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    fixture.detectChanges();
    expect(fixture.componentInstance.page()).toBe('news');
    expect((fixture.nativeElement as HTMLElement).querySelector('h1')?.textContent).toContain('Notícias monitoradas');
    expect((fixture.nativeElement as HTMLElement).querySelector('.articles')).toBeTruthy();

    const scheduleLink = (fixture.nativeElement as HTMLElement).querySelector<HTMLAnchorElement>('.sidebar a[href="/envios"]');
    scheduleLink?.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    http.expectOne('/dashboard-api/keywords').flush([{ id: 1, keyword: 'corrupção' }]);
    http.expectOne('/dashboard-api/email-schedules').flush([]);
    fixture.detectChanges();
    expect(fixture.componentInstance.page()).toBe('schedules');
    expect((fixture.nativeElement as HTMLElement).querySelector('h1')?.textContent).toContain('Envios programados');
    expect((fixture.nativeElement as HTMLElement).querySelector('.schedule-email')?.textContent).toContain('equipe@example.com');
    expect((fixture.nativeElement as HTMLElement).querySelector('input[name="scheduleDate"]')).toBeTruthy();
    http.verify();
  });

  it('gera um resumo executivo com no máximo duas páginas', async () => {
    const service = TestBed.inject(ReportPdfService);
    const articles = Array.from({ length: 40 }, (_, index) => ({
      id: index + 1,
      title: `Notícia prioritária ${index + 1} com um título longo para validar o limite do relatório executivo`,
      url: `https://example.com/noticia-${index + 1}`,
      source: `Veículo ${index % 8}`,
      section: 'integridade_corrupcao',
      publishedAt: new Date(Date.now() - index * 60_000).toISOString(),
      risk: index % 3 === 0 ? 10 : 5,
      tone: 'negativo',
      impact: 8 - (index % 4),
      keywords: ['corrupção'],
      evidence: []
    }));
    const doc = await service.build({
      periodDays: 7,
      generatedAt: new Date().toISOString(),
      kpis: { articles: 40, sources: 8, risk10: 14, risk5: 26, averageImpact: 6.5, instagram: 0 },
      byRisk: [{ label: 'Risco 10', value: 14 }, { label: 'Risco 5', value: 26 }],
      byTone: [{ label: 'negativo', value: 40 }],
      bySource: Array.from({ length: 8 }, (_, index) => ({ label: `Veículo ${index}`, value: 8 - index })),
      bySection: [{ label: 'integridade_corrupcao', value: 40 }],
      byKeyword: [{ label: 'corrupção', value: 40 }, { label: 'emendas parlamentares', value: 18 }],
      timeline: [],
      articles
    }, {
      periodLabel: 'Últimos 7 dias',
      filters: ['Abrangência: Estado do Rio de Janeiro'],
      notes: 'Priorizar a leitura dos casos críticos e acompanhar os principais veículos.',
      dashboardUrl: 'https://news.venturi.vps-kinghost.net/noticias'
    });
    expect(doc.getNumberOfPages()).toBeLessThanOrEqual(2);
    expect(doc.getNumberOfPages()).toBe(2);
  });
});
