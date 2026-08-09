import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { AdminService } from '../../../services/admin.service';

@Component({
  selector: 'app-audit-logs',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 class="text-2xl font-bold text-slate-900 dark:text-white">Admin Audit Logs</h1>
        <p class="text-slate-500 dark:text-slate-400 text-sm mt-1">Immutable record of sensitive administrative actions</p>
      </div>

      <!-- Filters -->
      <div class="flex items-center gap-4 bg-white dark:bg-slate-800 p-4 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm">
        <input type="text" [(ngModel)]="actionFilter" (keyup.enter)="loadLogs()" placeholder="Filter by action (e.g. user.role_change)" class="text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white flex-1" />
        <input type="text" [(ngModel)]="targetTypeFilter" (keyup.enter)="loadLogs()" placeholder="Filter by target type (e.g. user, meeting)" class="text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white flex-1" />
        <button (click)="loadLogs()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition">
          Filter
        </button>
      </div>

      <!-- Audit Logs Table -->
      <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm">
        <table class="w-full text-left text-sm">
          <thead class="bg-slate-50 dark:bg-slate-900 text-slate-500 font-semibold border-b border-slate-200 dark:border-slate-700">
            <tr>
              <th class="p-4">Timestamp</th>
              <th class="p-4">Actor</th>
              <th class="p-4">Action</th>
              <th class="p-4">Target Type</th>
              <th class="p-4">Target ID</th>
              <th class="p-4">Metadata</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-200 dark:divide-slate-700">
            <tr *ngFor="let log of logs()" class="hover:bg-slate-50/50 dark:hover:bg-slate-700/30">
              <td class="p-4 text-xs text-slate-500 whitespace-nowrap">{{ log.created_at | date:'medium' }}</td>
              <td class="p-4 font-medium text-slate-900 dark:text-white">{{ log.actor_email }}</td>
              <td class="p-4 font-mono text-xs text-indigo-600 dark:text-indigo-400 font-semibold">{{ log.action }}</td>
              <td class="p-4 text-slate-600 dark:text-slate-300 text-xs uppercase">{{ log.target_type }}</td>
              <td class="p-4 text-slate-500 font-mono text-xs">{{ log.target_id }}</td>
              <td class="p-4 font-mono text-xs text-slate-500 max-w-xs truncate">{{ log.metadata | json }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
})
export class AuditLogsComponent implements OnInit {
  private readonly adminService = inject(AdminService);

  readonly logs = signal<any[]>([]);
  actionFilter = '';
  targetTypeFilter = '';

  ngOnInit(): void {
    this.loadLogs();
  }

  loadLogs(): void {
    this.adminService
      .getAuditLogs(this.actionFilter || undefined, this.targetTypeFilter || undefined)
      .subscribe({
        next: (res) => this.logs.set(res.rows),
        error: (err) => console.error(err),
      });
  }
}
