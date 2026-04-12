# Angular Migration Plan

**Status:** Planning
**Created:** 2024-12-30
**Decision:** Pending

---

## Executive Summary

This document outlines the plan to migrate Mission Control's frontend from vanilla JavaScript to Angular with PrimeNG. The primary driver is potential future integration with Cortex XDR, which uses the same stack.

---

## Context

### Current State

- **Frontend:** ~1,600 lines vanilla JavaScript across 5 files
- **Architecture:** Django templates with class-based JS managers
- **Patterns:** Direct DOM manipulation, manual state management, event-driven
- **Build:** No bundler, Jest for testing

| File | Lines | Responsibility |
|------|-------|----------------|
| dashboard.js | 617 | Range launch, status polling, agent selection |
| terminal.js | 425 | Dual xterm.js terminals, WebSocket connections |
| xdr-dropdown.js | 256 | Custom dropdown component |
| upload.js | 219 | Presigned URL upload with progress |
| sidebar.js | 62 | Navigation state |

### Why Migrate

1. **Cortex XDR Compatibility**
   Cortex uses Angular + PrimeNG. If Shifter integrates with Cortex (ranges for clients, automated red teaming), same-stack means zero rewrite.

2. **Incoming Complexity**
   - Multi-tab terminal UI
   - CMS for content management
   - Multiple asset categories beyond agents

3. **Current Pain Points**
   - Code duplication in dropdown population
   - Manual state synchronization
   - Fragile DOM coupling (30+ cached queries)
   - WebSocket handlers duplicated for Kali/Victim

### Why Not Migrate

- Learning curve if unfamiliar with Angular
- Slower initial velocity (1-2 week setup vs shipping today)
- Overkill if Cortex integration never happens

---

## Target Architecture

### Stack

| Layer | Technology | Notes |
|-------|------------|-------|
| Framework | Angular 17+ | Standalone components, signals |
| Components | PrimeNG 17 | Matches Cortex XDR component library |
| State | Angular Signals | Reactive, no NgRx needed at this scale |
| Styling | SCSS + CSS Variables | Reuse existing xdr-theme.css |
| Terminal | xterm.js | Same as current |
| WebSocket | RxJS WebSocketSubject | Native Angular pattern |
| HTTP | HttpClient | CSRF interceptor for Django |

### Integration Model

```
┌─────────────────────────────────────────────────────────────┐
│                         Browser                              │
├─────────────────────────────────────────────────────────────┤
│  Angular SPA (served from /mission-control/*)               │
│  ├── Dashboard (range launcher, status)                     │
│  ├── Agents (upload, list, delete)                          │
│  ├── Terminal (multi-tab xterm.js + WebSocket)              │
│  ├── Assets (future: multiple asset categories)             │
│  ├── CMS (future: content management)                       │
│  └── Settings                                                │
├─────────────────────────────────────────────────────────────┤
│                    HTTP / WebSocket                          │
├─────────────────────────────────────────────────────────────┤
│  Django Backend                                              │
│  ├── /mission-control/api/*  (REST endpoints)               │
│  ├── /ws/terminal/*          (WebSocket for SSH)            │
│  └── /mission-control/*      (serves Angular SPA)           │
└─────────────────────────────────────────────────────────────┘
```

Django serves the Angular build artifacts. Angular handles all client-side routing under `/mission-control/`. API routes remain unchanged.

---

## Project Structure

