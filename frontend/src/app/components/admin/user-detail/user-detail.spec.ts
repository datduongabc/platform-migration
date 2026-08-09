import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { ProfileResponse } from '../../../api/models/profile-response';
import { UserResponse } from '../../../api/models/user-response';
import { UserManagementService } from '../../../api/services/user-management.service';
import { AdminService } from '../../../services/admin.service';
import { AuthService, User } from '../../../services/auth.service';
import { UserDetailComponent } from './user-detail';

function makeUser(overrides: Partial<UserResponse> = {}): UserResponse {
  const profile: ProfileResponse = {
    id: 'target-1',
    username: 'target_user',
    role: 'user',
    created_at: '2026-07-27T00:00:00Z',
  };
  return {
    id: 'target-1',
    email: 'target@example.com',
    created_at: '2026-07-27T00:00:00Z',
    disabled_at: null,
    profile,
    ...overrides,
  };
}

describe('UserDetailComponent', () => {
  let component: UserDetailComponent;
  let httpMock: HttpTestingController;
  let adminService: {
    updateUserRole: ReturnType<typeof vi.fn>;
    updateUserStatus: ReturnType<typeof vi.fn>;
    resetUserPassword: ReturnType<typeof vi.fn>;
    deleteUser: ReturnType<typeof vi.fn>;
  };
  let userManagementService: { getUserDetailAdminUsersIdGet: ReturnType<typeof vi.fn> };
  let authService: { currentUser: ReturnType<typeof vi.fn> };
  let currentUser: User | null;

  function setup(loadedUser: UserResponse) {
    currentUser = { id: 'admin-1', email: 'admin@example.com', username: 'admin_user', role: 'admin' };

    adminService = {
      updateUserRole: vi.fn().mockReturnValue(of({})),
      updateUserStatus: vi.fn().mockReturnValue(of({})),
      resetUserPassword: vi.fn().mockReturnValue(of({ temporaryPassword: 'temp-pass-12345' })),
      deleteUser: vi.fn().mockReturnValue(of({ ok: true, storageWarning: null })),
    };
    userManagementService = {
      getUserDetailAdminUsersIdGet: vi.fn().mockReturnValue(of(loadedUser)),
    };
    authService = { currentUser: vi.fn(() => currentUser) };

    TestBed.configureTestingModule({
      imports: [UserDetailComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AdminService, useValue: adminService },
        { provide: UserManagementService, useValue: userManagementService },
        { provide: AuthService, useValue: authService },
        {
          provide: ActivatedRoute,
          useValue: { paramMap: of(convertToParamMap({ id: loadedUser.id })) },
        },
      ],
    });

    const fixture = TestBed.createComponent(UserDetailComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('should create and load the target user', () => {
    setup(makeUser());
    expect(component).toBeTruthy();
    expect(component.user()?.id).toBe('target-1');
  });

  it('isSelf is false when the loaded user differs from the current admin', () => {
    setup(makeUser());
    expect(component.isSelf()).toBe(false);
  });

  it('isSelf is true when the loaded user is the current admin', () => {
    setup(makeUser({ id: 'admin-1' }));
    expect(component.isSelf()).toBe(true);
  });

  it('toggleRole does nothing when the confirm dialog is dismissed', () => {
    setup(makeUser());
    vi.spyOn(window, 'confirm').mockReturnValue(false);

    component.toggleRole();

    expect(adminService.updateUserRole).not.toHaveBeenCalled();
  });

  it('toggleRole promotes a regular user to admin after confirmation', () => {
    setup(makeUser({ profile: { id: 'target-1', username: 'target_user', role: 'user', created_at: '2026-07-27T00:00:00Z' } }));
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    component.toggleRole();

    expect(adminService.updateUserRole).toHaveBeenCalledWith('target-1', 'admin');
  });

  it('toggleStatus disables an active account after confirmation', () => {
    setup(makeUser({ disabled_at: null }));
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    component.toggleStatus();

    expect(adminService.updateUserStatus).toHaveBeenCalledWith('target-1', true);
  });

  it('toggleStatus re-enables a disabled account after confirmation', () => {
    setup(makeUser({ disabled_at: '2026-08-01T00:00:00Z' }));
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    component.toggleStatus();

    expect(adminService.updateUserStatus).toHaveBeenCalledWith('target-1', false);
  });

  it('resetPassword surfaces the temporary password from the response', () => {
    setup(makeUser());
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    component.resetPassword();

    expect(adminService.resetUserPassword).toHaveBeenCalledWith('target-1');
    expect(component.tempPassword()).toBe('temp-pass-12345');
  });

  it('resetPassword does nothing when the confirm dialog is dismissed', () => {
    setup(makeUser());
    vi.spyOn(window, 'confirm').mockReturnValue(false);

    component.resetPassword();

    expect(adminService.resetUserPassword).not.toHaveBeenCalled();
  });

  it('deleteUser does nothing when the confirm dialog is dismissed', () => {
    setup(makeUser());
    vi.spyOn(window, 'confirm').mockReturnValue(false);

    component.deleteUser();

    expect(adminService.deleteUser).not.toHaveBeenCalled();
  });

  it('deleteUser calls the delete endpoint after confirmation', () => {
    setup(makeUser());
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    // deleteUser navigates via window.location.href on success; jsdom doesn't
    // implement navigation, so stub it out to keep this test focused on the
    // guard/service-call behavior rather than browser navigation.
    const originalLocation = window.location;
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, href: '' },
    });

    component.deleteUser();

    expect(adminService.deleteUser).toHaveBeenCalledWith('target-1');
    Object.defineProperty(window, 'location', { configurable: true, value: originalLocation });
  });

  it('surfaces an error message when an action fails', () => {
    setup(makeUser());
    adminService.updateUserRole.mockReturnValue({
      subscribe: ({ error }: any) => error({ error: { detail: 'last remaining admin' } }),
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    component.toggleRole();

    expect(component.actionError()).toBe('last remaining admin');
    expect(component.actionBusy()).toBe(false);
  });
});
