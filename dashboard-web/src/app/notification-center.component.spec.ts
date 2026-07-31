import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { NotificationCenterComponent } from './notification-center.component';

describe('NotificationCenterComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [NotificationCenterComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()]
    }).compileComponents();
  });

  it('exibe contador, abre o histórico e marca uma notícia individualmente', () => {
    const fixture = TestBed.createComponent(NotificationCenterComponent);
    fixture.detectChanges();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/dashboard-api/alerts/unread-count').flush({ unreadCount: 3 });
    fixture.detectChanges();

    const bell = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.alert-bell')!;
    expect(bell.getAttribute('aria-label')).toContain('3 alertas não lidos');
    expect((fixture.nativeElement as HTMLElement).querySelector('.alert-badge')?.textContent).toContain('3');

    bell.click();
    http.expectOne(request =>
      request.url === '/dashboard-api/alerts' && request.params.get('limit') === '20'
    ).flush({
      unreadCount: 3,
      nextCursor: null,
      items: [{
        id: 81,
        title: 'MCS anuncia novo projeto cultural',
        url: 'https://example.com/noticia-mcs',
        source: 'Portal de teste',
        publishedAt: new Date().toISOString(),
        detectedAt: new Date().toISOString(),
        matchedTerms: ['MCS'],
        excerpt: 'O MCS anunciou um novo projeto.',
        risk: 5,
        impact: 7,
        read: false
      }]
    });
    fixture.detectChanges();

    const item = (fixture.nativeElement as HTMLElement).querySelector<HTMLAnchorElement>('.alert-item')!;
    expect(item.href).toBe('https://example.com/noticia-mcs');
    expect(item.getAttribute('role')).toBeNull();
    expect(item.closest('li')).not.toBeNull();
    expect(item.textContent).toContain('MCS anuncia novo projeto cultural');
    item.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    http.expectOne('/dashboard-api/alerts/81/read').flush({ unreadCount: 2 });
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).querySelector('.alert-badge')?.textContent).toContain('2');
    expect((fixture.nativeElement as HTMLElement).querySelector('.alert-item')?.classList.contains('unread')).toBe(false);
    fixture.destroy();
    http.verify();
  });

  it('marca todo o histórico como lido', () => {
    const fixture = TestBed.createComponent(NotificationCenterComponent);
    fixture.detectChanges();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/dashboard-api/alerts/unread-count').flush({ unreadCount: 12 });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('.alert-badge')?.textContent).toContain('9+');

    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.alert-bell')!.click();
    http.expectOne(request => request.url === '/dashboard-api/alerts').flush({
      unreadCount: 12,
      items: [],
      nextCursor: null
    });
    fixture.detectChanges();

    const markAll = [...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('.alert-toolbar button')]
      .find(button => button.textContent?.includes('Marcar todas'))!;
    markAll.click();
    http.expectOne('/dashboard-api/alerts/read-all').flush({ unreadCount: 0 });
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).querySelector('.alert-badge')).toBeNull();
    fixture.destroy();
    http.verify();
  });

  it('carrega páginas anteriores usando o cursor retornado pela API', () => {
    const fixture = TestBed.createComponent(NotificationCenterComponent);
    fixture.detectChanges();
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/dashboard-api/alerts/unread-count').flush({ unreadCount: 0 });

    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.alert-bell')!.click();
    http.expectOne(request => request.url === '/dashboard-api/alerts').flush({
      unreadCount: 0,
      nextCursor: 81,
      items: [{
        id: 81,
        title: 'Primeira menção',
        url: 'https://example.com/primeira',
        source: 'Portal A',
        detectedAt: new Date().toISOString(),
        matchedTerms: ['MCS'],
        risk: 0,
        impact: 2,
        read: true
      }]
    });
    fixture.detectChanges();

    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.load-more')!.click();
    http.expectOne(request =>
      request.url === '/dashboard-api/alerts'
      && request.params.get('beforeId') === '81'
      && request.params.get('limit') === '20'
    ).flush({
      unreadCount: 0,
      nextCursor: null,
      items: [{
        id: 40,
        title: 'Menção anterior',
        url: 'https://example.com/anterior',
        source: 'Portal B',
        detectedAt: new Date().toISOString(),
        matchedTerms: ['Movimento Cultural Social'],
        risk: 5,
        impact: 6,
        read: true
      }]
    });
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).querySelectorAll('.alert-item')).toHaveLength(2);
    expect((fixture.nativeElement as HTMLElement).querySelector('.load-more')).toBeNull();
    fixture.destroy();
    http.verify();
  });
});
