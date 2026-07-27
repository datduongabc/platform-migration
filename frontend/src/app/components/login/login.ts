import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { LoginRequest } from '../../api/models';
import { LoginRequestSchema } from '../../schemas/api.schemas';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [RouterLink, FormsModule],
  templateUrl: './login.html',
})
export class LoginComponent {
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);

  identifier = '';
  password = '';

  protected readonly error = signal<string | null>(null);
  protected readonly loading = signal(false);
  protected readonly showPassword = signal(false);

  protected togglePasswordVisibility(): void {
    this.showPassword.update((val) => !val);
  }

  protected handleSubmit(): void {
    const payload: LoginRequest = {
      identifier: this.identifier,
      password: this.password,
    };

    const validation = LoginRequestSchema.safeParse(payload);

    if (!validation.success) {
      const firstError = validation.error.issues[0];
      this.error.set(firstError.message);
      return;
    }

    this.error.set(null);
    this.loading.set(true);

    this.authService.login(payload).subscribe({
      next: () => {
        this.loading.set(false);
        this.router.navigate(['/meetings']);
      },
      error: (err) => {
        this.loading.set(false);
        const errMsg = err.error?.detail || 'Login failed. Please try again.';
        this.error.set(errMsg);
      },
    });
  }
}