```
shifter/
├── portal/                          # Django (mostly unchanged)
│   ├── mission_control/
│   │   ├── views.py                 # Add spa() view, keep API views
│   │   └── urls.py                  # Add SPA catch-all route
│   ├── templates/
│   │   └── mission_control/
│   │       └── spa.html             # Bootstrap template for Angular
│   └── static/
│       └── ng/                      # Angular build output (gitignored)
│
└── frontend/                        # NEW: Angular application
    ├── angular.json
    ├── package.json
    ├── tsconfig.json
    ├── proxy.conf.json              # Dev server proxy to Django
    │
    └── src/
        ├── index.html
        ├── main.ts
        ├── styles.scss
        │
        └── app/
            ├── app.component.ts
            ├── app.routes.ts
            ├── app.config.ts
            │
            ├── core/                # Singletons, guards, interceptors
            │   ├── services/
            │   │   ├── api.service.ts
            │   │   ├── auth.service.ts
            │   │   ├── range.service.ts
            │   │   ├── agents.service.ts
            │   │   ├── upload.service.ts
            │   │   └── websocket.service.ts
            │   ├── guards/
            │   │   └── auth.guard.ts
            │   ├── interceptors/
            │   │   └── csrf.interceptor.ts
            │   └── models/
            │       ├── range.model.ts
            │       ├── agent.model.ts
            │       └── user.model.ts
            │
            ├── shared/              # Reusable components
            │   ├── components/
            │   │   ├── sidebar/
            │   │   │   ├── sidebar.component.ts
            │   │   │   ├── sidebar.component.html
            │   │   │   └── sidebar.component.scss
            │   │   ├── status-badge/
            │   │   ├── loading-spinner/
            │   │   └── confirm-dialog/
            │   ├── pipes/
            │   │   └── time-ago.pipe.ts
            │   └── directives/
            │
            └── features/            # Feature modules (lazy loaded)
                │
                ├── dashboard/
                │   ├── dashboard.component.ts
                │   ├── dashboard.component.html
                │   ├── dashboard.component.scss
                │   └── components/
                │       ├── range-launcher/
                │       │   ├── range-launcher.component.ts
                │       │   └── range-launcher.component.html
                │       ├── range-status/
                │       ├── scenario-selector/
                │       └── agent-dropdown/
                │
                ├── agents/
                │   ├── agents.component.ts
                │   └── components/
                │       ├── agent-list/
                │       ├── agent-upload/
                │       └── agent-delete-dialog/
                │
                ├── terminal/
                │   ├── terminal.component.ts
                │   └── components/
                │       ├── terminal-pane/       # xterm.js wrapper
                │       ├── terminal-tabs/       # Tab bar for multi-tab
                │       ├── terminal-toolbar/    # Actions, connection status
                │       └── terminal-divider/    # Resizable split
                │
                ├── assets/                      # FUTURE
                │   ├── assets.component.ts
                │   └── components/
                │       ├── asset-category-nav/
                │       ├── asset-list/
                │       ├── asset-upload/
                │       └── asset-detail/
                │
                ├── cms/                         # FUTURE
                │   ├── cms.component.ts
                │   └── components/
                │       ├── content-list/
                │       ├── content-editor/
                │       ├── content-preview/
                │       └── category-manager/
                │
                └── settings/
                    ├── settings.component.ts
                    └── components/
                        └── profile-section/
```

---

## Key Implementation Details

### 1. Django URL Configuration

```python
# portal/mission_control/urls.py

from django.urls import path, re_path
from . import views

app_name = "mission_control"

urlpatterns = [
    # === API Routes (unchanged) ===
    path("api/upload/initiate/", views.initiate_upload, name="initiate_upload"),
    path("api/upload/complete/", views.complete_upload, name="complete_upload"),
    path("api/upload/cancel/", views.cancel_upload, name="cancel_upload"),
    path("api/range/status/", views.get_range_status, name="range_status"),
    path("api/range/launch/", views.launch_range, name="launch_range"),
    path("api/range/cancel/", views.cancel_range, name="cancel_range"),
    path("api/range/destroy/", views.destroy_range, name="destroy_range"),
    path("api/agents/", views.list_agents, name="list_agents"),

    # === SPA Catch-All ===
    # Serves Angular for all non-API routes under /mission-control/
    re_path(r"^(?!api/).*$", views.spa, name="spa"),
]
```

### 2. SPA Bootstrap Template

```html
<!-- portal/templates/mission_control/spa.html -->
{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shifter - Mission Control</title>
  <base href="/mission-control/">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" type="image/png" href="{% static 'images/favicon.png' %}">

  <!-- Pass Django context to Angular -->
  <script>
    window.SHIFTER_CONFIG = {
      csrfToken: "{{ csrf_token }}",
      wsProtocol: window.location.protocol === 'https:' ? 'wss:' : 'ws:',
      user: {
        email: "{{ user.email|escapejs }}",
        firstName: "{{ user.first_name|escapejs }}",
        lastName: "{{ user.last_name|escapejs }}"
      }
    };
  </script>
</head>
<body>
  <app-root></app-root>
  <script src="{% static 'ng/runtime.js' %}" type="module"></script>
  <script src="{% static 'ng/polyfills.js' %}" type="module"></script>
  <script src="{% static 'ng/main.js' %}" type="module"></script>
</body>
</html>
```

