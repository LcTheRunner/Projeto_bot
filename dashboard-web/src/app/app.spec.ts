import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { App } from './app';

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
    http.expectOne('/auth-api/me').flush({ id: 1, username: 'equipe', displayName: 'Administrador MCS', admin: true });
    http.expectOne('/dashboard-api/filters').flush({ sources: [], sections: [], risks: [0, 5, 10], keywords: [], tones: [] });
    http.expectOne(request => request.url === '/dashboard-api/overview').flush({
      periodDays: 7, generatedAt: new Date().toISOString(),
      kpis: { articles: 0, sources: 0, risk10: 0, risk5: 0, averageImpact: 0, instagram: 0 },
      byRisk: [], byTone: [], bySource: [], bySection: [], byKeyword: [], timeline: [], articles: []
    });
    fixture.detectChanges();
    expect(fixture.componentInstance).toBeTruthy();
    expect((fixture.nativeElement as HTMLElement).querySelector('h1')?.textContent).toContain('Panorama de impacto midiático');
    const reportButton = [...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('.report-button')]
      .find(button => button.textContent?.includes('PDF'));
    reportButton?.click();
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('#report-title')?.textContent).toContain('Emitir relatório em PDF');
    expect((fixture.nativeElement as HTMLElement).querySelectorAll('.report-options input').length).toBe(6);
    http.verify();
  });
});
