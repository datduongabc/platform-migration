import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { rxResource, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { of } from 'rxjs';
import { UserManagementService } from '../../../api/services/user-management.service';

@Component({
  selector: 'app-user-detail',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './user-detail.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UserDetailComponent {
  private readonly userService = inject(UserManagementService);
  private readonly route = inject(ActivatedRoute);

  // Convert route paramMap observable to a reactive signal
  private readonly paramMap = toSignal(this.route.paramMap);

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
}
