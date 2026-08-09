import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { rxResource, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { of } from 'rxjs';
import { UserManagementService } from '../../../api/services/user-management.service';
import { AdminService } from '../../../services/admin.service';
import { AuthService } from '../../../services/auth.service';

@Component({
  selector: 'app-user-detail',
  standalone: true,
  imports: [DatePipe, RouterLink],
  templateUrl: './user-detail.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UserDetailComponent {
  private readonly userService = inject(UserManagementService);
  private readonly adminService = inject(AdminService);
  private readonly authService = inject(AuthService);
  private readonly route = inject(ActivatedRoute);

  // Convert route paramMap observable to a reactive signal
  private readonly paramMap = toSignal(this.route.paramMap);

  readonly actionBusy = signal(false);
  readonly actionError = signal<string | null>(null);
  readonly tempPassword = signal<string | null>(null);

  // rxResource uses params and stream options for RxJS Observable services
  userDetailResource = rxResource({
    params: () => this.paramMap()?.get('id'),
    stream: ({ params: id }) => {
      if (!id) {
        return of(null);
      }
      return this.userService.getUserDetailAdminUsersIdGet({ id });
    },
  });

  // Derived signals for template bindings
  user = computed(() => this.userDetailResource.value() || null);
  loading = computed(() => this.userDetailResource.isLoading());
  error = computed(() => {
    const err: any = this.userDetailResource.error();
    if (!err) return null;
    return err.error?.detail || 'Failed to load user details.';
  });

  isSelf = computed(() => {
    const u = this.user();
    const me = this.authService.currentUser();
    return !!u && !!me && u.id === (me as any).id;
  });

  private handleAction(obs: any, onSuccess?: () => void): void {
    this.actionBusy.set(true);
    this.actionError.set(null);
    obs.subscribe({
      next: () => {
        this.actionBusy.set(false);
        onSuccess?.();
        this.userDetailResource.reload();
      },
      error: (err: any) => {
        this.actionBusy.set(false);
        this.actionError.set(err.error?.detail || 'Action failed.');
      },
    });
  }

  toggleRole(): void {
    const u = this.user();
    if (!u?.profile) return;
    const newRole = u.profile.role === 'admin' ? 'user' : 'admin';
    if (!confirm(`Change this user's role to "${newRole}"?`)) return;
    this.handleAction(this.adminService.updateUserRole(u.id, newRole));
  }

  toggleStatus(): void {
    const u = this.user();
    if (!u) return;
    const disable = !u.disabled_at;
    if (
      !confirm(disable ? 'Disable this account? They will be signed out immediately.' : 'Re-enable this account?')
    )
      return;
    this.handleAction(this.adminService.updateUserStatus(u.id, disable));
  }

  resetPassword(): void {
    const u = this.user();
    if (!u) return;
    if (!confirm('Generate a new temporary password for this user?')) return;
    this.tempPassword.set(null);
    this.actionBusy.set(true);
    this.actionError.set(null);
    this.adminService.resetUserPassword(u.id).subscribe({
      next: (res) => {
        this.actionBusy.set(false);
        this.tempPassword.set(res.temporaryPassword);
      },
      error: (err) => {
        this.actionBusy.set(false);
        this.actionError.set(err.error?.detail || 'Reset failed.');
      },
    });
  }

  deleteUser(): void {
    const u = this.user();
    if (!u) return;
    if (!confirm('Permanently delete this user and all their meetings? This cannot be undone.')) return;
    this.actionBusy.set(true);
    this.actionError.set(null);
    this.adminService.deleteUser(u.id).subscribe({
      next: () => {
        window.location.href = '/admin/users';
      },
      error: (err) => {
        this.actionBusy.set(false);
        this.actionError.set(err.error?.detail || 'Delete failed.');
      },
    });
  }
}
