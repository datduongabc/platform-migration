import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { AuthService } from '../../services/auth.service';
import { LoginComponent } from './login';

describe('LoginComponent - Multi-Paradigm Test Suite', () => {
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

  // ---------------------------------------------------------------------------
  // 1. BLACKBOX TESTING - BOUNDARY VALUE ANALYSIS (3-VALUE BVA)
  // Password boundary: Min length = 8
  // 3 Values: 7 (just below), 8 (boundary), 9 (just above)
  // ---------------------------------------------------------------------------
  describe('Blackbox - Boundary Value Analysis (3-Value BVA)', () => {
    it('BVA Value 7 (Just Below): Should block submit for 7-character password', () => {
      component['loginForm'].patchValue({
        identifier: 'testuser',
        password: 'a'.repeat(7), // 7 chars - Invalid
      });
      component['handleSubmit']();
      expect(authServiceSpy.login).not.toHaveBeenCalled();
    });

    it('BVA Value 8 (Boundary): Should allow submit for 8-character password', () => {
      component['loginForm'].patchValue({
        identifier: 'testuser',
        password: 'a'.repeat(8), // 8 chars - Valid
      });
      authServiceSpy.login.mockReturnValue(of({}));
      component['handleSubmit']();
      expect(authServiceSpy.login).toHaveBeenCalled();
    });

    it('BVA Value 9 (Just Above): Should allow submit for 9-character password', () => {
      component['loginForm'].patchValue({
        identifier: 'testuser',
        password: 'a'.repeat(9), // 9 chars - Valid
      });
      authServiceSpy.login.mockReturnValue(of({}));
      component['handleSubmit']();
      expect(authServiceSpy.login).toHaveBeenCalled();
    });
  });

  // ---------------------------------------------------------------------------
  // 2. DECISION TABLE (DT) COMBINATIONS
  // Inputs: A (Identifier filled), B (Password valid >= 8 chars)
  // ---------------------------------------------------------------------------
  describe('Decision Table (DT) Testing', () => {
    // DT Case 1: Identifier Empty (False), Password Short (False) -> Result: Invalid
    it('DT Case 1 [F, F]: Should block submit when both fields are invalid', () => {
      component['loginForm'].patchValue({
        identifier: '',
        password: '123',
      });
      component['handleSubmit']();
      expect(authServiceSpy.login).not.toHaveBeenCalled();
    });

    // DT Case 2: Identifier Empty (False), Password Valid (True) -> Result: Invalid
    it('DT Case 2 [F, T]: Should block submit when identifier is empty but password is valid', () => {
      component['loginForm'].patchValue({
        identifier: '',
        password: 'password123',
      });
      component['handleSubmit']();
      expect(authServiceSpy.login).not.toHaveBeenCalled();
    });

    // DT Case 3: Identifier Filled (True), Password Short (False) -> Result: Invalid
    it('DT Case 3 [T, F]: Should block submit when identifier is filled but password is short', () => {
      component['loginForm'].patchValue({
        identifier: 'testuser',
        password: '123',
      });
      component['handleSubmit']();
      expect(authServiceSpy.login).not.toHaveBeenCalled();
    });

    // DT Case 4: Identifier Filled (True), Password Valid (True) -> Result: Valid
    it('DT Case 4 [T, T]: Should allow submit when both inputs are valid', () => {
      component['loginForm'].patchValue({
        identifier: 'testuser',
        password: 'password123',
      });
      authServiceSpy.login.mockReturnValue(of({}));
      component['handleSubmit']();
      expect(authServiceSpy.login).toHaveBeenCalled();
    });
  });

  // ---------------------------------------------------------------------------
  // 3. WHITEBOX TESTING (BRANCH / STATEMENT COVERAGE)
  // Targets code branches in handleSubmit()
  // ---------------------------------------------------------------------------
  describe('Whitebox - Path & Branch Coverage', () => {
    // Path 1: form.invalid is true -> marks all touched, returns early
    it('Path 1: Should exit early and call markAllAsTouched if form is invalid', () => {
      const formSpy = vi.spyOn(component['loginForm'], 'markAllAsTouched');
      component['loginForm'].patchValue({
        identifier: '',
        password: '',
      });
      component['handleSubmit']();
      expect(formSpy).toHaveBeenCalled();
      expect(authServiceSpy.login).not.toHaveBeenCalled();
    });

    // Path 2: form.valid is true, authService.login succeeds -> navigates to /meetings
    it('Path 2: Should navigate to /meetings on successful login API call', () => {
      component['loginForm'].patchValue({
        identifier: 'admin',
        password: 'password123',
      });
      authServiceSpy.login.mockReturnValue(of({ access_token: 'token' }));

      component['handleSubmit']();

      expect(component['loading']()).toBe(false);
      expect(component['error']()).toBeNull();
      expect(routerSpy.navigate).toHaveBeenCalledWith(['/meetings']);
    });

    // Path 3: form.valid is true, authService.login fails -> sets loading false, sets error details
    it('Path 3: Should handle API error response and display error message', () => {
      component['loginForm'].patchValue({
        identifier: 'admin',
        password: 'password123',
      });
      authServiceSpy.login.mockReturnValue(
        throwError(() => ({
          error: { detail: 'Incorrect username or password.' },
        })),
      );

      component['handleSubmit']();

      expect(component['loading']()).toBe(false);
      expect(component['error']()).toBe('Incorrect username or password.');
      expect(routerSpy.navigate).not.toHaveBeenCalled();
    });
  });
});
