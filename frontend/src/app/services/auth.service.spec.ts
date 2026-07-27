import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { LoginRequest, RegisterRequest, Token, TokenRefreshResponse } from '../api/models';
import { AuthService } from './auth.service';

describe('AuthService', () => {
  let service: AuthService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [AuthService, provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(AuthService);
    httpMock = TestBed.inject(HttpTestingController);

    // Clear localStorage before each test
    localStorage.clear();
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should send a register request', () => {
    const mockRequest: RegisterRequest = {
      email: 'test@example.com',
      username: 'testuser',
      password: 'password123',
    };

    service.register(mockRequest).subscribe((response) => {
      expect(response).toEqual({ message: 'Success' });
    });

    const req = httpMock.expectOne('http://localhost:8000/auth/register');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(mockRequest);
    req.flush({ message: 'Success' });
  });

  it('should login, set tokens in localStorage, and update currentUser', () => {
    const mockRequest: LoginRequest = {
      identifier: 'testuser',
      password: 'password123',
    };

    const mockResponse: Token = {
      access_token: 'access-123',
      refresh_token: 'refresh-123',
      token_type: 'bearer',
      user_id: 'user-123',
      email: 'test@example.com',
      username: 'testuser',
      role: 'user',
    };

    service.login(mockRequest).subscribe((response) => {
      expect(response).toEqual(mockResponse);
      expect(localStorage.getItem('access_token')).toBe('access-123');
      expect(localStorage.getItem('refresh_token')).toBe('refresh-123');
      expect(service.currentUser()).toEqual({
        id: 'user-123',
        email: 'test@example.com',
        username: 'testuser',
        role: 'user',
      });
    });

    const req = httpMock.expectOne('http://localhost:8000/auth/login');
    expect(req.request.method).toBe('POST');
    req.flush(mockResponse);
  });

  it('should logout and clear localStorage and currentUser', () => {
    localStorage.setItem('access_token', 'access-123');
    localStorage.setItem('refresh_token', 'refresh-123');
    localStorage.setItem('user', JSON.stringify({ id: '1' }));

    service.logout().subscribe(() => {
      expect(localStorage.getItem('access_token')).toBeNull();
      expect(localStorage.getItem('refresh_token')).toBeNull();
      expect(localStorage.getItem('user')).toBeNull();
      expect(service.currentUser()).toBeNull();
    });

    const req = httpMock.expectOne('http://localhost:8000/auth/logout');
    expect(req.request.method).toBe('POST');
    req.flush({});
  });

  it('should refresh access token', () => {
    localStorage.setItem('refresh_token', 'refresh-123');

    const mockResponse: TokenRefreshResponse = {
      access_token: 'new-access-123',
      refresh_token: 'new-refresh-123',
      token_type: 'bearer',
    };

    service.refreshToken().subscribe((response) => {
      expect(response).toEqual(mockResponse);
      expect(localStorage.getItem('access_token')).toBe('new-access-123');
      expect(localStorage.getItem('refresh_token')).toBe('new-refresh-123');
    });

    const req = httpMock.expectOne('http://localhost:8000/auth/refresh');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ refresh_token: 'refresh-123' });
    req.flush(mockResponse);
  });
});
