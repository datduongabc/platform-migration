import { CommonModule } from '@angular/common';
import { Component, computed, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Subject, Subscription } from 'rxjs';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';
import { UserResponse } from '../../../api/models';
import { UserManagementService } from '../../../api/services/user-management.service';

@Component({
  selector: 'app-user-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './user-list.html',
})
export class UserListComponent implements OnInit, OnDestroy {
  private readonly userService = inject(UserManagementService);

  users = signal<UserResponse[]>([]);
  loading = signal(false);
  error = signal<string | null>(null);

  searchQuery = '';
  private readonly searchSubject = new Subject<string>();
  private searchSubscription?: Subscription;

  roleFilter = signal<'all' | 'user' | 'admin'>('all');

  skip = signal(0);
  limit = signal(10);

  currentPage = computed(() => Math.floor(this.skip() / this.limit()) + 1);

  ngOnInit(): void {
    this.searchSubscription = this.searchSubject
      .pipe(debounceTime(300), distinctUntilChanged())
      .subscribe(() => {
        this.skip.set(0);
        this.loadUsers();
      });
    this.loadUsers();
  }

  ngOnDestroy(): void {
    this.searchSubscription?.unsubscribe();
  }

  onSearch(): void {
    this.searchSubject.next(this.searchQuery);
  }

  loadUsers(): void {
    this.loading.set(true);
    this.error.set(null);

    const roleParam = this.roleFilter() === 'all' ? undefined : this.roleFilter();

    this.userService
      .listUsersAdminUsersGet({
        skip: this.skip(),
        limit: this.limit(),
        role: roleParam,
        search: this.searchQuery.trim() || undefined,
      })
      .subscribe({
        next: (data) => {
          this.users.set(data);
          this.loading.set(false);
        },
        error: (err) => {
          this.loading.set(false);
          this.error.set(err.error?.detail || 'Failed to load users.');
        },
      });
  }

  setRoleFilter(role: 'all' | 'user' | 'admin'): void {
    this.roleFilter.set(role);
    this.skip.set(0);
    this.loadUsers();
  }

  prevPage(): void {
    if (this.skip() > 0) {
      this.skip.update((s) => Math.max(0, s - this.limit()));
      this.loadUsers();
    }
  }

  nextPage(): void {
    this.skip.update((s) => s + this.limit());
    this.loadUsers();
  }
}
