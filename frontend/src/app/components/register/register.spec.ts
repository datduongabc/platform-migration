import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { AuthService } from '../../services/auth.service';
import { RegisterComponent } from './register';

describe('RegisterComponent', () => {
  let component: RegisterComponent;
  let fixture: ComponentFixture<RegisterComponent>;
  let authServiceSpy: any;
  let routerSpy: any;

  beforeEach(async () => {
    authServiceSpy = {
      register: vi.fn(),
    };
    routerSpy = {
      navigate: vi.fn(),
    };

    await TestBed.configureTestingModule({
      imports: [RegisterComponent],
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

    fixture = TestBed.createComponent(RegisterComponent);
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

  it('should validate email format using Zod', () => {
    component.email = 'not-an-email';
    component.username = 'validuser';
    component.password = 'password123';

    component['handleSubmit']();

    expect(component['error']()).toBe('Enter a valid email address.');
    expect(authServiceSpy.register).not.toHaveBeenCalled();
  });

  it('should validate username length and charset', () => {
    component.email = 'user@example.com';
    component.username = 'a';
    component.password = 'password123';

    component['handleSubmit']();
    expect(component['error']()).toBe('Username must be at least 3 characters.');

    component.username = 'invalid@user';
    component['handleSubmit']();
    expect(component['error']()).toBe(
      'Username may only contain lowercase letters, digits, hyphens, and underscores.',
    );
  });

  it('should validate password length', () => {
    component.email = 'user@example.com';
    component.username = 'validuser';
    component.password = 'short';

    component['handleSubmit']();

    expect(component['error']()).toBe('Password must be at least 8 characters.');
    expect(authServiceSpy.register).not.toHaveBeenCalled();
  });

  it('should submit successfully and navigate to login', () => {
    component.email = 'user@example.com';
    component.username = 'validuser';
    component.password = 'password123';

    authServiceSpy.register.mockReturnValue(of({ status: 'ok' }));

    component['handleSubmit']();

    expect(component['error']()).toBeNull();
    expect(component['loading']()).toBe(false);
    expect(authServiceSpy.register).toHaveBeenCalledWith({
      email: 'user@example.com',
      username: 'validuser',
      password: 'password123',
    });
    expect(routerSpy.navigate).toHaveBeenCalledWith(['/login']);
  });

  it('should display error if registration fails', () => {
    component.email = 'user@example.com';
    component.username = 'validuser';
    component.password = 'password123';

    authServiceSpy.register.mockReturnValue(
      throwError(() => ({
        error: { detail: 'Username is already taken.' },
      })),
    );

    component['handleSubmit']();

    expect(component['loading']()).toBe(false);
    expect(component['error']()).toBe('Username is already taken.');
    expect(routerSpy.navigate).not.toHaveBeenCalled();
  });
});
