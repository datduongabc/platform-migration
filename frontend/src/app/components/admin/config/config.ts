import { ChangeDetectionStrategy, ChangeDetectorRef, Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { AdminService } from '../../../services/admin.service';

@Component({
  selector: 'app-config',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 class="text-2xl font-bold text-slate-900 dark:text-white">System Config & AI Generation Control</h1>
        <p class="text-slate-500 dark:text-slate-400 text-sm mt-1">Configure global feature flags and AI model allow-lists</p>
      </div>

      <!-- AI Generation Model Control Card -->
      <div class="bg-white dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700 shadow-sm space-y-4">
        <h2 class="text-lg font-semibold text-slate-900 dark:text-white">System Default Model</h2>
        <div class="flex items-center gap-4">
          <div class="flex-1">
            <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">Provider</label>
            <input type="text" [(ngModel)]="defaultProvider" class="w-full text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white" />
          </div>
          <div class="flex-1">
            <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">Model ID</label>
            <input type="text" [(ngModel)]="defaultModel" class="w-full text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white" />
          </div>
          <div class="flex items-end">
            <button (click)="saveSystemDefault()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-lg text-sm transition">
              Save Default
            </button>
          </div>
        </div>
      </div>

      <!-- System Key-Value App Configs -->
      <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm p-6 space-y-4">
        <h2 class="text-lg font-semibold text-slate-900 dark:text-white">Application Feature Flags</h2>
        <div class="divide-y divide-slate-200 dark:divide-slate-700">
          <div *ngFor="let cfg of appConfigs()" class="py-3 flex items-center justify-between">
            <div>
              <div class="font-mono text-sm font-semibold text-slate-900 dark:text-white">{{ cfg.key }}</div>
              <div class="text-xs text-slate-500">{{ cfg.description }}</div>
            </div>
            <div class="font-mono text-xs text-indigo-600 dark:text-indigo-400 bg-slate-100 dark:bg-slate-900 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700">
              {{ cfg.value | json }}
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
})
export class ConfigComponent implements OnInit {
  private readonly adminService = inject(AdminService);
  private readonly cdr = inject(ChangeDetectorRef);

  readonly appConfigs = signal<any[]>([]);
  defaultProvider = 'gemini';
  defaultModel = 'gemini-2.5-flash';

  ngOnInit(): void {
    this.loadConfigs();
  }

  loadConfigs(): void {
    this.adminService.getAppConfig().subscribe({
      next: (res) => this.appConfigs.set(res.configs),
      error: (err) => console.error(err),
    });

    // defaultProvider/defaultModel are plain fields (two-way ngModel-bound) with
    // no signal write alongside them here — under OnPush this response wouldn't
    // otherwise mark the view dirty, so the loaded system default would never
    // appear in the form.
    this.adminService.getGenerationConfig().subscribe({
      next: (res) => {
        if (res.systemDefault) {
          this.defaultProvider = res.systemDefault.provider;
          this.defaultModel = res.systemDefault.model;
          this.cdr.markForCheck();
        }
      },
      error: (err) => console.error(err),
    });
  }

  saveSystemDefault(): void {
    this.adminService
      .updateGenerationConfig({
        systemDefault: { provider: this.defaultProvider, model: this.defaultModel },
      })
      .subscribe({
        next: () => alert('System default AI model updated successfully.'),
        error: (err) => alert(err.error?.detail || 'Failed to update system default.'),
      });
  }
}
