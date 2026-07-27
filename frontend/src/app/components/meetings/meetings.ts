import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import { ProjectsByUserService } from '../../api/services/projects-by-user.service';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-meetings',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './meetings.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MeetingsComponent {
  protected readonly authService = inject(AuthService);
  private readonly projectService = inject(ProjectsByUserService);
  private readonly router = inject(Router);

  // Pagination signals
  skip = signal(0);
  limit = signal(10);

  // Computed parameters for request
  requestParams = computed(() => ({
    skip: this.skip(),
    limit: this.limit(),
  }));

  // Resource for managing asynchronous data fetching
  meetingsResource = rxResource({
    params: () => this.requestParams(),
    stream: ({ params }) => this.projectService.listUserProjectsProjectsGet(params),
  });

  // Derived signals to match legacy variables bound to template
  projects = computed(() => this.meetingsResource.value() || []);
  loading = computed(() => this.meetingsResource.isLoading());
  error = computed(() => {
    const err: any = this.meetingsResource.error();
    if (!err) return null;
    return err.error?.detail || 'Failed to load meetings.';
  });

  currentPage = computed(() => Math.floor(this.skip() / this.limit()) + 1);

  loadProjects(): void {
    this.meetingsResource.reload();
  }

  formatDuration(seconds: number | null | undefined): string {
    if (seconds == null) return '00:00';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }

  prevPage(): void {
    if (this.skip() > 0) {
      this.skip.update((s) => Math.max(0, s - this.limit()));
    }
  }

  nextPage(): void {
    this.skip.update((s) => s + this.limit());
  }

  handleLogout(): void {
    this.authService.logout().subscribe(() => {
      this.router.navigate(['/login']);
    });
  }
}
