import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { Subject, concat, of } from 'rxjs';
import { catchError, map, switchMap, tap } from 'rxjs/operators';
import { RegisterRequest } from '../../api/models';
import { RegisterRequestSchema } from '../../schemas/api.schemas';
import { AuthService } from '../../services/auth.service';

interface SubmitState<T> {
  loading: boolean;
  error: string | null;
  data: T | null;
}

@Component({
  selector: 'app-register',
  standalone: true,
  imports: [RouterLink, FormsModule],
  templateUrl: './register.html',
})
export class RegisterComponent {
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);

  email = '';
  username = '';
  password = '';

  protected readonly showPassword = signal(false);

  // Subject to trigger submit action
  private readonly submitSubject = new Subject<RegisterRequest>();

  // Declarative RxJS stream representing the submit pipeline
  private readonly submitState$ = this.submitSubject.pipe(
    switchMap((payload) => {
      // Validate register request using Zod
      const validation = RegisterRequestSchema.safeParse(payload);
      if (!validation.success) {
        const firstError = validation.error.issues[0];
        return of({ loading: false, error: firstError.message, data: null });
      }

      // Execute request with proper loading/error states
      return concat(
        of({ loading: true, error: null, data: null }),
        this.authService.register(payload).pipe(
          tap(() => this.router.navigate(['/login'])),
          map((data) => ({ loading: false, error: null, data })),
          catchError((err) => {
            const errMsg = err.error?.detail || 'Registration failed. Please try again.';
            return of({ loading: false, error: errMsg, data: null });
          }),
        ),
      );
    }),
  );

  // Convert stream to signal (handles subscription & lifecycle automatically)
  private readonly submitState = toSignal(this.submitState$, {
    initialValue: { loading: false, error: null, data: null } as SubmitState<any>,
  });

  // Expose signals to preserve template bindings
  protected readonly loading = computed(() => this.submitState().loading);
  protected readonly error = computed(() => this.submitState().error);

  protected togglePasswordVisibility(): void {
    this.showPassword.update((val) => !val);
  }

  protected handleSubmit(): void {
    this.submitSubject.next({
      email: this.email,
      username: this.username,
      password: this.password,
    });
  }
}