### 3. CSRF Interceptor

```typescript
// frontend/src/app/core/interceptors/csrf.interceptor.ts

import { HttpInterceptorFn } from '@angular/common/http';

declare global {
  interface Window {
    SHIFTER_CONFIG: {
      csrfToken: string;
      wsProtocol: string;
      user: { email: string; firstName: string; lastName: string };
    };
  }
}

export const csrfInterceptor: HttpInterceptorFn = (req, next) => {
  // Only add CSRF for same-origin mutating requests
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(req.method)) {
    req = req.clone({
      headers: req.headers.set('X-CSRFToken', window.SHIFTER_CONFIG.csrfToken)
    });
  }
  return next(req);
};
```

### 4. Range Service with Signals

```typescript
// frontend/src/app/core/services/range.service.ts

import { Injectable, inject, signal, computed } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { toSignal } from '@angular/core/rxjs-interop';
import { interval, switchMap, takeWhile, tap } from 'rxjs';

export interface Range {
  has_range: boolean;
  status: 'ready' | 'provisioning' | 'failed' | 'destroying' | null;
  kali_ip?: string;
  victim_ip?: string;
  agent_name?: string;
  dc_agent_name?: string;
  scenario?: string;
  created_at?: string;
  error_message?: string;
}

@Injectable({ providedIn: 'root' })
export class RangeService {
  private http = inject(HttpClient);

  // State signals
  private _range = signal<Range | null>(null);
  private _loading = signal(false);
  private _error = signal<string | null>(null);

  // Public readonly signals
  readonly range = this._range.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  // Computed state
  readonly isProvisioning = computed(() =>
    this._range()?.status === 'provisioning'
  );
  readonly isReady = computed(() =>
    this._range()?.status === 'ready'
  );
  readonly canLaunch = computed(() =>
    !this._range()?.has_range && !this._loading()
  );

  fetchStatus() {
    this._loading.set(true);
    this._error.set(null);

    this.http.get<Range>('/mission-control/api/range/status/').subscribe({
      next: (range) => {
        this._range.set(range);
        this._loading.set(false);
      },
      error: (err) => {
        this._error.set(err.error?.message || 'Failed to fetch range status');
        this._loading.set(false);
      }
    });
  }

  startPolling() {
    return interval(2000).pipe(
      switchMap(() => this.http.get<Range>('/mission-control/api/range/status/')),
      tap(range => this._range.set(range)),
      takeWhile(range =>
        ['provisioning', 'destroying'].includes(range.status || ''),
        true
      )
    );
  }

  launch(agentId: number, scenario: string, dcAgentId?: number) {
    this._loading.set(true);
    return this.http.post<Range>('/mission-control/api/range/launch/', {
      agent_id: agentId,
      scenario,
      dc_agent_id: dcAgentId
    }).pipe(
      tap({
        next: (range) => {
          this._range.set(range);
          this._loading.set(false);
        },
        error: () => this._loading.set(false)
      })
    );
  }

  destroy() {
    this._loading.set(true);
    return this.http.post('/mission-control/api/range/destroy/', {}).pipe(
      tap({ complete: () => this._loading.set(false) })
    );
  }
}
```

### 5. Terminal Pane Component

