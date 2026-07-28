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
interface Filters { sources: string[]; sections: string[]; risks: number[]; keywords: string[]; tones: string[]; municipalities: string[]; }
interface CurrentUser { id: number; username: string; displayName: string; email?: string; admin: boolean; }
interface UserKeyword { id: number; keyword: string; }
interface ManagedUser { id: number; username: string; displayName: string; email?: string; admin: boolean; active: boolean; }

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
  readonly filters = signal<Filters>({ sources: [], sections: [], risks: [0, 5, 10], keywords: [], tones: [], municipalities: [] });
  readonly loading = signal(true);
  readonly error = signal('');
  readonly lastUpdate = computed(() => this.data()?.generatedAt ? this.date(this.data()!.generatedAt) : '—');
  readonly reportOpen = signal(false);
  readonly reportGenerating = signal(false);
  readonly reportError = signal('');
  readonly user = signal<CurrentUser | null>(null);
  readonly authChecking = signal(true);
  readonly loginError = signal('');
  readonly authMode = signal<'login' | 'register' | 'verify' | 'forgot' | 'reset'>('login');
  readonly authMessage = signal('');
  readonly keywordOpen = signal(false);
  readonly userKeywords = signal<UserKeyword[]>([]);
  readonly keywordError = signal('');
  readonly keywordMessage = signal('');
  readonly geographyOpen = signal(false);
  readonly accountsOpen = signal(false);
  readonly managedUsers = signal<ManagedUser[]>([]);
  readonly accountError = signal('');

  days = 7;
  keyword = '';
  source = '';
  risk = '';
  tone = '';
  selectedLocations: string[] = [];
  draftLocations = new Set<string>();
  geographySearch = '';
  search = '';
  loginUsername = '';
  loginPassword = '';
  registerUsername = '';
  registerEmail = '';
  registerPassword = '';
  recoveryEmail = '';
  resetToken = '';
  resetPasswordValue = '';
  verificationCode = '';
  newKeyword = '';
  selectedKeywordIds = new Set<number>();
  reportNotes = '';
  accountUsername = '';
  accountEmail = '';
  accountPassword = '';
  accountAdmin = false;
  reportSections: ReportSections = {
    summary: true,
    distributions: true,
    relevant: true,
    critical: true,
    journalists: true,
    allNews: false
  };

  ngOnInit(): void {
    this.resetToken = new URLSearchParams(window.location.search).get('reset') || '';
    if (this.resetToken) this.authMode.set('reset');
    this.http.get<CurrentUser>('/auth-api/me').subscribe({
      next: user => { this.user.set(user); this.authChecking.set(false); this.initializeDashboard(); },
      error: () => this.authChecking.set(false)
    });
  }

  login(): void {
    this.loginError.set('');
    this.http.post<CurrentUser>('/auth-api/login', { username: this.loginUsername, password: this.loginPassword }).subscribe({
      next: user => {
        this.user.set(user);
        this.loginPassword = '';
        this.initializeDashboard();
      },
      error: () => this.loginError.set('Usuário ou senha inválidos.')
    });
  }

  showAuth(mode: 'login' | 'register' | 'verify' | 'forgot' | 'reset'): void {
    this.loginError.set('');
    this.authMessage.set('');
    this.authMode.set(mode);
  }

  register(): void {
    this.loginError.set('');
    this.http.post('/auth-api/register', {
      username: this.registerUsername,
      email: this.registerEmail, password: this.registerPassword
    }).subscribe({
      next: () => {
        this.loginUsername = this.registerUsername;
        this.registerPassword = '';
        this.showAuth('verify');
        this.authMessage.set('Enviamos um código de 6 dígitos para o seu e-mail.');
      },
      error: error => this.loginError.set(this.authError(error, 'Não foi possível criar a conta.'))
    });
  }

  verifyEmail(): void {
    this.loginError.set('');
    this.http.post('/auth-api/verify-email', { username: this.registerUsername, code: this.verificationCode }).subscribe({
      next: () => {
        this.verificationCode = '';
        this.showAuth('login');
        this.authMessage.set('E-mail confirmado. Agora você pode entrar.');
      },
      error: error => this.loginError.set(this.authError(error, 'Não foi possível confirmar o código.'))
    });
  }

  resendVerification(): void {
    this.loginError.set('');
    this.http.post('/auth-api/resend-verification', { username: this.registerUsername, code: '' }).subscribe({
      next: () => this.authMessage.set('Enviamos um novo código. Ele expira em 15 minutos.'),
      error: error => this.loginError.set(this.authError(error, 'Não foi possível reenviar o código.'))
    });
  }

  requestRecovery(): void {
    this.loginError.set('');
    this.http.post('/auth-api/forgot-password', { email: this.recoveryEmail }).subscribe({
      next: () => this.authMessage.set('Se o e-mail estiver cadastrado, enviaremos um link válido por 30 minutos.'),
      error: error => this.loginError.set(this.authError(error, 'Não foi possível enviar o e-mail de recuperação.'))
    });
  }

  resetPassword(): void {
    this.loginError.set('');
    this.http.post('/auth-api/reset-password', { token: this.resetToken, password: this.resetPasswordValue }).subscribe({
      next: () => {
        window.history.replaceState({}, '', window.location.pathname);
        this.resetPasswordValue = '';
        this.showAuth('login');
        this.authMessage.set('Senha alterada. Entre com sua nova senha.');
      },
      error: error => this.loginError.set(this.authError(error, 'O link é inválido ou expirou.'))
    });
  }

  logout(): void {
    this.http.post('/auth-api/logout', {}).subscribe({
      next: () => { this.user.set(null); this.data.set(null); this.loginPassword = ''; }
    });
  }

  private initializeDashboard(): void {
    this.http.get<Filters>('/dashboard-api/filters').subscribe({ next: value => this.filters.set(value) });
    this.load();
  }

  openKeywords(): void {
    this.keywordError.set('');
    this.keywordMessage.set('');
    this.selectedKeywordIds.clear();
    this.keywordOpen.set(true);
    this.loadKeywords();
  }

  closeKeywords(): void { this.keywordOpen.set(false); }

  openGeography(): void {
    this.geographySearch = '';
    this.draftLocations = new Set(this.selectedLocations);
    this.geographyOpen.set(true);
  }

  closeGeography(): void { this.geographyOpen.set(false); }

  selectBrazil(): void {
    this.draftLocations.clear();
  }

  toggleLocation(value: string, checked: boolean): void {
    if (value === 'estado_rj' && checked) {
      this.draftLocations.clear();
      this.draftLocations.add(value);
      return;
    }
    if (value !== 'estado_rj' && checked) this.draftLocations.delete('estado_rj');
    if (checked) this.draftLocations.add(value); else this.draftLocations.delete(value);
  }

  locationChecked(value: string): boolean { return this.draftLocations.has(value); }

  applyLocations(): void {
    this.selectedLocations = [...this.draftLocations];
    this.geographyOpen.set(false);
    this.load();
  }

  geographyLabel(): string {
    if (!this.selectedLocations.length) return 'Brasil inteiro';
    if (this.selectedLocations.includes('estado_rj')) return 'Todo o Estado do RJ';
    if (this.selectedLocations.length === 1) return this.selectedLocations[0];
    return `${this.selectedLocations.length} municípios`;
  }

  filteredMunicipalities(): string[] {
    const term = this.geographySearch.trim().toLocaleLowerCase('pt-BR');
    return this.filters().municipalities.filter(item => !term || item.toLocaleLowerCase('pt-BR').includes(term));
  }

  addKeyword(): void {
    const text = this.newKeyword.trim();
    this.keywordError.set('');
    this.keywordMessage.set('');
    if (text.length < 2) { this.keywordError.set('Digite ao menos uma palavra-chave válida.'); return; }
    this.http.post<{ received: number; added: number; ignored: number }>('/dashboard-api/keywords/batch', { text }).subscribe({
      next: result => {
        this.newKeyword = '';
        this.keywordMessage.set(`${result.added} adicionada(s). ${result.ignored} repetida(s) ignorada(s).`);
        this.loadKeywords();
        this.initializeDashboard();
      },
      error: error => this.keywordError.set(error.error?.message || 'Não foi possível adicionar as palavras-chave.')
    });
  }

  removeKeyword(item: UserKeyword): void {
    this.http.delete(`/dashboard-api/keywords/${item.id}`).subscribe({
      next: () => { this.loadKeywords(); this.initializeDashboard(); },
      error: () => this.keywordError.set('Não foi possível remover a palavra-chave.')
    });
  }

  toggleKeyword(id: number, checked: boolean): void {
    if (checked) this.selectedKeywordIds.add(id); else this.selectedKeywordIds.delete(id);
  }

  keywordSelected(id: number): boolean { return this.selectedKeywordIds.has(id); }

  toggleAllKeywords(checked: boolean): void {
    this.selectedKeywordIds.clear();
    if (checked) this.userKeywords().forEach(item => this.selectedKeywordIds.add(item.id));
  }

  removeSelectedKeywords(): void {
    const ids = [...this.selectedKeywordIds];
    this.keywordError.set('');
    this.keywordMessage.set('');
    if (!ids.length) { this.keywordError.set('Selecione ao menos uma palavra-chave.'); return; }
    this.http.post<{ removed: number }>('/dashboard-api/keywords/delete-batch', { ids }).subscribe({
      next: result => {
        this.selectedKeywordIds.clear();
        this.keywordMessage.set(`${result.removed} palavra(s)-chave removida(s).`);
        this.loadKeywords();
        this.initializeDashboard();
      },
      error: error => this.keywordError.set(error.error?.message || 'Não foi possível remover as palavras-chave.')
    });
  }

  private loadKeywords(): void {
    this.http.get<UserKeyword[]>('/dashboard-api/keywords').subscribe({
      next: items => this.userKeywords.set(items),
      error: () => this.keywordError.set('Não foi possível carregar suas palavras-chave.')
    });
  }

  openAccounts(): void {
    this.accountError.set('');
    this.accountsOpen.set(true);
    this.loadAccounts();
  }

  closeAccounts(): void { this.accountsOpen.set(false); }

  createAccount(): void {
    this.accountError.set('');
    this.http.post<{ id: number }>('/auth-api/users', {
      username: this.accountUsername,
      email: this.accountEmail,
      password: this.accountPassword,
      admin: this.accountAdmin
    }).subscribe({
      next: () => {
        this.accountUsername = '';
        this.accountEmail = '';
        this.accountPassword = '';
        this.accountAdmin = false;
        this.loadAccounts();
      },
      error: error => this.accountError.set(this.authError(error, 'Não foi possível criar a conta.'))
    });
  }

  private loadAccounts(): void {
    this.http.get<ManagedUser[]>('/auth-api/users').subscribe({
      next: users => this.managedUsers.set(users),
      error: () => this.accountError.set('Não foi possível carregar as contas.')
    });
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
            filters: this.activeFilterLabels(),
            notes: this.reportNotes
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

  clear(): void { this.days = 7; this.keyword = ''; this.source = ''; this.risk = ''; this.tone = ''; this.selectedLocations = []; this.search = ''; this.load(); }
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
    this.selectedLocations.forEach(location => params = params.append('location', location));
    return params;
  }

  private activeFilterLabels(): string[] {
    const labels: string[] = [];
    if (this.keyword) labels.push(`Palavra-chave: ${this.keyword}`);
    if (this.source) labels.push(`Veículo: ${this.source}`);
    if (this.risk !== '') labels.push(`Risco: ${this.risk}`);
    if (this.tone) labels.push(`Tom: ${this.toneLabel(this.tone)}`);
    if (this.selectedLocations.includes('estado_rj')) labels.push('Abrangência: Todo o Estado do Rio de Janeiro');
    else if (this.selectedLocations.length) labels.push(`Municípios: ${this.selectedLocations.join(', ')}`);
    return labels;
  }

  private authError(error: any, fallback: string): string {
    return error?.error?.detail || error?.error?.message || error?.error?.error || fallback;
  }
}
