import { CommonModule } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { UserResponse } from '../../../api/models';
import { UserManagementService } from '../../../api/services/user-management.service';

@Component({
  selector: 'app-user-detail',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './user-detail.html',
})
export class UserDetailComponent implements OnInit {
  private readonly userService = inject(UserManagementService);
  private readonly route = inject(ActivatedRoute);

  user = signal<UserResponse | null>(null);
  loading = signal(false);
  error = signal<string | null>(null);

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.loadUserDetail(id);
    } else {
      this.error.set('No user ID found in route.');
    }
  }

  loadUserDetail(id: string): void {
    this.loading.set(true);
    this.error.set(null);

    this.userService.getUserDetailAdminUsersIdGet({ id }).subscribe({
      next: (data) => {
        this.user.set(data);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(err.error?.detail || 'Failed to load user details.');
      },
    });
  }
}
