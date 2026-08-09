import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { AdminService } from '../../../services/admin.service';

@Component({
  selector: 'app-activity',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, DatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 class="text-2xl font-bold text-slate-900 dark:text-white">User Activity Logs</h1>
        <p class="text-slate-500 dark:text-slate-400 text-sm mt-1">High-volume user action telemetry stream</p>
      </div>

      <!-- Filters -->
      <div class="flex items-center gap-4 bg-white dark:bg-slate-800 p-4 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm">
        <input type="text" [(ngModel)]="eventTypeFilter" (keyup.enter)="loadActivities()" placeholder="Filter event (e.g. login, meeting_created)" class="text-sm px-3 py-2 border rounded-lg border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-white flex-1" />
        <button (click)="loadActivities()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition">
          Filter
        </button>
      </div>

      <!-- Activity Logs Table -->
      <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm">
        <table class="w-full text-left text-sm">
          <thead class="bg-slate-50 dark:bg-slate-900 text-slate-500 font-semibold border-b border-slate-200 dark:border-slate-700">
            <tr>
              <th class="p-4">Timestamp</th>
              <th class="p-4">User</th>
              <th class="p-4">Event Type</th>
              <th class="p-4">Meeting Title</th>
              <th class="p-4">Metadata</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-200 dark:divide-slate-700">
            <tr *ngFor="let act of activities()" class="hover:bg-slate-50/50 dark:hover:bg-slate-700/30">
              <td class="p-4 text-xs text-slate-500 whitespace-nowrap">{{ act.created_at | date:'medium' }}</td>
              <td class="p-4 font-medium text-slate-900 dark:text-white">{{ act.user_email || act.user_id }}</td>
              <td class="p-4">
                <span class="bg-indigo-50 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300 text-xs px-2.5 py-1 rounded-md font-mono font-semibold">
                  {{ act.event_type }}
                </span>
              </td>
              <td class="p-4 text-slate-600 dark:text-slate-300 font-medium">{{ act.meeting_title || '—' }}</td>
              <td class="p-4 font-mono text-xs text-slate-500 max-w-xs truncate">{{ act.metadata | json }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
})
export class ActivityComponent implements OnInit {
  private readonly adminService = inject(AdminService);

  readonly activities = signal<any[]>([]);
  eventTypeFilter = '';

  ngOnInit(): void {
    this.loadActivities();
  }

  loadActivities(): void {
    this.adminService.getActivityLogs(undefined, this.eventTypeFilter || undefined).subscribe({
      next: (res) => this.activities.set(res.rows),
      error: (err) => console.error(err),
    });
  }
}
