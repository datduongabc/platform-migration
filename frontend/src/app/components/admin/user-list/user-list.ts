import { CommonModule } from '@angular/common';
import { Component, computed, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Subject, Subscription } from 'rxjs';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';
import { UserManagementService } from '../../../api/services/user-management.service';

@Component({
  selector: 'app-user-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './user-list.html',
})
export class UserListComponent implements OnInit, OnDestroy {
  private readonly userService = inject(UserManagementService);

  // Pagination and filter signals
  roleFilter = signal<'all' | 'user' | 'admin'>('all');
  skip = signal(0);
  limit = signal(10);

  // Search input and debounced search signal
  searchQuery = '';
  private readonly debouncedSearch = signal('');
  private readonly searchSubject = new Subject<string>();
  private searchSubscription?: Subscription;

  // Computed parameters for request
  requestParams = computed(() => ({
    skip: this.skip(),
    limit: this.limit(),
    role: this.roleFilter() === 'all' ? undefined : this.roleFilter(),
    search: this.debouncedSearch().trim() || undefined,
  }));

  // Resource for managing asynchronous data fetching
  usersResource = rxResource({
    params: () => this.requestParams(),
    stream: ({ params }) => this.userService.listUsersAdminUsersGet(params),
  });

  // Derived signals to match legacy variables bound to template
  users = computed(() => this.usersResource.value() || []);
  loading = computed(() => this.usersResource.isLoading());
  error = computed(() => {
    const err: any = this.usersResource.error();
    if (!err) return null;
    return err.error?.detail || 'Failed to load users.';
  });

  currentPage = computed(() => Math.floor(this.skip() / this.limit()) + 1);

  ngOnInit(): void {
    this.searchSubscription = this.searchSubject
      .pipe(debounceTime(300), distinctUntilChanged())
      .subscribe((val) => {
        this.debouncedSearch.set(val);
        this.skip.set(0);
      });
  }

  ngOnDestroy(): void {
    this.searchSubscription?.unsubscribe();
  }

  onSearch(): void {
    this.searchSubject.next(this.searchQuery);
  }

  setRoleFilter(role: 'all' | 'user' | 'admin'): void {
    this.roleFilter.set(role);
    this.skip.set(0);
  }

  prevPage(): void {
    if (this.skip() > 0) {
      this.skip.update((s) => Math.max(0, s - this.limit()));
    }
  }

  nextPage(): void {
    this.skip.update((s) => s + this.limit());
  }
}
