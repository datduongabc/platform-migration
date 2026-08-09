import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AdminService, KeyResponse, HealthProbeInfo } from '../../../services/admin.service';

@Component({
  selector: 'app-admin-keys',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './keys.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class KeysComponent implements OnInit {
  private readonly adminService = inject(AdminService);

  // States
  readonly keys = signal<KeyResponse[]>([]);
  readonly loading = signal<boolean>(false);
  readonly error = signal<string | null>(null);

  // Form states
  readonly addBusy = signal<boolean>(false);
  readonly addError = signal<string | null>(null);
  configKey = 'gemini_api_key';
  label = '';
  key = '';

  // Health check status mapping
  readonly healthBusy = signal<boolean>(false);
  readonly healthReport = signal<any | null>(null);
  healthMap: Record<string, HealthProbeInfo> = {};

  ngOnInit(): void {
    this.loadKeys();
  }

  loadKeys(): void {
    this.loading.set(true);
    this.error.set(null);
    this.adminService.getKeys().subscribe({
      next: (res) => {
        this.keys.set(res.keys);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err.error?.detail || 'Failed to load key pool.');
        this.loading.set(false);
      }
    });
  }

  addKey(): void {
    const ck = this.configKey;
    const lbl = this.label.trim();
    const secret = this.key.trim();

    if (!ck || !lbl || !secret) return;

    this.addBusy.set(true);
    this.addError.set(null);

    this.adminService.addKey({ configKey: ck, label: lbl, key: secret }).subscribe({
      next: () => {
        this.label = '';
        this.key = '';
        this.addBusy.set(false);
        this.loadKeys();
      },
      error: (err) => {
        this.addError.set(err.error?.detail || 'Failed to save new key.');
        this.addBusy.set(false);
      }
    });
  }

  toggleKey(k: KeyResponse): void {
    const targetStatus = k.status === 'active' ? 'disabled' : 'active';
    let reason: string | null = null;
    
    if (targetStatus === 'disabled') {
      reason = prompt('Enter a reason for disabling this key (optional):') || '';
    }

    this.adminService.updateKey(k.id, { status: targetStatus, disabled_reason: reason }).subscribe({
      next: () => this.loadKeys(),
      error: (err) => alert(err.error?.detail || 'Failed to update key status.')
    });
  }

  deleteKey(id: string): void {
    if (confirm('Are you sure you want to permanently delete this key? This operation is irreversible.')) {
      this.adminService.deleteKey(id).subscribe({
        next: () => this.loadKeys(),
        error: (err) => alert(err.error?.detail || 'Failed to delete key.')
      });
    }
  }

  triggerHealthcheck(): void {
    this.healthBusy.set(true);
    this.healthReport.set(null);
    this.healthMap = {};

    this.adminService.runHealthcheck().subscribe({
      next: (res) => {
        this.healthReport.set(res);
        for (const item of res.keys) {
          this.healthMap[item.id] = item;
        }
        this.healthBusy.set(false);
      },
      error: (err) => {
        alert(err.error?.detail || 'Health check run failed.');
        this.healthBusy.set(false);
      }
    });
  }

  getProviderLabel(key: string): string {
    const map: Record<string, string> = {
      gemini_api_key: 'Google Gemini',
      speechmatics_api_key: 'Speechmatics ASR',
    };
    return map[key] || key;
  }
}
