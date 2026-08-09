import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { AdminService } from '../../../services/admin.service';

@Component({
  selector: 'app-features',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 class="text-2xl font-bold text-slate-900 dark:text-white">Feature Registry Tracker</h1>
        <p class="text-slate-500 dark:text-slate-400 text-sm mt-1">Database-backed source of truth for app features and modules</p>
      </div>

      <!-- Feature Split Pane -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Feature List Sidebar -->
        <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm p-4 space-y-3">
          <input type="text" [(ngModel)]="searchQuery" (input)="loadFeatures()" placeholder="Search key or title..." class="w-full text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white" />

          <div class="divide-y divide-slate-200 dark:divide-slate-700 max-h-[600px] overflow-y-auto pr-1">
            <div *ngFor="let feat of features()" (click)="selectFeature(feat)" [class.bg-indigo-50]="selectedFeature()?.id === feat.id" [class.dark:bg-indigo-900/30]="selectedFeature()?.id === feat.id" class="py-3 px-2 rounded-lg cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-700/50 transition flex items-center justify-between">
              <div>
                <div class="font-mono text-xs font-bold text-indigo-600 dark:text-indigo-400">{{ feat.key }}</div>
                <div class="text-sm font-semibold text-slate-900 dark:text-white line-clamp-1">{{ feat.title }}</div>
              </div>
              <span [class]="getStatusClass(feat.status)" class="text-xs px-2 py-0.5 rounded-full font-medium uppercase">
                {{ feat.status }}
              </span>
            </div>
          </div>
        </div>

        <!-- Selected Feature Detail & Editor -->
        <div class="lg:col-span-2 bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6 shadow-sm space-y-4" *ngIf="selectedFeature() as feat">
          <div class="flex items-center justify-between border-b border-slate-200 dark:border-slate-700 pb-4">
            <div>
              <span class="font-mono text-xs font-bold text-indigo-600 dark:text-indigo-400">{{ feat.key }} ({{ feat.module_name }})</span>
              <h2 class="text-xl font-bold text-slate-900 dark:text-white">{{ feat.title }}</h2>
            </div>
            <button (click)="saveFeature()" [disabled]="busy()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-sm rounded-lg transition">
              Save Feature
            </button>
          </div>

          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">Status</label>
              <select [(ngModel)]="feat.status" class="w-full text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white">
                <option value="done">Done</option>
                <option value="partial">Partial</option>
                <option value="not_started">Not Started</option>
              </select>
            </div>
            <div>
              <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">Priority</label>
              <select [(ngModel)]="feat.priority" class="w-full text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white">
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
          </div>

          <div>
            <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">Description</label>
            <input type="text" [(ngModel)]="feat.description" class="w-full text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white" />
          </div>

          <div>
            <label class="block text-xs font-semibold text-slate-500 uppercase mb-1">Markdown Body Content</label>
            <textarea [(ngModel)]="feat.content" rows="10" class="w-full text-sm p-3 font-mono border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white leading-relaxed"></textarea>
          </div>
        </div>
      </div>
    </div>
  `,
})
export class FeaturesComponent implements OnInit {
  private readonly adminService = inject(AdminService);

  readonly features = signal<any[]>([]);
  readonly selectedFeature = signal<any | null>(null);
  readonly busy = signal<boolean>(false);
  searchQuery = '';

  ngOnInit(): void {
    this.loadFeatures();
  }

  loadFeatures(): void {
    this.adminService.getFeatures(undefined, undefined, this.searchQuery || undefined).subscribe({
      next: (res) => {
        this.features.set(res.features);
        if (res.features.length > 0 && !this.selectedFeature()) {
          this.selectedFeature.set(res.features[0]);
        }
      },
      error: (err) => console.error(err),
    });
  }

  selectFeature(feat: any): void {
    this.selectedFeature.set(feat);
  }

  getStatusClass(status: string): string {
    if (status === 'done') return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300';
    if (status === 'partial') return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
    return 'bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-300';
  }

  saveFeature(): void {
    const feat = this.selectedFeature();
    if (!feat) return;

    this.busy.set(true);
    this.adminService
      .updateFeature(feat.id, {
        title: feat.title,
        description: feat.description,
        content: feat.content,
        status: feat.status,
        priority: feat.priority,
      })
      .subscribe({
        next: () => {
          this.busy.set(false);
          alert('Feature updated successfully.');
          this.loadFeatures();
        },
        error: (err) => {
          alert(err.error?.detail || 'Failed to update feature.');
          this.busy.set(false);
        },
      });
  }
}
