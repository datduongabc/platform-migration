import { CommonModule } from '@angular/common';
import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { ProjectResponse } from '../../api/models';
import { ProjectsByUserService } from '../../api/services/projects-by-user.service';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-meetings',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './meetings.html',
})
export class MeetingsComponent implements OnInit {
  protected readonly authService = inject(AuthService);
  private readonly projectService = inject(ProjectsByUserService);
  private readonly router = inject(Router);

  projects = signal<ProjectResponse[]>([]);
  loading = signal(false);
  error = signal<string | null>(null);

  skip = signal(0);
  limit = signal(10);

  currentPage = computed(() => Math.floor(this.skip() / this.limit()) + 1);

  ngOnInit(): void {
    this.loadProjects();
  }

  loadProjects(): void {
    this.loading.set(true);
    this.error.set(null);

    this.projectService
      .listUserProjectsProjectsGet({
        skip: this.skip(),
        limit: this.limit(),
      })
      .subscribe({
        next: (data) => {
          this.projects.set(data);
          this.loading.set(false);
        },
        error: (err) => {
          this.loading.set(false);
          this.error.set(err.error?.detail || 'Failed to load meetings.');
        },
      });
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
      this.loadProjects();
    }
  }

  nextPage(): void {
    this.skip.update((s) => s + this.limit());
    this.loadProjects();
  }

  handleLogout(): void {
    this.authService.logout().subscribe(() => {
      this.router.navigate(['/login']);
    });
  }
}
