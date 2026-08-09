import { ChangeDetectionStrategy, ChangeDetectorRef, Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AdminService, PipelineOverview, PipelineJob } from '../../../services/admin.service';

@Component({
  selector: 'app-admin-pipeline',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './pipeline.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PipelineComponent implements OnInit {
  private readonly adminService = inject(AdminService);
  private readonly cdr = inject(ChangeDetectorRef);

  // Stats & jobs state
  readonly overview = signal<PipelineOverview | null>(null);
  readonly jobs = signal<PipelineJob[]>([]);
  readonly loading = signal<boolean>(false);
  readonly error = signal<string | null>(null);

  // Filters & paging
  statusFilter = signal<string>('all');
  page = signal<number>(1);
  perPage = signal<number>(20);
  total = signal<number>(0);

  // Requeue busy mapping
  requeueBusy: Record<string, boolean> = {};

  ngOnInit(): void {
    this.loadOverview();
    this.loadJobs();
  }

  loadOverview(): void {
    this.adminService.getPipelineOverview().subscribe({
      next: (res) => this.overview.set(res),
      error: () => console.warn('Failed to load pipeline overview statistics.')
    });
  }

  loadJobs(): void {
    this.loading.set(true);
    this.error.set(null);

    this.adminService.getPipelineJobs(this.statusFilter(), this.page(), this.perPage()).subscribe({
      next: (res) => {
        this.jobs.set(res.jobs);
        this.total.set(res.total);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err.error?.detail || 'Failed to load pipeline jobs.');
        this.loading.set(false);
      }
    });
  }

  setFilter(status: string): void {
    this.statusFilter.set(status);
    this.page.set(1);
    this.loadJobs();
  }

  prevPage(): void {
    if (this.page() > 1) {
      this.page.update((p) => p - 1);
      this.loadJobs();
    }
  }

  nextPage(): void {
    if (this.page() * this.perPage() < this.total()) {
      this.page.update((p) => p + 1);
      this.loadJobs();
    }
  }

  requeue(jobId: string): void {
    if (this.requeueBusy[jobId]) return;
    
    if (confirm('Are you sure you want to requeue this meeting? All prior generated transcripts, chunks, todos and calendar suggestions will be cleared and regenerated.')) {
      this.requeueBusy[jobId] = true;
      // requeueBusy is a plain (non-signal) map. loadOverview()/loadJobs() below
      // fire new requests but don't resolve synchronously in this callback, so
      // under OnPush the busy-flag flip here needs an explicit markForCheck to
      // show immediately rather than waiting on those separate responses to land.
      this.adminService.requeueJob(jobId).subscribe({
        next: () => {
          this.requeueBusy[jobId] = false;
          this.cdr.markForCheck();
          this.loadOverview();
          this.loadJobs();
        },
        error: (err) => {
          alert(err.error?.detail || 'Failed to requeue job.');
          this.requeueBusy[jobId] = false;
          this.cdr.markForCheck();
        }
      });
    }
  }

  formatDuration(seconds: number | null): string {
    if (!seconds) return '--:--';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) {
      return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m}:${s.toString().padStart(2, '0')}`;
  }
}
