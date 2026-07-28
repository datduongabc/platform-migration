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
      const userJson = sessionStorage.getItem('user');

      if (userJson) {
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
        const user: User = {
          id: response.user_id,
          email: response.email,
          username: response.username,
          role: response.role,
        };
        sessionStorage.setItem('user', JSON.stringify(user));
        this.currentUser.set(user);
      }),
    );
  }

  logout(): Observable<any> {
    // Clear session storage and reset state immediately
    sessionStorage.removeItem('user');
    this.currentUser.set(null);

    // Call logout endpoint to clear HttpOnly cookies server-side
    return this.apiAuthService
      .logoutAuthLogoutPost()
      .pipe(catchError(() => of({ message: 'Logged out locally.' })));
  }

  refreshToken(): Observable<TokenRefreshResponse> {
    return this.apiAuthService.refreshTokenAuthRefreshPost({ body: { refresh_token: '' } }).pipe(
      catchError((error) => {
        // If refreshing fails, log out the user
        this.logout().subscribe();
        return throwError(() => error);
      }),
    );
  }

  getAccessToken(): string | null {
    return null;
  }
}
