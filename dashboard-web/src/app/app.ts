import { CommonModule } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NotificationCenterComponent } from './notification-center.component';
import { ReportOverview, ReportPdfService } from './report-pdf.service';

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
  pagination?: { page: number; pageSize: number; totalItems: number; totalPages: number; };
}
interface Filters { sources: string[]; sections: string[]; risks: number[]; keywords: string[]; tones: string[]; municipalities: string[]; }
interface CurrentUser {
  id: number; username: string; displayName: string; email?: string; admin: boolean;
  externalEmailAllowed?: boolean; whatsappAllowed?: boolean; owner?: boolean;
}
interface UserKeyword { id: number; keyword: string; }
interface ManagedUser {
  id: number; username: string; displayName: string; email?: string;
  emailVerified: boolean; admin: boolean; active: boolean; createdAt: string;
  ownerCandidate: boolean; externalEmailAllowed: boolean; whatsappAllowed: boolean;
}
interface EmailSchedule {
  id: number; scheduledAt: string; risk: number | null; keywords: string[];
  recipientEmail?: string;
  status: 'PENDING' | 'PREPARING' | 'SENT' | 'FAILED';
  preparedAt?: string; sentAt?: string; lastError?: string;
}
type DashboardPage = 'overview' | 'keywords' | 'sources' | 'news' | 'schedules' | 'admin';
type TextFacet = 'keyword' | 'source' | 'section' | 'tone';