```typescript
// frontend/src/app/features/terminal/components/terminal-pane/terminal-pane.component.ts

import {
  Component, Input, Output, EventEmitter,
  OnInit, OnDestroy, ElementRef, ViewChild,
  signal, effect
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import { WebLinksAddon } from 'xterm-addon-web-links';

type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

@Component({
  selector: 'app-terminal-pane',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="terminal-pane" [class.focused]="focused">
      <div class="terminal-header">
        <span class="terminal-title">{{ title }}</span>
        <span class="terminal-ip" *ngIf="ipAddress">{{ ipAddress }}</span>
        <span
          class="terminal-status"
          [class]="status()"
          [title]="statusMessage()">
          {{ status() }}
        </span>
      </div>
      <div
        #terminalContainer
        class="terminal-container"
        (click)="focus()">
      </div>
    </div>
  `,
  styleUrl: './terminal-pane.component.scss'
})
export class TerminalPaneComponent implements OnInit, OnDestroy {
  @Input({ required: true }) title!: string;
  @Input({ required: true }) wsUrl!: string;
  @Input() ipAddress?: string;
  @Output() statusChange = new EventEmitter<ConnectionStatus>();

  @ViewChild('terminalContainer', { static: true })
  terminalContainer!: ElementRef<HTMLDivElement>;

  status = signal<ConnectionStatus>('connecting');
  statusMessage = signal('');
  focused = false;

  private terminal!: Terminal;
  private fitAddon!: FitAddon;
  private socket: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 2000;

  constructor() {
    // Emit status changes
    effect(() => {
      this.statusChange.emit(this.status());
    });
  }

  ngOnInit() {
    this.initTerminal();
    this.connect();
    this.setupResizeHandler();
  }

  private initTerminal() {
    this.terminal = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', monospace",
      theme: {
        background: '#1a1a1a',
        foreground: '#00ff00',
        cursor: '#00ff00',
        selectionBackground: '#00ff0033'
      },
      scrollback: 10000,
      convertEol: true
    });

    this.fitAddon = new FitAddon();
    this.terminal.loadAddon(this.fitAddon);
    this.terminal.loadAddon(new WebLinksAddon());

    this.terminal.open(this.terminalContainer.nativeElement);

    // Delay fit to ensure container has dimensions
    setTimeout(() => this.fitAddon.fit(), 0);

    this.terminal.onData(data => {
      if (this.socket?.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ type: 'input', data }));
      }
    });

    this.terminal.onResize(({ cols, rows }) => {
      if (this.socket?.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ type: 'resize', cols, rows }));
      }
    });
  }

  private connect() {
    this.status.set('connecting');
    this.statusMessage.set('Establishing connection...');

    const protocol = window.SHIFTER_CONFIG.wsProtocol;
    const fullUrl = `${protocol}//${window.location.host}${this.wsUrl}`;

    this.socket = new WebSocket(fullUrl);

    this.socket.onopen = () => {
      this.status.set('connected');
      this.statusMessage.set('Connected');
      this.reconnectAttempts = 0;

      // Send initial resize
      const { cols, rows } = this.terminal;
      this.socket!.send(JSON.stringify({ type: 'resize', cols, rows }));
    };

    this.socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'output') {
          this.terminal.write(msg.data);
        }
      } catch {
        // Raw data fallback
        this.terminal.write(event.data);
      }
    };

    this.socket.onclose = (event) => {
      if (event.wasClean) {
        this.status.set('disconnected');
        this.statusMessage.set('Connection closed');
      } else {
        this.handleReconnect();
      }
    };

    this.socket.onerror = () => {
      this.status.set('error');
      this.statusMessage.set('Connection error');
    };
  }

  private handleReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

      this.status.set('connecting');
      this.statusMessage.set(
        `Reconnecting (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`
      );

      setTimeout(() => this.connect(), delay);
    } else {
      this.status.set('error');
      this.statusMessage.set('Connection failed. Click to retry.');
    }
  }

  private setupResizeHandler() {
    const resizeObserver = new ResizeObserver(() => {
      this.fitAddon.fit();
    });
    resizeObserver.observe(this.terminalContainer.nativeElement);
  }

  focus() {
    this.focused = true;
    this.terminal.focus();
  }

  blur() {
    this.focused = false;
  }

  reconnect() {
    this.reconnectAttempts = 0;
    this.socket?.close();
    this.connect();
  }

  ngOnDestroy() {
    this.socket?.close();
    this.terminal?.dispose();
  }
}
```

### 6. App Routes with Lazy Loading

```typescript
// frontend/src/app/app.routes.ts

