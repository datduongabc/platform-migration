import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { AdminService } from '../../../services/admin.service';

@Component({
  selector: 'app-usage',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 class="text-2xl font-bold text-slate-900 dark:text-white">AI Usage & Telemetry</h1>
        <p class="text-slate-500 dark:text-slate-400 text-sm mt-1">Metered API consumption breakdown for Gemini and Speechmatics</p>
      </div>

      <!-- Telemetry Rows Table -->
      <div class="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm">
        <table class="w-full text-left text-sm">
          <thead class="bg-slate-50 dark:bg-slate-900 text-slate-500 font-semibold border-b border-slate-200 dark:border-slate-700">
            <tr>
              <th class="p-4">Provider</th>
              <th class="p-4">Model</th>
              <th class="p-4">Unit</th>
              <th class="p-4">Total Calls</th>
              <th class="p-4">Input Tokens</th>
              <th class="p-4">Output Tokens</th>
              <th class="p-4">Audio Seconds</th>
              <th class="p-4">Rate-Limited</th>
              <th class="p-4">Errors</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-200 dark:divide-slate-700">
            <tr *ngFor="let row of usageRows()" class="hover:bg-slate-50/50 dark:hover:bg-slate-700/30">
              <td class="p-4 font-bold text-indigo-600 uppercase text-xs">{{ row.provider }}</td>
              <td class="p-4 font-medium text-slate-900 dark:text-white">{{ row.model }}</td>
              <td class="p-4 text-xs font-mono text-slate-500">{{ row.unit }}</td>
              <td class="p-4 font-semibold text-slate-900 dark:text-white">{{ row.calls }}</td>
              <td class="p-4 font-mono text-slate-600 dark:text-slate-300">{{ row.input_tokens || 0 }}</td>
              <td class="p-4 font-mono text-slate-600 dark:text-slate-300">{{ row.output_tokens || 0 }}</td>
              <td class="p-4 font-mono text-slate-600 dark:text-slate-300">{{ row.total_audio_seconds || 0 }}s</td>
              <td class="p-4 text-amber-600 font-bold text-xs">{{ row.rate_limited_count || 0 }}</td>
              <td class="p-4 text-rose-600 font-bold text-xs">{{ row.error_count || 0 }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
})
export class UsageComponent implements OnInit {
  private readonly adminService = inject(AdminService);

  readonly usageRows = signal<any[]>([]);

  ngOnInit(): void {
    this.adminService.getAiUsage().subscribe({
      next: (res) => this.usageRows.set(res.rows),
      error: (err) => console.error(err),
    });
  }
}
