import { computed, inject, Injectable, signal } from '@angular/core';
import { catchError, Observable, of, tap, throwError } from 'rxjs';

import { LoginRequest, RegisterRequest, Token, TokenRefreshResponse } from '../api/models';
import { AuthenticationService } from '../api/services/authentication.service';

export interface User {
  id: string;
  email: string;
  username: string;
  role: string;
}

@Injectable({
  providedIn: 'root',
})
export class AuthService {
  private readonly apiAuthService = inject(AuthenticationService);

  // Signals for client state management
  readonly currentUser = signal<User | null>(null);
  readonly isAuthenticated = computed(() => this.currentUser() !== null);
  readonly isCheckingSession = signal<boolean>(true);

  constructor() {
    this.loadSession();
  }

  private loadSession(): void {
    try {
      const accessToken = localStorage.getItem('access_token');
      const userJson = localStorage.getItem('user');

      if (accessToken && userJson) {
        this.currentUser.set(JSON.parse(userJson));
      }
    } catch (e) {
      console.error('Error loading auth session:', e);
    } finally {
      this.isCheckingSession.set(false);
    }
  }

  register(payload: RegisterRequest): Observable<any> {
    return this.apiAuthService.registerAuthRegisterPost({ body: payload });
  }

  login(payload: LoginRequest): Observable<Token> {
    return this.apiAuthService.loginAuthLoginPost({ body: payload }).pipe(
      tap((response) => {
        localStorage.setItem('access_token', response.access_token);
        localStorage.setItem('refresh_token', response.refresh_token);

        const user: User = {
          id: response.user_id,
          email: response.email,
          username: response.username,
          role: response.role,
        };
        localStorage.setItem('user', JSON.stringify(user));
        this.currentUser.set(user);
      }),
    );
  }

  logout(): Observable<any> {
    // Clear storage and reset state immediately
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user');
    this.currentUser.set(null);

    // Call logout endpoint (non-blocking, best-effort)
    return this.apiAuthService
      .logoutAuthLogoutPost()
      .pipe(catchError(() => of({ message: 'Logged out locally.' })));
  }

  refreshToken(): Observable<TokenRefreshResponse> {
    const refreshToken = localStorage.getItem('refresh_token');
    if (!refreshToken) {
      return throwError(() => new Error('No refresh token available'));
    }

    return this.apiAuthService
      .refreshTokenAuthRefreshPost({ body: { refresh_token: refreshToken } })
      .pipe(
        tap((response) => {
          localStorage.setItem('access_token', response.access_token);
          localStorage.setItem('refresh_token', response.refresh_token);
        }),
        catchError((error) => {
          // If refreshing fails, log out the user
          this.logout().subscribe();
          return throwError(() => error);
        }),
      );
  }

  getAccessToken(): string | null {
    return localStorage.getItem('access_token');
  }
}