import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  {
    path: '',
    canActivate: [authGuard],
    children: [
      {
        path: '',
        redirectTo: 'dashboard',
        pathMatch: 'full'
      },
      {
        path: 'dashboard',
        loadComponent: () =>
          import('./features/dashboard/dashboard.component')
            .then(m => m.DashboardComponent),
        title: 'Dashboard - Shifter'
      },
      {
        path: 'agents',
        loadComponent: () =>
          import('./features/agents/agents.component')
            .then(m => m.AgentsComponent),
        title: 'Agents - Shifter'
      },
      {
        path: 'terminal',
        loadComponent: () =>
          import('./features/terminal/terminal.component')
            .then(m => m.TerminalComponent),
        title: 'Terminal - Shifter'
      },
      {
        path: 'assets',
        loadComponent: () =>
          import('./features/assets/assets.component')
            .then(m => m.AssetsComponent),
        title: 'Assets - Shifter'
      },
      {
        path: 'cms',
        loadComponent: () =>
          import('./features/cms/cms.component')
            .then(m => m.CmsComponent),
        title: 'Content - Shifter'
      },
      {
        path: 'settings',
        loadComponent: () =>
          import('./features/settings/settings.component')
            .then(m => m.SettingsComponent),
        title: 'Settings - Shifter'
      },
      {
        path: 'help',
        loadComponent: () =>
          import('./features/help/help.component')
            .then(m => m.HelpComponent),
        title: 'Help - Shifter'
      }
    ]
  },
  {
    path: '**',
    redirectTo: 'dashboard'
  }
];
```

### 7. App Configuration

```typescript
// frontend/src/app/app.config.ts

import { ApplicationConfig } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideAnimations } from '@angular/platform-browser/animations';

import { routes } from './app.routes';
import { csrfInterceptor } from './core/interceptors/csrf.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    provideRouter(routes, withComponentInputBinding()),
    provideHttpClient(withInterceptors([csrfInterceptor])),
    provideAnimations()
  ]
};
```

---

## Styling Strategy

### Preserve Existing Design System

The existing `xdr-theme.css` defines CSS variables that match Cortex XDR's design system. Import these into Angular:

```scss
// frontend/src/styles.scss

// Import existing theme variables
@import '../portal/static/css/xdr-theme.css';

// PrimeNG theme customization
@import 'primeng/resources/primeng.min.css';
@import 'primeicons/primeicons.css';

// Override PrimeNG with XDR variables
:root {
  // Map PrimeNG variables to XDR variables
  --primary-color: var(--xdr-primary);
  --primary-color-text: var(--xdr-on-primary);
  --surface-ground: var(--xdr-background);
  --surface-card: var(--xdr-surface);
  --text-color: var(--xdr-text);
  --text-color-secondary: var(--xdr-text-secondary);
}

// Global styles
body {
  margin: 0;
  font-family: var(--xdr-font-family);
  background: var(--xdr-background);
  color: var(--xdr-text);
}
```

### Component-Specific Styles

Each component uses scoped SCSS with XDR variables:

```scss
// Example: sidebar.component.scss

:host {
  display: flex;
  flex-direction: column;
  width: var(--sidebar-width, 240px);
  height: 100vh;
  background: var(--xdr-sidebar-bg);
  border-right: 1px solid var(--xdr-border);
}

.sidebar-nav {
  flex: 1;
  overflow-y: auto;
}

.sidebar-item {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  color: var(--xdr-text);
  text-decoration: none;
  transition: background 0.2s;

  &:hover {
    background: var(--xdr-hover);
  }

  &.active {
    background: var(--xdr-active);
    color: var(--xdr-primary);
    font-weight: 600;
  }
}
```

---

## Development Workflow

### Local Development

```bash
# Terminal 1: Django backend
cd portal
python manage.py runserver 8000

# Terminal 2: Angular dev server (proxies API to Django)
cd frontend
npm start
# Access at http://localhost:4200/mission-control/
```

### Proxy Configuration

```json
// frontend/proxy.conf.json
{
  "/mission-control/api": {
    "target": "http://localhost:8000",
    "secure": false,
    "changeOrigin": true
  },
  "/ws": {
    "target": "ws://localhost:8000",
    "ws": true
  },
  "/static": {
    "target": "http://localhost:8000",
    "secure": false
  }
}
```

### Production Build

```bash
# Build Angular (outputs to portal/static/ng/)
cd frontend
npm run build:prod

