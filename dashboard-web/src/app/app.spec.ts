import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { App } from './app';
import { ReportPdfService } from './report-pdf.service';

describe('App', () => {
  beforeEach(async () => {
    window.history.replaceState({}, '', '/');
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
    http.expectOne('/dashboard-api/alerts/unread-count').flush({ unreadCount: 2 });
    fixture.detectChanges();
    expect(fixture.componentInstance).toBeTruthy();
    expect((fixture.nativeElement as HTMLElement).querySelector('h1')?.textContent).toContain('Panorama de impacto midiático');
    expect((fixture.nativeElement as HTMLElement).querySelector('.alert-badge')?.textContent).toContain('2');
    const periodOptions = [...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLOptionElement>('.period-select option')]
      .map(option => option.textContent?.trim());
    expect(periodOptions).toEqual(['24 horas', '48 horas', '7 dias', '30 dias']);
    fixture.componentInstance.days = 1;
    expect(fixture.componentInstance.periodLabel()).toBe('Últimas 24 horas');
    fixture.componentInstance.days = 2;
    expect(fixture.componentInstance.periodLabel()).toBe('Últimas 48 horas');
    fixture.componentInstance.days = 7;
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
    expect((fixture.nativeElement as HTMLElement).querySelector('.schedule-email')).toBeNull();
    expect((fixture.nativeElement as HTMLElement).querySelector('input[name="scheduleDate"]')).toBeTruthy();

    const adminLink = (fixture.nativeElement as HTMLElement).querySelector<HTMLAnchorElement>('.sidebar a[href="/admin"]');
    adminLink?.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    http.expectOne('/auth-api/users').flush([{
      id: 1, username: 'equipe', displayName: 'Administrador MCS', email: 'equipe@example.com',
      emailVerified: true, admin: true, active: true, createdAt: new Date().toISOString(), ownerCandidate: false
    }]);
    fixture.detectChanges();
    expect(fixture.componentInstance.page()).toBe('admin');
    expect((fixture.nativeElement as HTMLElement).querySelector('.admin-intro')?.textContent).toContain('Gestão de contas');
    http.verify();
  });

  it('redireciona uma conta comum que tenta abrir /admin diretamente', () => {
    window.history.replaceState({}, '', '/admin');
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/auth-api/me').flush({
      id: 2, username: 'usuario', displayName: 'usuario', email: 'usuario@example.com', admin: false
    });
    http.expectOne('/dashboard-api/filters').flush({
      sources: [], sections: [], risks: [0, 5, 10], keywords: [], tones: [], municipalities: []
    });
    http.expectOne(request => request.url === '/dashboard-api/overview').flush({
      periodDays: 7, generatedAt: new Date().toISOString(),
      kpis: { articles: 0, sources: 0, risk10: 0, risk5: 0, averageImpact: 0, instagram: 0 },
      byRisk: [], byTone: [], bySource: [], bySection: [], byKeyword: [], timeline: [], articles: []
    });
    fixture.detectChanges();
    http.expectOne('/dashboard-api/alerts/unread-count').flush({ unreadCount: 0 });
    fixture.detectChanges();
    expect(fixture.componentInstance.page()).toBe('overview');
    expect(window.location.pathname).toBe('/');
    expect((fixture.nativeElement as HTMLElement).querySelector('.admin-intro')).toBeNull();
    http.expectNone('/auth-api/users');
    http.verify();
  });

  it('pagina notícias sem alterar os totais do recorte', () => {
    window.history.replaceState({}, '', '/noticias');
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/auth-api/me').flush({
      id: 1, username: 'equipe', displayName: 'Administrador MCS', email: 'equipe@example.com', admin: true
    });
    http.expectOne('/dashboard-api/filters').flush({
      sources: [], sections: [], risks: [0, 5, 10], keywords: [], tones: [], municipalities: []
    });
    const first = http.expectOne(request => request.url === '/dashboard-api/overview');
    expect(first.request.params.get('page')).toBe('1');
    expect(first.request.params.get('pageSize')).toBe('50');
    first.flush({
      periodDays: 7, generatedAt: new Date().toISOString(),
      kpis: { articles: 120, sources: 2, risk10: 10, risk5: 20, averageImpact: 3, instagram: 0 },
      byRisk: [], byTone: [], bySource: [], bySection: [], byKeyword: [], timeline: [], articles: [],
      pagination: { page: 1, pageSize: 50, totalItems: 120, totalPages: 3 }
    });
    fixture.detectChanges();
    http.expectOne('/dashboard-api/alerts/unread-count').flush({ unreadCount: 0 });
    fixture.detectChanges();
    expect(fixture.componentInstance.articleTotal()).toBe(120);

    fixture.componentInstance.goToArticlePage(2);
    const second = http.expectOne(request => request.url === '/dashboard-api/overview');
    expect(second.request.params.get('page')).toBe('2');
    second.flush({
      periodDays: 7, generatedAt: new Date().toISOString(),
      kpis: { articles: 120, sources: 2, risk10: 10, risk5: 20, averageImpact: 3, instagram: 0 },
      byRisk: [], byTone: [], bySource: [], bySection: [], byKeyword: [], timeline: [], articles: [],
      pagination: { page: 2, pageSize: 50, totalItems: 120, totalPages: 3 }
    });
    expect(fixture.componentInstance.articlePage()).toBe(2);
    fixture.destroy();
    http.verify();
  });

  it('abre /admin sem depender do carregamento dos indicadores', () => {
    window.history.replaceState({}, '', '/admin');
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/auth-api/me').flush({
      id: 1, username: 'equipe', displayName: 'Administrador MCS', email: 'equipe@example.com', admin: true
    });
    http.expectOne('/auth-api/users').flush([{
      id: 1, username: 'equipe', displayName: 'Administrador MCS', email: 'equipe@example.com',
      emailVerified: true, admin: true, active: true, createdAt: new Date().toISOString(), ownerCandidate: false
    }]);
    fixture.detectChanges();
    http.expectOne('/dashboard-api/alerts/unread-count').flush({ unreadCount: 1 });
    fixture.detectChanges();
    expect(fixture.componentInstance.page()).toBe('admin');
    expect((fixture.nativeElement as HTMLElement).querySelector('.admin-directory')).toBeTruthy();
    http.expectNone('/dashboard-api/overview');
    http.verify();
  });

  it('envia várias opções de cada filtro no mesmo recorte compartilhado', async () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/auth-api/me').flush({
      id: 1, username: 'lucas', displayName: 'Lucas', email: 'lucas@example.com', admin: true, owner: true
    });
    http.expectOne('/dashboard-api/filters').flush({
      sources: ['G1', 'O Globo'], sections: ['integridade_corrupcao'], risks: [0, 5, 10],
      keywords: ['corrupção', 'emendas parlamentares'], tones: ['negativo'], municipalities: []
    });
    http.expectOne(request => request.url === '/dashboard-api/overview').flush({
      periodDays: 7, generatedAt: new Date().toISOString(),
      kpis: { articles: 0, sources: 0, risk10: 0, risk5: 0, averageImpact: 0, instagram: 0 },
      byRisk: [], byTone: [], bySource: [], bySection: [], byKeyword: [], timeline: [], articles: []
    });
    fixture.detectChanges();
    http.expectOne('/dashboard-api/alerts/unread-count').flush({ unreadCount: 0 });

    fixture.componentInstance.toggleTextFilter('keyword', 'corrupção', true);
    fixture.componentInstance.toggleTextFilter('keyword', 'emendas parlamentares', true);
    fixture.componentInstance.toggleTextFilter('source', 'G1', true);
    fixture.componentInstance.toggleTextFilter('source', 'O Globo', true);
    fixture.componentInstance.toggleTextFilter('section', 'integridade_corrupcao', true);
    fixture.componentInstance.toggleRiskFilter(5, true);
    fixture.componentInstance.toggleRiskFilter(10, true);
    fixture.componentInstance.toggleTextFilter('tone', 'negativo', true);
    fixture.componentInstance.search = 'Instituto Carioca';
    fixture.componentInstance.onSharedSearchChange();
    await new Promise(resolve => window.setTimeout(resolve, 220));

    const request = http.expectOne(item => item.url === '/dashboard-api/overview');
    expect(request.request.params.getAll('keyword')).toEqual(['corrupção', 'emendas parlamentares']);
    expect(request.request.params.getAll('source')).toEqual(['G1', 'O Globo']);
    expect(request.request.params.getAll('section')).toEqual(['integridade_corrupcao']);
    expect(request.request.params.getAll('risk')).toEqual(['5', '10']);
    expect(request.request.params.getAll('tone')).toEqual(['negativo']);
    expect(request.request.params.get('query')).toBe('Instituto Carioca');
    request.flush({
      periodDays: 7, generatedAt: new Date().toISOString(),
      kpis: { articles: 0, sources: 0, risk10: 0, risk5: 0, averageImpact: 0, instagram: 0 },
      byRisk: [], byTone: [], bySource: [], bySection: [], byKeyword: [], timeline: [], articles: []
    });
    fixture.destroy();
    http.verify();
  });

  it('exibe o destino alternativo somente para uma conta autorizada', () => {
    window.history.replaceState({}, '', '/envios');
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/auth-api/me').flush({
      id: 2, username: 'autorizado', displayName: 'Autorizado', email: 'conta@example.com',
      admin: false, externalEmailAllowed: true, whatsappAllowed: true, owner: false
    });
    http.expectOne('/dashboard-api/filters').flush({
      sources: [], sections: [], risks: [0, 5, 10], keywords: ['corrupção'], tones: [], municipalities: []
    });
    http.expectOne('/dashboard-api/keywords').flush([{ id: 1, keyword: 'corrupção' }]);
    http.expectOne('/dashboard-api/email-schedules').flush([]);
    http.expectOne(request => request.url === '/dashboard-api/overview').flush({
      periodDays: 7, generatedAt: new Date().toISOString(),
      kpis: { articles: 0, sources: 0, risk10: 0, risk5: 0, averageImpact: 0, instagram: 0 },
      byRisk: [], byTone: [], bySource: [], bySection: [], byKeyword: [], timeline: [], articles: []
    });
    fixture.detectChanges();
    http.expectOne('/dashboard-api/alerts/unread-count').flush({ unreadCount: 0 });
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).querySelector('.schedule-email')).toBeTruthy();
    expect((fixture.nativeElement as HTMLElement).querySelector('.whatsapp-panel')).toBeTruthy();
    expect((fixture.nativeElement as HTMLElement).querySelector('.context-filters')).toBeNull();

    fixture.componentInstance.scheduleDate = '2099-12-31';
    fixture.componentInstance.scheduleTime = '12:00';
    fixture.componentInstance.scheduleRecipientEmail = 'destino@example.com';
    fixture.componentInstance.toggleScheduleKeyword('corrupção', true);
    fixture.componentInstance.createSchedule();
    const request = http.expectOne('/dashboard-api/email-schedules');
    expect(request.request.body.recipientEmail).toBe('destino@example.com');
    request.flush({ id: 44 });
    http.expectOne('/dashboard-api/email-schedules').flush([]);

    fixture.destroy();
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

  it('compartilha o arquivo PDF sem substituir o anexo por uma mensagem', async () => {
    const fixture = TestBed.createComponent(App);
    const component = fixture.componentInstance;
    const file = new File(['pdf'], 'panorama-midiatico.pdf', { type: 'application/pdf' });
    const share = vi.fn().mockResolvedValue(undefined);
    const originalShare = Object.getOwnPropertyDescriptor(navigator, 'share');
    const originalCanShare = Object.getOwnPropertyDescriptor(navigator, 'canShare');
    Object.defineProperty(navigator, 'share', { configurable: true, value: share });
    Object.defineProperty(navigator, 'canShare', { configurable: true, value: () => true });
    (component as unknown as { whatsappReportFile: File }).whatsappReportFile = file;

    try {
      await component.shareWhatsappReport();
      expect(share).toHaveBeenCalledWith({
        files: [file],
        title: 'Panorama de impacto midiático'
      });
      expect(share.mock.calls[0][0]).not.toHaveProperty('text');
    } finally {
      if (originalShare) Object.defineProperty(navigator, 'share', originalShare);
      else Reflect.deleteProperty(navigator, 'share');
      if (originalCanShare) Object.defineProperty(navigator, 'canShare', originalCanShare);
      else Reflect.deleteProperty(navigator, 'canShare');
      fixture.destroy();
    }
  });
});
