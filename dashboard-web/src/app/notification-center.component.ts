import { CommonModule } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import {
  Component,
  ElementRef,
  HostListener,
  OnDestroy,
  OnInit,
  ViewChild,
  inject,
  signal
} from '@angular/core';

interface McsAlert {
  id: number;
  title: string;
  url: string;
  source: string;
  publishedAt?: string;
  detectedAt: string;
  matchedTerms: string[];
  excerpt?: string;
  risk: number;
  impact: number;
  read: boolean;
  readAt?: string;
}

interface AlertResponse {
  items: McsAlert[];
  unreadCount: number;
  nextCursor?: number;
}

@Component({
  selector: 'app-notification-center',
  imports: [CommonModule],
  templateUrl: './notification-center.component.html',
  styleUrl: './notification-center.component.scss'
})
export class NotificationCenterComponent implements OnInit, OnDestroy {
  private readonly http = inject(HttpClient);
  private pollingId?: number;
  private countLoaded = false;
  private countLoading = false;
  private previousBodyOverflow = '';
  private readonly visibilityHandler = () => {
    if (document.visibilityState === 'visible') this.refreshUnread();
  };

  @ViewChild('bellButton') private bellButton?: ElementRef<HTMLButtonElement>;
  @ViewChild('closeButton') private closeButton?: ElementRef<HTMLButtonElement>;
  @ViewChild('alertPanel') private alertPanel?: ElementRef<HTMLElement>;

  readonly open = signal(false);
  readonly items = signal<McsAlert[]>([]);
  readonly unreadCount = signal(0);
  readonly nextCursor = signal<number | null>(null);
  readonly loading = signal(false);
  readonly loadingMore = signal(false);
  readonly markingAll = signal(false);
  readonly error = signal('');
  readonly announcement = signal('');

  ngOnInit(): void {
    this.refreshUnread();
    this.pollingId = window.setInterval(() => this.refreshUnread(), 60_000);
    document.addEventListener('visibilitychange', this.visibilityHandler);
  }

  ngOnDestroy(): void {
    if (this.pollingId !== undefined) window.clearInterval(this.pollingId);
    document.removeEventListener('visibilitychange', this.visibilityHandler);
    document.body.style.overflow = this.previousBodyOverflow;
  }

  toggle(): void {
    if (this.open()) this.close();
    else this.openPanel();
  }

  openPanel(): void {
    this.open.set(true);
    this.previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    this.loadAlerts(true);
    window.setTimeout(() => this.closeButton?.nativeElement.focus(), 0);
  }

  close(): void {
    if (!this.open()) return;
    this.open.set(false);
    this.restoreBodyScroll();
    window.setTimeout(() => this.bellButton?.nativeElement.focus(), 0);
  }

  @HostListener('document:keydown', ['$event'])
  handleKeydown(event: KeyboardEvent): void {
    if (!this.open()) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      this.close();
      return;
    }
    if (event.key !== 'Tab') return;

    const panel = this.alertPanel?.nativeElement;
    if (!panel) return;
    const focusable = [...panel.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
      'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )].filter(element => !element.hasAttribute('hidden'));
    if (!focusable.length) {
      event.preventDefault();
      panel.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !panel.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !panel.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  }

  refreshUnread(): void {
    if (this.countLoading || document.visibilityState === 'hidden') return;
    this.countLoading = true;
    this.http.get<{ unreadCount: number }>('/dashboard-api/alerts/unread-count').subscribe({
      next: response => {
        const previous = this.unreadCount();
        this.unreadCount.set(response.unreadCount);
        if (this.countLoaded && response.unreadCount > previous) {
          const added = response.unreadCount - previous;
          this.announcement.set(
            added === 1
              ? `Uma nova menção ao MCS foi encontrada. ${response.unreadCount} não lida no total.`
              : `${added} novas menções ao MCS foram encontradas. ${response.unreadCount} não lidas no total.`
          );
        }
        this.countLoaded = true;
      },
      error: () => {
        this.countLoading = false;
      },
      complete: () => {
        this.countLoading = false;
      }
    });
  }

  loadAlerts(reset = true): void {
    if (reset) {
      this.loading.set(true);
      this.items.set([]);
      this.nextCursor.set(null);
    } else {
      if (!this.nextCursor() || this.loadingMore()) return;
      this.loadingMore.set(true);
    }
    this.error.set('');
    let params = new HttpParams().set('limit', '20');
    if (!reset && this.nextCursor()) params = params.set('beforeId', String(this.nextCursor()));
    this.http.get<AlertResponse>('/dashboard-api/alerts', { params }).subscribe({
      next: response => {
        this.items.update(current => reset ? response.items : [...current, ...response.items]);
        this.unreadCount.set(response.unreadCount);
        this.nextCursor.set(response.nextCursor ?? null);
        this.loading.set(false);
        this.loadingMore.set(false);
      },
      error: () => {
        this.error.set('Não foi possível carregar os alertas agora.');
        this.loading.set(false);
        this.loadingMore.set(false);
      }
    });
  }

  markRead(alert: McsAlert): void {
    if (alert.read) return;
    this.items.update(items => items.map(item => item.id === alert.id ? { ...item, read: true } : item));
    this.unreadCount.update(value => Math.max(0, value - 1));
    this.http.put<{ unreadCount: number }>(`/dashboard-api/alerts/${alert.id}/read`, {}).subscribe({
      next: response => this.unreadCount.set(response.unreadCount),
      error: () => {
        this.items.update(items => items.map(item => item.id === alert.id ? { ...item, read: false } : item));
        this.refreshUnread();
      }
    });
  }

  markAllRead(): void {
    if (!this.unreadCount() || this.markingAll()) return;
    this.markingAll.set(true);
    this.http.put<{ unreadCount: number }>('/dashboard-api/alerts/read-all', {}).subscribe({
      next: response => {
        this.items.update(items => items.map(item => ({ ...item, read: true })));
        this.unreadCount.set(response.unreadCount);
        this.markingAll.set(false);
      },
      error: () => {
        this.markingAll.set(false);
        this.error.set('Não foi possível marcar os alertas como lidos.');
      }
    });
  }

  badge(): string {
    return this.unreadCount() > 9 ? '9+' : String(this.unreadCount());
  }

  ariaLabel(): string {
    const count = this.unreadCount();
    if (!count) return 'Alertas do MCS, nenhum alerta não lido';
    return `Alertas do MCS, ${count} ${count === 1 ? 'alerta não lido' : 'alertas não lidos'}`;
  }

  matchedTerms(alert: McsAlert): string {
    return alert.matchedTerms.join(' + ');
  }

  riskClass(risk: number): string {
    return risk >= 10 ? 'critical' : risk >= 5 ? 'attention' : 'neutral';
  }

  trackAlert(_: number, alert: McsAlert): number {
    return alert.id;
  }

  private restoreBodyScroll(): void {
    document.body.style.overflow = this.previousBodyOverflow;
  }
}