# Collect static files
cd ../portal
python manage.py collectstatic --noinput

# Deploy as usual
```

### CI/CD Integration

```yaml
# .github/workflows/deploy.yml (addition)

- name: Build Angular
  working-directory: frontend
  run: |
    npm ci
    npm run build:prod

- name: Collect Static
  working-directory: portal
  run: python manage.py collectstatic --noinput
```

---

## Migration Phases

### Phase 1: Foundation (1-2 days)

- [ ] Scaffold Angular project in `frontend/`
- [ ] Configure build to output to `portal/static/ng/`
- [ ] Create `spa.html` template
- [ ] Add SPA catch-all route in Django
- [ ] Implement CSRF interceptor
- [ ] Create sidebar component
- [ ] Verify routing works

### Phase 2: Dashboard (2-3 days)

- [ ] Create RangeService with signals
- [ ] Create AgentsService
- [ ] Build range-launcher component
- [ ] Build range-status component
- [ ] Build scenario-selector component
- [ ] Port agent dropdown to PrimeNG Dropdown
- [ ] Implement polling with RxJS
- [ ] Test launch/destroy flow

### Phase 3: Terminal (1-2 days)

- [ ] Create WebSocketService
- [ ] Build terminal-pane component (xterm.js wrapper)
- [ ] Build terminal-toolbar component
- [ ] Implement reconnection logic
- [ ] Port resize divider

### Phase 4: Agents (1-2 days)

- [ ] Create UploadService
- [ ] Build agent-list component
- [ ] Build agent-upload component with progress
- [ ] Build delete confirmation dialog
- [ ] Test upload flow end-to-end

### Phase 5: Multi-Tab Terminal (new feature)

- [ ] Build terminal-tabs component
- [ ] Add tab management (add, remove, rename)
- [ ] Persist tab state to localStorage
- [ ] Support multiple simultaneous connections

### Phase 6: Asset Categories (new feature)

- [ ] Design asset data model
- [ ] Create Django models/API
- [ ] Build asset-category-nav component
- [ ] Build asset-list component
- [ ] Build asset-upload component
- [ ] Build asset-detail component

### Phase 7: CMS (new feature)

- [ ] Design content data model
- [ ] Create Django models/API
- [ ] Build content-list component
- [ ] Build content-editor component
- [ ] Build content-preview component
- [ ] Build category-manager component

---

## Parallel Development Option

To avoid disruption, run Angular alongside existing vanilla JS:

1. Mount Angular at `/mission-control/v2/`
2. Keep current JS at `/mission-control/`
3. Migrate page by page
4. Redirect to v2 when ready
5. Remove v1 after validation

```python
# Parallel routes during migration
urlpatterns = [
    # Current vanilla JS pages (temporary)
    path("", views.dashboard, name="dashboard"),
    path("agents/", views.agents, name="agents"),
    # ...

    # Angular SPA (new)
    re_path(r"^v2/(?!api/).*$", views.spa, name="spa_v2"),

    # API (shared)
    path("api/...", ...),
]
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Learning curve delays | Start with simple pages (Settings), build complexity |
| Build complexity | Use Angular CLI defaults, avoid custom webpack |
| Django integration issues | Test SPA serving early in Phase 1 |
| WebSocket compatibility | Port terminal component early (Phase 3) |
| Styling mismatches | Preserve all existing CSS variables |
| Testing gaps | Maintain Jest tests for Django, add Jasmine for Angular |

---

## Success Criteria

1. **Functional parity** with current vanilla JS
2. **No performance regression** (measure load times)
3. **Same styling** (visual regression testing)
4. **API unchanged** (no Django modifications beyond routing)
5. **WebSocket stable** (terminal works reliably)
6. **Build integrates** with existing CI/CD

---

## References

- [Angular Documentation](https://angular.io/docs)
- [PrimeNG Components](https://primeng.org/)
- [xterm.js](https://xtermjs.org/)
- [Cortex XDR UI Patterns](internal) - Reference for component alignment