@Component({
  selector: 'app-root',
  imports: [CommonModule, FormsModule, NotificationCenterComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App implements OnInit, OnDestroy {
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
  readonly page = signal<DashboardPage>('overview');
  readonly articlePage = signal(1);
  readonly userKeywords = signal<UserKeyword[]>([]);
  readonly keywordError = signal('');
  readonly keywordMessage = signal('');
  readonly geographyOpen = signal(false);
  readonly selectedKeywords = signal<ReadonlySet<string>>(new Set());
  readonly selectedSources = signal<ReadonlySet<string>>(new Set());
  readonly selectedSections = signal<ReadonlySet<string>>(new Set());
  readonly selectedRisks = signal<ReadonlySet<number>>(new Set());
  readonly selectedTones = signal<ReadonlySet<string>>(new Set());
  readonly managedUsers = signal<ManagedUser[]>([]);
  readonly accountError = signal('');
  readonly accountMessage = signal('');
  readonly emailSchedules = signal<EmailSchedule[]>([]);
  readonly scheduleError = signal('');
  readonly scheduleMessage = signal('');
  readonly whatsappGenerating = signal(false);
  readonly whatsappReady = signal(false);
  readonly whatsappError = signal('');
  readonly whatsappMessage = signal('');
  private readonly popStateHandler = () => this.activatePage(this.pageFromPath(), false);
  private filterReloadTimer?: number;
  private loadSequence = 0;

  days = 7;
  selectedLocations: string[] = [];
  draftLocations = new Set<string>();
  geographySearch = '';
  keywordFilterSearch = '';
  sourceFilterSearch = '';
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
  accountSearch = '';
  scheduleDate = '';
  scheduleTime = '';
  scheduleRisk = '';
  scheduleKeywords = new Set<string>();
  scheduleRecipientEmail = '';
  whatsappRisk = '';
  whatsappKeywords = new Set<string>();
  private whatsappReportFile?: File;

  ngOnInit(): void {
    this.activatePage(this.pageFromPath(), false);
    window.addEventListener('popstate', this.popStateHandler);
    this.resetToken = new URLSearchParams(window.location.search).get('reset') || '';
    if (this.resetToken) this.authMode.set('reset');
    this.http.get<CurrentUser>('/auth-api/me').subscribe({
      next: user => { this.user.set(user); this.authChecking.set(false); this.initializeDashboard(); },
      error: () => this.authChecking.set(false)
    });
  }

  ngOnDestroy(): void {
    window.removeEventListener('popstate', this.popStateHandler);
    if (this.filterReloadTimer !== undefined) window.clearTimeout(this.filterReloadTimer);
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
    if (this.page() === 'admin' && !this.user()?.admin) {
      window.history.replaceState({}, '', '/');
      this.page.set('overview');
      document.title = `${this.pageTitle()} — Central MCS`;
    }
    if (this.page() === 'admin') {
      this.loadAccounts();
      this.loading.set(false);
      return;
    }
    this.loadFilterOptions();
    if (this.page() === 'keywords') this.loadKeywords();
    if (this.page() === 'schedules') { this.loadKeywords(); this.loadSchedules(); this.prepareScheduleForm(); }
    this.load();
  }

  navigate(page: DashboardPage, event?: MouseEvent): void {
    if (event && (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)) return;
    event?.preventDefault();
    const path = this.pagePath(page);
    if (window.location.pathname !== path) window.history.pushState({}, '', path);
    this.activatePage(page, true);
  }

  pagePath(page: DashboardPage): string {
    return {
      overview: '/',
      keywords: '/palavras-chave',
      sources: '/veiculos',
      news: '/noticias',
      schedules: '/envios',
      admin: '/admin'
    }[page];
  }

  pageTitle(): string {
    return {
      overview: 'Panorama de impacto midiático',
      keywords: 'Palavras-chave monitoradas',
      sources: 'Cobertura por veículos',
      news: 'Notícias monitoradas',
      schedules: 'Envios programados',
      admin: 'Administração'
    }[this.page()];
  }

  pageDescription(): string {
    return {
      overview: 'Veja o que exige atenção agora, sem excesso de informação.',
      keywords: 'Defina os temas da sua conta e acompanhe o volume de cada termo.',
      sources: 'Compare quem mais publicou dentro do mesmo recorte usado nas outras páginas.',
      news: 'Combine temas, veículos, editorias, riscos, tons e localidades em uma única busca.',
      schedules: 'Receba um recorte objetivo no seu e-mail, no dia e horário que escolher.',
      admin: 'Gerencie acessos e contas da Central de Monitoramento.'
    }[this.page()];
  }

  openKeywords(): void {
    this.navigate('keywords');
  }

  private activatePage(page: DashboardPage, _resetDetailFilters: boolean): void {
    if (page === 'admin' && this.user() && !this.user()!.admin) {
      window.history.replaceState({}, '', '/');
      page = 'overview';
    }
    this.page.set(page);
    document.title = `${this.pageTitle()} — Central MCS`;

    if (page === 'keywords' && this.user()) {
      this.keywordError.set('');
      this.keywordMessage.set('');
      this.selectedKeywordIds.clear();
      this.loadKeywords();
    }
    if (page === 'schedules' && this.user()) {
      this.scheduleError.set('');
      this.scheduleMessage.set('');
      this.loadKeywords();
      this.loadSchedules();
      this.prepareScheduleForm();
    }
    if (page === 'admin' && this.user()?.admin) {
      this.accountError.set('');
      this.accountMessage.set('');
      this.loadAccounts();
    }
    if (page !== 'admin' && this.user() && !this.data()) {
      this.loadFilterOptions();
      this.load();
    }
  }

  private pageFromPath(): DashboardPage {
    const path = decodeURI(window.location.pathname).replace(/\/+$/, '') || '/';
    if (path === '/palavras-chave') return 'keywords';
    if (path === '/veiculos') return 'sources';
    if (path === '/noticias') return 'news';
    if (path === '/envios') return 'schedules';
    if (path === '/admin') return 'admin';
    return 'overview';
  }

  closeKeywords(): void {
    this.navigate('overview');
  }

  prepareKeywords(): void {
    this.keywordError.set('');
    this.keywordMessage.set('');
    this.selectedKeywordIds.clear();
    this.loadKeywords();
  }

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
    this.load(true);
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

  usesSharedFilters(): boolean {
    return this.page() === 'overview' || this.page() === 'keywords'
      || this.page() === 'sources' || this.page() === 'news';
  }

  toggleTextFilter(facet: TextFacet, value: string, checked: boolean): void {
    const next = new Set(this.textSelection(facet));
    if (checked) next.add(value); else next.delete(value);
    this.setTextSelection(facet, next);
    this.scheduleFilterLoad();
  }

  toggleRiskFilter(value: number, checked: boolean): void {
    const next = new Set(this.selectedRisks());
    if (checked) next.add(value); else next.delete(value);
    this.selectedRisks.set(next);
    this.scheduleFilterLoad();
  }

  textFilterSelected(facet: TextFacet, value: string): boolean {
    return this.textSelection(facet).has(value);
  }

  riskFilterSelected(value: number): boolean {
    return this.selectedRisks().has(value);
  }

  facetCount(facet: TextFacet | 'risk'): number {
    return facet === 'risk' ? this.selectedRisks().size : this.textSelection(facet).size;
  }

  facetSummary(facet: TextFacet | 'risk'): string {
    const count = this.facetCount(facet);
    return count ? `${count} selecionado${count === 1 ? '' : 's'}` : 'Todos';
  }

  clearFacet(facet: TextFacet | 'risk', event?: Event): void {
    event?.preventDefault();
    event?.stopPropagation();
    if (facet === 'risk') this.selectedRisks.set(new Set());
    else this.setTextSelection(facet, new Set());
    this.scheduleFilterLoad();
  }

  filteredFacetOptions(facet: TextFacet): string[] {
    const options = {
      keyword: this.filters().keywords,
      source: this.filters().sources,
      section: this.filters().sections,
      tone: this.filters().tones
    }[facet];
    const search = (facet === 'keyword' ? this.keywordFilterSearch
      : facet === 'source' ? this.sourceFilterSearch : '').trim().toLocaleLowerCase('pt-BR');
    return options.filter(value => !search || value.toLocaleLowerCase('pt-BR').includes(search));
  }

  activeFilterCount(): number {
    return this.selectedKeywords().size + this.selectedSources().size + this.selectedSections().size
      + this.selectedRisks().size + this.selectedTones().size + this.selectedLocations.length
      + (this.search.trim() ? 1 : 0);
  }

  filterContextSummary(): string {
    const parts: string[] = [];
    if (this.selectedKeywords().size) parts.push(this.compactSelection('Temas', this.selectedKeywords()));
    if (this.selectedSources().size) parts.push(this.compactSelection('Veículos', this.selectedSources()));
    if (this.selectedSections().size) parts.push(this.compactSelection('Editorias', this.selectedSections()));
    if (this.selectedRisks().size) parts.push(`Riscos: ${[...this.selectedRisks()].sort().join(', ')}`);
    if (this.selectedTones().size) parts.push(this.compactSelection('Tons', this.selectedTones()));
    if (this.selectedLocations.length) parts.push(`Abrangência: ${this.geographyLabel()}`);
    if (this.search.trim()) parts.push(`Busca: “${this.search.trim()}”`);
    return parts.length ? parts.join(' · ') : 'Todo o conteúdo monitorado na sua conta';
  }

  onSharedSearchChange(): void {
    this.scheduleFilterLoad();
  }

  viewSourceNews(source: string): void {
    this.selectedSources.set(new Set([source]));
    this.navigate('news');
    this.load(true);
  }

  private textSelection(facet: TextFacet): ReadonlySet<string> {
    return {
      keyword: this.selectedKeywords(),
      source: this.selectedSources(),
      section: this.selectedSections(),
      tone: this.selectedTones()
    }[facet];
  }

  private setTextSelection(facet: TextFacet, value: ReadonlySet<string>): void {
    if (facet === 'keyword') this.selectedKeywords.set(value);
    if (facet === 'source') this.selectedSources.set(value);
    if (facet === 'section') this.selectedSections.set(value);
    if (facet === 'tone') this.selectedTones.set(value);
  }

  private compactSelection(label: string, values: ReadonlySet<string>): string {
    const selected = [...values];
    const visible = selected.slice(0, 2).map(value => this.toneLabel(value)).join(', ');
    return `${label}: ${visible}${selected.length > 2 ? ` +${selected.length - 2}` : ''}`;
  }

  private scheduleFilterLoad(): void {
    if (this.filterReloadTimer !== undefined) window.clearTimeout(this.filterReloadTimer);
    this.filterReloadTimer = window.setTimeout(() => this.load(true), 180);
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

  private loadFilterOptions(): void {
    this.http.get<Filters>('/dashboard-api/filters').subscribe({
      next: value => {
        this.filters.set(value);
        const keywordChanged = this.keepAvailable(this.selectedKeywords, value.keywords);
        const sourceChanged = this.keepAvailable(this.selectedSources, value.sources);
        const sectionChanged = this.keepAvailable(this.selectedSections, value.sections);
        const toneChanged = this.keepAvailable(this.selectedTones, value.tones);
        const validRisks = new Set(value.risks);
        const risks = new Set([...this.selectedRisks()].filter(item => validRisks.has(item)));
        const riskChanged = risks.size !== this.selectedRisks().size;
        if (riskChanged) this.selectedRisks.set(risks);
        if (keywordChanged || sourceChanged || sectionChanged || toneChanged || riskChanged) {
          this.scheduleFilterLoad();
        }
      }
    });
  }

  private keepAvailable(
    target: { (): ReadonlySet<string>; set(value: ReadonlySet<string>): void },
    available: string[]
  ): boolean {
    const allowed = new Set(available.map(value => value.toLocaleLowerCase('pt-BR')));
    const next = new Set([...target()].filter(value => allowed.has(value.toLocaleLowerCase('pt-BR'))));
    if (next.size === target().size) return false;
    target.set(next);
    return true;
  }

  private loadSchedules(): void {
    this.http.get<EmailSchedule[]>('/dashboard-api/email-schedules').subscribe({
      next: schedules => this.emailSchedules.set(schedules),
      error: error => this.scheduleError.set(this.authError(error, 'Não foi possível carregar seus envios.'))
    });
  }

  private prepareScheduleForm(): void {
    if (this.scheduleDate && this.scheduleTime) return;
    const next = new Date(Date.now() + 60 * 60 * 1000);
    this.scheduleDate = [
      next.getFullYear(),
      String(next.getMonth() + 1).padStart(2, '0'),
      String(next.getDate()).padStart(2, '0')
    ].join('-');
    this.scheduleTime = `${String(next.getHours()).padStart(2, '0')}:${String(next.getMinutes()).padStart(2, '0')}`;
  }

  toggleScheduleKeyword(keyword: string, checked: boolean): void {
    if (checked) this.scheduleKeywords.add(keyword); else this.scheduleKeywords.delete(keyword);
  }

  scheduleKeywordChecked(keyword: string): boolean { return this.scheduleKeywords.has(keyword); }

  toggleAllScheduleKeywords(checked: boolean): void {
    this.scheduleKeywords.clear();
    if (checked) this.filters().keywords.forEach(keyword => this.scheduleKeywords.add(keyword));
  }

  createSchedule(): void {
    this.scheduleError.set('');
    this.scheduleMessage.set('');
    if (!this.scheduleDate || !this.scheduleTime) {
      this.scheduleError.set('Escolha a data e o horário do envio.');
      return;
    }
    this.http.post<{ id: number }>('/dashboard-api/email-schedules', {
      scheduledAt: `${this.scheduleDate}T${this.scheduleTime}:00`,
      risk: this.scheduleRisk === '' ? null : Number(this.scheduleRisk),
      keywords: [...this.scheduleKeywords],
      recipientEmail: this.user()?.externalEmailAllowed ? this.scheduleRecipientEmail.trim() || null : null
    }).subscribe({
      next: () => {
        this.scheduleMessage.set('Envio programado. A coleta será atualizada antes do horário.');
        this.scheduleKeywords.clear();
        this.scheduleRisk = '';
        this.scheduleRecipientEmail = '';
        this.scheduleDate = '';
        this.scheduleTime = '';
        this.prepareScheduleForm();
        this.loadSchedules();
      },
      error: error => this.scheduleError.set(this.authError(error, 'Não foi possível programar o envio.'))
    });
  }

  cancelSchedule(schedule: EmailSchedule): void {
    this.scheduleError.set('');
    this.http.delete(`/dashboard-api/email-schedules/${schedule.id}`).subscribe({
      next: () => { this.scheduleMessage.set('Agendamento cancelado.'); this.loadSchedules(); },
      error: error => this.scheduleError.set(this.authError(error, 'Não foi possível cancelar o agendamento.'))
    });
  }

  activeSchedules(): number {
    return this.emailSchedules().filter(item => item.status === 'PENDING' || item.status === 'PREPARING').length;
  }

  scheduleStatus(value: EmailSchedule['status']): string {
    return { PENDING: 'Programado', PREPARING: 'Preparando', SENT: 'Enviado', FAILED: 'Falhou' }[value];
  }

  scheduleRiskLabel(value: number | null): string {
    return value == null ? 'Todos os riscos' : `Risco ${value}`;
  }

  minimumScheduleDate(): string {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  }

  toggleWhatsappKeyword(keyword: string, checked: boolean): void {
    if (checked) this.whatsappKeywords.add(keyword); else this.whatsappKeywords.delete(keyword);
    this.invalidateWhatsappReport();
  }

  whatsappKeywordChecked(keyword: string): boolean { return this.whatsappKeywords.has(keyword); }

  toggleAllWhatsappKeywords(checked: boolean): void {
    this.whatsappKeywords.clear();
    if (checked) this.filters().keywords.forEach(keyword => this.whatsappKeywords.add(keyword));
    this.invalidateWhatsappReport();
  }

  onWhatsappRiskChange(): void { this.invalidateWhatsappReport(); }

  prepareWhatsappReport(): void {
    this.whatsappGenerating.set(true);
    this.whatsappError.set('');
    this.whatsappMessage.set('');
    this.whatsappReady.set(false);
    this.whatsappReportFile = undefined;
    const selected = [...this.whatsappKeywords];
    this.http.post<ReportOverview>('/dashboard-api/whatsapp-report', {
      risk: this.whatsappRisk === '' ? null : Number(this.whatsappRisk),
      keywords: selected
    }).subscribe({
      next: async value => {
        try {
          const terms = selected.length ? selected : this.filters().keywords;
          this.whatsappReportFile = await this.reportPdf.createFile(value, {
            periodLabel: 'Últimas 24 horas',
            filters: [
              this.whatsappRisk === '' ? 'Todos os riscos' : `Risco: ${this.whatsappRisk}`,
              `Palavras-chave: ${terms.join(', ')}`
            ],
            dashboardUrl: `${window.location.origin}/noticias`
          });
          this.whatsappReady.set(true);
          this.whatsappMessage.set(this.canShareWhatsappFile()
            ? 'PDF pronto. Toque em “Enviar PDF” e escolha o WhatsApp.'
            : 'PDF pronto. Baixe o documento e anexe-o no WhatsApp Web.');
        } catch {
          this.whatsappError.set('Não foi possível montar o PDF. Tente novamente.');
        } finally {
          this.whatsappGenerating.set(false);
        }
      },
      error: error => {
        this.whatsappError.set(this.authError(error, 'Não foi possível preparar o relatório.'));
        this.whatsappGenerating.set(false);
      }
    });
  }

  canShareWhatsappFile(): boolean {
    if (!this.whatsappReportFile || typeof navigator.share !== 'function') return false;
    return typeof navigator.canShare !== 'function' || navigator.canShare({ files: [this.whatsappReportFile] });
  }

  async shareWhatsappReport(): Promise<void> {
    if (!this.whatsappReportFile || !this.canShareWhatsappFile()) {
      this.whatsappError.set('Este navegador não compartilha arquivos diretamente. Baixe o PDF e abra o WhatsApp.');
      return;
    }
    this.whatsappError.set('');
    try {
      await navigator.share({
        files: [this.whatsappReportFile],
        title: 'Panorama de impacto midiático'
      });
      this.whatsappMessage.set('O PDF foi entregue ao aplicativo escolhido para você concluir o envio.');
    } catch (error) {
      if ((error as DOMException)?.name !== 'AbortError') {
        this.whatsappError.set('Não foi possível abrir o compartilhamento. Baixe o PDF e tente novamente.');
      }
    }
  }

  downloadWhatsappReport(): void {
    if (!this.whatsappReportFile) return;
    this.reportPdf.download(this.whatsappReportFile);
    this.whatsappMessage.set('PDF baixado. Agora abra o WhatsApp Web e anexe o arquivo à conversa.');
  }

  openWhatsappWeb(): void {
    window.open('https://web.whatsapp.com/', '_blank', 'noopener,noreferrer');
  }

  private invalidateWhatsappReport(): void {
    this.whatsappReportFile = undefined;
    this.whatsappReady.set(false);
    this.whatsappError.set('');
    this.whatsappMessage.set('');
  }

  createAccount(): void {
    this.accountError.set('');
    this.accountMessage.set('');
    this.http.post<{ id: number }>('/auth-api/users', {
      username: this.accountUsername,
      email: this.accountEmail,
      password: this.accountPassword,
      admin: false
    }).subscribe({
      next: () => {
        this.accountUsername = '';
        this.accountEmail = '';
        this.accountPassword = '';
        this.accountMessage.set('Conta criada com acesso padrão ao dashboard.');
        this.loadAccounts();
      },
      error: error => this.accountError.set(this.authError(error, 'Não foi possível criar a conta.'))
    });
  }

  deleteAccount(account: ManagedUser): void {
    this.accountError.set('');
    this.accountMessage.set('');
    if (account.id === this.user()?.id) {
      this.accountError.set('Sua própria conta não pode ser excluída.');
      return;
    }
    const confirmed = window.confirm(
      `Excluir permanentemente a conta "${account.username}"? Palavras-chave, sessões e agendamentos dessa conta também serão removidos.`
    );
    if (!confirmed) return;
    this.http.delete(`/auth-api/users/${account.id}`).subscribe({
      next: () => {
        this.accountMessage.set(`A conta ${account.username} foi excluída.`);
        this.loadAccounts();
      },
      error: error => this.accountError.set(this.authError(error, 'Não foi possível excluir a conta.'))
    });
  }

  transferOwnership(account: ManagedUser): void {
    this.accountError.set('');
    this.accountMessage.set('');
    const confirmed = window.confirm(
      `Transferir a administração exclusiva para "${account.username}"? Sua conta perderá o acesso administrativo.`
    );
    if (!confirmed) return;
    this.http.put(`/auth-api/users/${account.id}/owner`, {}).subscribe({
      next: () => {
        this.authMessage.set(`Administração transferida. Entre com a conta ${account.username} para acessar /admin.`);
        this.http.post('/auth-api/logout', {}).subscribe({
          next: () => {
            this.user.set(null);
            this.data.set(null);
            this.authMode.set('login');
            window.history.replaceState({}, '', '/');
          }
        });
      },
      error: error => this.accountError.set(this.authError(error, 'Não foi possível transferir a administração.'))
    });
  }

  updateExternalEmailPermission(account: ManagedUser): void {
    this.accountError.set('');
    this.accountMessage.set('');
    const enabled = !account.externalEmailAllowed;
    this.http.put(`/auth-api/users/${account.id}/external-email`, { enabled }).subscribe({
      next: () => {
        if (account.id === this.user()?.id) {
          this.user.update(current => current ? { ...current, externalEmailAllowed: enabled } : current);
        }
        this.accountMessage.set(enabled
          ? `${account.username} agora pode escolher outro e-mail nos agendamentos.`
          : `Envio para outros e-mails bloqueado para ${account.username}.`);
        this.loadAccounts();
      },
      error: error => this.accountError.set(this.authError(error, 'Não foi possível alterar a permissão de envio.'))
    });
  }

  updateWhatsappPermission(account: ManagedUser): void {
    this.accountError.set('');
    this.accountMessage.set('');
    const enabled = !account.whatsappAllowed;
    this.http.put(`/auth-api/users/${account.id}/whatsapp`, { enabled }).subscribe({
      next: () => {
        if (account.id === this.user()?.id) {
          this.user.update(current => current ? { ...current, whatsappAllowed: enabled } : current);
        }
        this.accountMessage.set(enabled
          ? `${account.username} agora pode preparar PDFs para o WhatsApp.`
          : `Compartilhamento por WhatsApp bloqueado para ${account.username}.`);
        this.loadAccounts();
      },
      error: error => this.accountError.set(this.authError(error, 'Não foi possível alterar a permissão do WhatsApp.'))
    });
  }

  private loadAccounts(): void {
    this.http.get<ManagedUser[]>('/auth-api/users').subscribe({
      next: users => this.managedUsers.set(users),
      error: () => this.accountError.set('Não foi possível carregar as contas.')
    });
  }

  filteredAccounts(): ManagedUser[] {
    const term = this.accountSearch.trim().toLocaleLowerCase('pt-BR');
    if (!term) return this.managedUsers();
    return this.managedUsers().filter(account =>
      [account.username, account.displayName, account.email]
        .some(value => value?.toLocaleLowerCase('pt-BR').includes(term))
    );
  }

  activeAdminCount(): number {
    return this.managedUsers().filter(account => account.active && account.admin).length;
  }

  load(resetArticlePage = false): void {
    if (resetArticlePage) this.articlePage.set(1);
    const sequence = ++this.loadSequence;
    this.loading.set(true);
    this.error.set('');
    const params = this.params();
    this.http.get<Overview>('/dashboard-api/overview', { params }).subscribe({
      next: value => {
        if (sequence !== this.loadSequence) return;
        this.data.set(value);
        this.loading.set(false);
      },
      error: () => {
        if (sequence !== this.loadSequence) return;
        this.error.set('Não foi possível carregar os dados. Tente novamente.');
        this.loading.set(false);
      }
    });
  }

  openReport(): void {
    this.reportError.set('');
    this.reportOpen.set(true);
  }

  closeReport(): void {
    if (!this.reportGenerating()) this.reportOpen.set(false);
  }

  generateReport(): void {
    this.reportGenerating.set(true);
    this.reportError.set('');
    const params = this.params().set('includeAll', true);
    this.http.get<ReportOverview>('/dashboard-api/overview', { params }).subscribe({
      next: async value => {
        try {
          await this.reportPdf.generate(value, {
            periodLabel: this.periodLabel(),
            filters: this.activeFilterLabels(),
            notes: this.reportNotes,
            dashboardUrl: `${window.location.origin}/noticias`
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

  clear(): void {
    this.days = 7;
    this.selectedKeywords.set(new Set());
    this.selectedSources.set(new Set());
    this.selectedSections.set(new Set());
    this.selectedRisks.set(new Set());
    this.selectedTones.set(new Set());
    this.selectedLocations = [];
    this.keywordFilterSearch = '';
    this.sourceFilterSearch = '';
    this.search = '';
    this.load(true);
  }
  periodLabel(): string {
    if (this.days === 1) return 'Últimas 24 horas';
    if (this.days === 2) return 'Últimas 48 horas';
    return `Últimos ${this.days} dias`;
  }
  max(points: Point[] | undefined): number { return Math.max(...(points ?? []).map(item => item.value), 1); }
  width(point: Point, points: Point[] | undefined): number { return Math.max(3, point.value / this.max(points) * 100); }
  riskClass(risk: number): string { return risk === 10 ? 'critical' : risk === 5 ? 'attention' : 'neutral'; }
  toneLabel(value: string): string { return value.replaceAll('_', ' '); }
  impactLabel(value: number): string { return value >= 7 ? 'Alto impacto' : value >= 4 ? 'Impacto moderado' : 'Baixo impacto'; }
  impactClass(value: number): string { return value >= 7 ? 'high' : value >= 4 ? 'medium' : 'low'; }
  date(value: string): string { return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)); }
  day(value: string): string { return new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit' }).format(new Date(value + 'T12:00:00')); }
  sourceType(source: string): string { return source.startsWith('Instagram/') ? 'Instagram' : source.includes('.') ? 'Web' : 'RSS'; }
  priorityArticles(): Article[] {
    return [...(this.data()?.articles ?? [])]
      .sort((a, b) => b.risk - a.risk || b.impact - a.impact || Date.parse(b.publishedAt) - Date.parse(a.publishedAt))
      .slice(0, 6);
  }
  topKeyword(): Point | undefined { return this.data()?.byKeyword?.[0]; }
  topSource(): Point | undefined { return this.data()?.bySource?.[0]; }
  visibleArticles(): Article[] {
    return this.data()?.articles ?? [];
  }

  articleTotal(): number {
    return this.data()?.pagination?.totalItems ?? this.data()?.kpis.articles ?? 0;
  }

  articleTotalPages(): number {
    return Math.max(1, this.data()?.pagination?.totalPages ?? 1);
  }

  goToArticlePage(page: number): void {
    const bounded = Math.max(1, Math.min(page, this.articleTotalPages()));
    if (bounded === this.articlePage()) return;
    this.articlePage.set(bounded);
    this.load();
  }

  private params(): HttpParams {
    let params = new HttpParams().set('days', this.days);
    if (this.page() === 'news') {
      params = params.set('page', this.articlePage()).set('pageSize', 50);
    }
    this.selectedKeywords().forEach(value => params = params.append('keyword', value));
    this.selectedSources().forEach(value => params = params.append('source', value));
    this.selectedSections().forEach(value => params = params.append('section', value));
    this.selectedRisks().forEach(value => params = params.append('risk', String(value)));
    this.selectedTones().forEach(value => params = params.append('tone', value));
    if (this.search.trim()) params = params.set('query', this.search.trim());
    this.selectedLocations.forEach(location => params = params.append('location', location));
    return params;
  }

  private activeFilterLabels(): string[] {
    const labels: string[] = [];
    this.selectedKeywords().forEach(value => labels.push(`Palavra-chave: ${value}`));
    this.selectedSources().forEach(value => labels.push(`Veículo: ${value}`));
    this.selectedSections().forEach(value => labels.push(`Editoria: ${this.toneLabel(value)}`));
    this.selectedRisks().forEach(value => labels.push(`Risco: ${value}`));
    this.selectedTones().forEach(value => labels.push(`Tom: ${this.toneLabel(value)}`));
    if (this.search.trim()) labels.push(`Busca livre: ${this.search.trim()}`);
    if (this.selectedLocations.includes('estado_rj')) labels.push('Abrangência: Todo o Estado do Rio de Janeiro');
    else if (this.selectedLocations.length) labels.push(`Municípios: ${this.selectedLocations.join(', ')}`);
    return labels;
  }

  private authError(error: any, fallback: string): string {
    return error?.error?.detail || error?.error?.message || error?.error?.error || fallback;
  }
}
