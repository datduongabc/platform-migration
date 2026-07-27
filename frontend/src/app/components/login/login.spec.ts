import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { AuthService } from '../../services/auth.service';
import { LoginComponent } from './login';

describe('LoginComponent', () => {
  let component: LoginComponent;
  let fixture: ComponentFixture<LoginComponent>;
  let authServiceSpy: any;
  let routerSpy: any;

  beforeEach(async () => {
    authServiceSpy = {
      login: vi.fn(),
    };
    routerSpy = {
      navigate: vi.fn(),
    };

    await TestBed.configureTestingModule({
      imports: [LoginComponent],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: () => null } },
            queryParams: of({}),
          },
        },
        { provide: AuthService, useValue: authServiceSpy },
        { provide: Router, useValue: routerSpy },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(LoginComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should toggle password visibility', () => {
    expect(component['showPassword']()).toBe(false);
    component['togglePasswordVisibility']();
    expect(component['showPassword']()).toBe(true);
    component['togglePasswordVisibility']();
    expect(component['showPassword']()).toBe(false);
  });

  it('should show validation error if inputs are empty on submit', () => {
    component.identifier = '';
    component.password = '';

    component['handleSubmit']();

    expect(component['error']()).toBe('Email or username is required.');
    expect(authServiceSpy.login).not.toHaveBeenCalled();
  });

  it('should show validation error if password is too short', () => {
    component.identifier = 'user@example.com';
    component.password = '123';

    component['handleSubmit']();

    expect(component['error']()).toBe('Password must be at least 8 characters.');
    expect(authServiceSpy.login).not.toHaveBeenCalled();
  });

  it('should call authService.login and navigate on success', () => {
    component.identifier = 'testuser';
    component.password = 'securepassword';

    authServiceSpy.login.mockReturnValue(
      of({
        access_token: 'access',
        refresh_token: 'refresh',
        token_type: 'bearer',
        user_id: '1',
        email: 'a@a.com',
        username: 'testuser',
        role: 'user',
      }),
    );

    component['handleSubmit']();

    expect(component['error']()).toBeNull();
    expect(component['loading']()).toBe(false);
    expect(authServiceSpy.login).toHaveBeenCalledWith({
      identifier: 'testuser',
      password: 'securepassword',
    });
    expect(routerSpy.navigate).toHaveBeenCalledWith(['/meetings']);
  });

  it('should set error message if authService.login fails', () => {
    component.identifier = 'testuser';
    component.password = 'securepassword';

    authServiceSpy.login.mockReturnValue(
      throwError(() => ({
        error: { detail: 'Incorrect credentials' },
      })),
    );

    component['handleSubmit']();

    expect(component['loading']()).toBe(false);
    expect(component['error']()).toBe('Incorrect credentials');
    expect(routerSpy.navigate).not.toHaveBeenCalled();
  });
});
