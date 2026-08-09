import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { AdminService } from '../../../services/admin.service';

@Component({
  selector: 'app-storage',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-2xl font-bold text-slate-900 dark:text-white">Object Storage Configuration</h1>
          <p class="text-slate-5800 dark:text-slate-400 text-sm mt-1">Manage Cloudflare R2 / S3 storage credentials securely</p>
        </div>
      </div>

      <!-- Add Storage Config Card -->
      <div class="bg-white dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700 shadow-sm space-y-4">
        <h2 class="text-lg font-semibold text-slate-900 dark:text-white">Add Storage Credential</h2>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">Label</label>
            <input type="text" [(ngModel)]="newLabel" placeholder="e.g. Primary R2 Bucket" class="w-full text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white" />
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">Provider</label>
            <select [(ngModel)]="newProvider" class="w-full text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white">
              <option value="r2">Cloudflare R2</option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">Account ID</label>
            <input type="text" [(ngModel)]="newAccountId" placeholder="Cloudflare Account ID" class="w-full text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white" />
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">Access Key ID</label>
            <input type="text" [(ngModel)]="newAccessKeyId" placeholder="R2 Access Key ID" class="w-full text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white" />
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">Secret Access Key</label>
            <input type="password" [(ngModel)]="newSecretAccessKey" placeholder="Write-only encrypted secret" class="w-full text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white" />
          </div>
          <div>
            <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">Bucket Name</label>
            <input type="text" [(ngModel)]="newBucket" placeholder="e.g. recordings" class="w-full text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white" />
          </div>
        </div>
        <button (click)="addConfig()" [disabled]="busy()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-lg text-sm transition">
          Save Credentials
        </button>
      </div>

      <!-- Storage Configs Table -->
      <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm">
        <table class="w-full text-left text-sm">
          <thead class="bg-slate-50 dark:bg-slate-900 text-slate-500 font-semibold border-b border-slate-200 dark:border-slate-700">
            <tr>
              <th class="p-4">Label</th>
              <th class="p-4">Provider</th>
              <th class="p-4">Bucket</th>
              <th class="p-4">Access Key ID</th>
              <th class="p-4">Secret</th>
              <th class="p-4">Status</th>
              <th class="p-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-200 dark:divide-slate-700">
            <tr *ngFor="let cfg of configs()" class="hover:bg-slate-50/50 dark:hover:bg-slate-700/30">
              <td class="p-4 font-medium text-slate-900 dark:text-white">{{ cfg.label }}</td>
              <td class="p-4 uppercase text-xs font-bold text-indigo-600 dark:text-indigo-400">{{ cfg.provider }}</td>
              <td class="p-4 text-slate-600 dark:text-slate-300">{{ cfg.bucket }}</td>
              <td class="p-4 text-slate-600 dark:text-slate-300 font-mono text-xs">{{ cfg.access_key_id }}</td>
              <td class="p-4 text-slate-400 font-mono text-xs">••••{{ cfg.secret_last4 }}</td>
              <td class="p-4">
                <span [class]="cfg.status === 'active' ? 'bg-emerald-100 text-emerald-800 text-xs px-2.5 py-0.5 rounded-full font-medium' : 'bg-rose-100 text-rose-800 text-xs px-2.5 py-0.5 rounded-full font-medium'">
                  {{ cfg.status }}
                </span>
              </td>
              <td class="p-4 text-right space-x-2">
                <button (click)="toggleStatus(cfg)" class="text-xs text-indigo-600 hover:underline">
                  {{ cfg.status === 'active' ? 'Disable' : 'Enable' }}
                </button>
                <button (click)="deleteConfig(cfg.id)" class="text-xs text-rose-600 hover:underline">
                  Delete
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
})
export class StorageComponent implements OnInit {
  private readonly adminService = inject(AdminService);

  readonly configs = signal<any[]>([]);
  readonly busy = signal<boolean>(false);

  newLabel = '';
  newProvider = 'r2';
  newAccountId = '';
  newAccessKeyId = '';
  newSecretAccessKey = '';
  newBucket = 'recordings';

  ngOnInit(): void {
    this.loadConfigs();
  }

  loadConfigs(): void {
    this.adminService.getStorageConfigs().subscribe({
      next: (res) => this.configs.set(res.storage_configs),
      error: (err) => console.error(err),
    });
  }

  addConfig(): void {
    if (!this.newLabel || !this.newAccountId || !this.newAccessKeyId || !this.newSecretAccessKey || !this.newBucket) {
      alert('Please fill out all storage credential fields.');
      return;
    }

    this.busy.set(true);
    this.adminService
      .createStorageConfig({
        label: this.newLabel,
        provider: this.newProvider,
        account_id: this.newAccountId,
        access_key_id: this.newAccessKeyId,
        secret_access_key: this.newSecretAccessKey,
        bucket: this.newBucket,
      })
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.newLabel = '';
          this.newSecretAccessKey = '';
          this.loadConfigs();
        },
        error: (err) => {
          alert(err.error?.detail || 'Failed to save storage configuration.');
          this.busy.set(false);
        },
      });
  }

  toggleStatus(cfg: any): void {
    const newStatus = cfg.status === 'active' ? 'disabled' : 'active';
    this.adminService.updateStorageConfig(cfg.id, { status: newStatus }).subscribe({
      next: () => this.loadConfigs(),
      error: (err) => alert(err.error?.detail || 'Failed to update status.'),
    });
  }

  deleteConfig(id: string): void {
    if (confirm('Are you sure you want to delete this storage configuration?')) {
      this.adminService.deleteStorageConfig(id).subscribe({
        next: () => this.loadConfigs(),
        error: (err) => alert(err.error?.detail || 'Failed to delete configuration.'),
      });
    }
  }
}
