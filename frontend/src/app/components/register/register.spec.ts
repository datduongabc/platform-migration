import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { AuthService } from '../../services/auth.service';
import { RegisterComponent } from './register';

describe('RegisterComponent - Multi-Paradigm Test Suite', () => {
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

  // ---------------------------------------------------------------------------
  // 1. BLACKBOX TESTING - BOUNDARY VALUE ANALYSIS (3-VALUE BVA)
  // Boundaries:
  // A. Username length: Min = 3, Max = 30
  // B. Password length: Min = 8
  // ---------------------------------------------------------------------------
  describe('Blackbox - Boundary Value Analysis (3-Value BVA)', () => {
    // --- Username Min Length (3) ---
    it('BVA Username Min 3: 2 chars (Just Below) -> Should block submit', () => {
      component['registerForm'].patchValue({
        email: 'user@example.com',
        username: 'ab', // 2 chars - Invalid
        password: 'password123',
      });
      component['handleSubmit']();
      expect(authServiceSpy.register).not.toHaveBeenCalled();
    });

    it('BVA Username Min 3: 3 chars (Boundary) -> Should allow submit', () => {
      component['registerForm'].patchValue({
        email: 'user@example.com',
        username: 'abc', // 3 chars - Valid
        password: 'password123',
      });
      authServiceSpy.register.mockReturnValue(of({}));
      component['handleSubmit']();
      expect(authServiceSpy.register).toHaveBeenCalled();
    });

    it('BVA Username Min 3: 4 chars (Just Above) -> Should allow submit', () => {
      component['registerForm'].patchValue({
        email: 'user@example.com',
        username: 'abcd', // 4 chars - Valid
        password: 'password123',
      });
      authServiceSpy.register.mockReturnValue(of({}));
      component['handleSubmit']();
      expect(authServiceSpy.register).toHaveBeenCalled();
    });

    // --- Username Max Length (30) ---
    it('BVA Username Max 30: 29 chars (Just Below) -> Should allow submit', () => {
      component['registerForm'].patchValue({
        email: 'user@example.com',
        username: 'a'.repeat(29), // 29 chars - Valid
        password: 'password123',
      });
      authServiceSpy.register.mockReturnValue(of({}));
      component['handleSubmit']();
      expect(authServiceSpy.register).toHaveBeenCalled();
    });

    it('BVA Username Max 30: 30 chars (Boundary) -> Should allow submit', () => {
      component['registerForm'].patchValue({
        email: 'user@example.com',
        username: 'a'.repeat(30), // 30 chars - Valid
        password: 'password123',
      });
      authServiceSpy.register.mockReturnValue(of({}));
      component['handleSubmit']();
      expect(authServiceSpy.register).toHaveBeenCalled();
    });

    it('BVA Username Max 30: 31 chars (Just Above) -> Should block submit', () => {
      component['registerForm'].patchValue({
        email: 'user@example.com',
        username: 'a'.repeat(31), // 31 chars - Invalid
        password: 'password123',
      });
      component['handleSubmit']();
      expect(authServiceSpy.register).not.toHaveBeenCalled();
    });

    // --- Password Min Length (8) ---
    it('BVA Password Min 8: 7 chars (Just Below) -> Should block submit', () => {
      component['registerForm'].patchValue({
        email: 'user@example.com',
        username: 'validuser',
        password: 'a'.repeat(7), // 7 chars - Invalid
      });
      component['handleSubmit']();
      expect(authServiceSpy.register).not.toHaveBeenCalled();
    });

    it('BVA Password Min 8: 8 chars (Boundary) -> Should allow submit', () => {
      component['registerForm'].patchValue({
        email: 'user@example.com',
        username: 'validuser',
        password: 'a'.repeat(8), // 8 chars - Valid
      });
      authServiceSpy.register.mockReturnValue(of({}));
      component['handleSubmit']();
      expect(authServiceSpy.register).toHaveBeenCalled();
    });

    it('BVA Password Min 8: 9 chars (Just Above) -> Should allow submit', () => {
      component['registerForm'].patchValue({
        email: 'user@example.com',
        username: 'validuser',
        password: 'a'.repeat(9), // 9 chars - Valid
      });
      authServiceSpy.register.mockReturnValue(of({}));
      component['handleSubmit']();
      expect(authServiceSpy.register).toHaveBeenCalled();
    });
  });

  // ---------------------------------------------------------------------------
  // 2. DECISION TABLE (DT) COMBINATIONS
  // Mathematically complete: 2^3 = 8 cases
  // Inputs: E (Email validity), U (Username validity), P (Password validity)
  // ---------------------------------------------------------------------------
  describe('Decision Table (DT) Testing - Complete 8 Combinations', () => {
    // DT1: Email Invalid (F), Username Invalid (F), Password Invalid (F) -> Invalid
    it('DT Case 1 [F, F, F]: Should block submit when all fields are invalid', () => {
      component['registerForm'].patchValue({
        email: 'not-an-email',
        username: 'a',
        password: '123',
      });
      component['handleSubmit']();
      expect(authServiceSpy.register).not.toHaveBeenCalled();
    });

    // DT2: Email Invalid (F), Username Invalid (F), Password Valid (T) -> Invalid
    it('DT Case 2 [F, F, T]: Should block submit when email and username are invalid', () => {
      component['registerForm'].patchValue({
        email: 'not-an-email',
        username: 'a',
        password: 'password123',
      });
      component['handleSubmit']();
      expect(authServiceSpy.register).not.toHaveBeenCalled();
    });

    // DT3: Email Invalid (F), Username Valid (T), Password Invalid (F) -> Invalid
    it('DT Case 3 [F, T, F]: Should block submit when email and password are invalid', () => {
      component['registerForm'].patchValue({
        email: 'not-an-email',
        username: 'validuser',
        password: '123',
      });
      component['handleSubmit']();
      expect(authServiceSpy.register).not.toHaveBeenCalled();
    });

    // DT4: Email Invalid (F), Username Valid (T), Password Valid (T) -> Invalid
    it('DT Case 4 [F, T, T]: Should block submit when only email is invalid', () => {
      component['registerForm'].patchValue({
        email: 'not-an-email',
        username: 'validuser',
        password: 'password123',
      });
      component['handleSubmit']();
      expect(authServiceSpy.register).not.toHaveBeenCalled();
    });

    // DT5: Email Valid (T), Username Invalid (F), Password Invalid (F) -> Invalid
    it('DT Case 5 [T, F, F]: Should block submit when username and password are invalid', () => {
      component['registerForm'].patchValue({
        email: 'user@example.com',
        username: 'a',
        password: '123',
      });
      component['handleSubmit']();
      expect(authServiceSpy.register).not.toHaveBeenCalled();
    });

    // DT6: Email Valid (T), Username Invalid (F), Password Valid (T) -> Invalid
    it('DT Case 6 [T, F, T]: Should block submit when only username is invalid', () => {
      component['registerForm'].patchValue({
        email: 'user@example.com',
        username: 'a',
        password: 'password123',
      });
      component['handleSubmit']();
      expect(authServiceSpy.register).not.toHaveBeenCalled();
    });

    // DT7: Email Valid (T), Username Valid (T), Password Invalid (F) -> Invalid
    it('DT Case 7 [T, T, F]: Should block submit when only password is invalid', () => {
      component['registerForm'].patchValue({
        email: 'user@example.com',
        username: 'validuser',
        password: '123',
      });
      component['handleSubmit']();
      expect(authServiceSpy.register).not.toHaveBeenCalled();
    });

    // DT8: Email Valid (T), Username Valid (T), Password Valid (T) -> Valid
    it('DT Case 8 [T, T, T]: Should allow submit when all fields are valid', () => {
      component['registerForm'].patchValue({
        email: 'user@example.com',
        username: 'validuser',
        password: 'password123',
      });
      authServiceSpy.register.mockReturnValue(of({}));
      component['handleSubmit']();
      expect(authServiceSpy.register).toHaveBeenCalled();
    });
  });

  // ---------------------------------------------------------------------------
  // 3. WHITEBOX TESTING (BRANCH / STATEMENT COVERAGE)
  // Targets code branches in handleSubmit()
  // ---------------------------------------------------------------------------
  describe('Whitebox - Path & Branch Coverage', () => {
    // Path 1: form.invalid is true -> marks all touched, returns early
    it('Path 1: Should exit early and call markAllAsTouched if form is invalid', () => {
      const formSpy = vi.spyOn(component['registerForm'], 'markAllAsTouched');
      component['registerForm'].patchValue({
        email: '',
        username: '',
        password: '',
      });
      component['handleSubmit']();
      expect(formSpy).toHaveBeenCalled();
      expect(authServiceSpy.register).not.toHaveBeenCalled();
    });

    // Path 2: form.valid is true, authService.register succeeds -> navigates to /login
    it('Path 2: Should navigate to /login on successful registration API call', () => {
      component['registerForm'].patchValue({
        email: 'test@example.com',
        username: 'testuser',
        password: 'password123',
      });
      authServiceSpy.register.mockReturnValue(of({ status: 'ok' }));

      component['handleSubmit']();

      expect(component['loading']()).toBe(false);
      expect(component['error']()).toBeNull();
      expect(routerSpy.navigate).toHaveBeenCalledWith(['/login']);
    });

    // Path 3: form.valid is true, authService.register fails -> sets loading false, sets error details
    it('Path 3: Should handle API error response and display error message', () => {
      component['registerForm'].patchValue({
        email: 'test@example.com',
        username: 'testuser',
        password: 'password123',
      });
      authServiceSpy.register.mockReturnValue(
        throwError(() => ({
          error: { detail: 'Email already exists.' },
        })),
      );

      component['handleSubmit']();

      expect(component['loading']()).toBe(false);
      expect(component['error']()).toBe('Email already exists.');
      expect(routerSpy.navigate).not.toHaveBeenCalled();
    });
  });
});
