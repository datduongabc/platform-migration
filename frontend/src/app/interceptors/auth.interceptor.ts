import {
  HttpErrorResponse,
  HttpHandlerFn,
  HttpInterceptorFn,
  HttpRequest,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, switchMap, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';

export const authInterceptor: HttpInterceptorFn = (
  req: HttpRequest<unknown>,
  next: HttpHandlerFn,
) => {
  const authService = inject(AuthService);
  const token = authService.getAccessToken();

  let authReq = req;
  if (
    token &&
    !req.url.includes('/auth/refresh') &&
    !req.url.includes('/auth/login') &&
    !req.url.includes('/auth/register')
  ) {
    authReq = req.clone({
      headers: req.headers.set('Authorization', `Bearer ${token}`),
    });
  }

  return next(authReq).pipe(
    catchError((error) => {
      // If we get a 401 Unauthorized, try to refresh the token (excluding login/refresh endpoints)
      if (
        error instanceof HttpErrorResponse &&
        error.status === 401 &&
        !req.url.includes('/auth/login') &&
        !req.url.includes('/auth/refresh') &&
        !req.url.includes('/auth/register')
      ) {
        return authService.refreshToken().pipe(
          switchMap((response) => {
            // Retry the request with the new access token
            const retryReq = req.clone({
              headers: req.headers.set('Authorization', `Bearer ${response.access_token}`),
            });
            return next(retryReq);
          }),
          catchError((refreshErr) => {
            // If token refresh fails, propagate error
            return throwError(() => refreshErr);
          }),
        );
      }
      return throwError(() => error);
    }),
  );
};
