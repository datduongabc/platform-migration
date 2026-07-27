import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { RegisterRequest } from '../../api/models';
import { RegisterRequestSchema } from '../../schemas/api.schemas';
import { AuthService } from '../../services/auth.service';

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

  protected readonly error = signal<string | null>(null);
  protected readonly loading = signal(false);
  protected readonly showPassword = signal(false);

  protected togglePasswordVisibility(): void {
    this.showPassword.update((val) => !val);
  }

  protected handleSubmit(): void {
    const payload: RegisterRequest = {
      email: this.email,
      username: this.username,
      password: this.password,
    };

    const validation = RegisterRequestSchema.safeParse(payload);

    if (!validation.success) {
      const firstError = validation.error.issues[0];
      this.error.set(firstError.message);
      return;
    }

    this.error.set(null);
    this.loading.set(true);

    this.authService.register(payload).subscribe({
      next: () => {
        this.loading.set(false);
        this.router.navigate(['/login']);
      },
      error: (err) => {
        this.loading.set(false);
        const errMsg = err.error?.detail || 'Registration failed. Please try again.';
        this.error.set(errMsg);
      },
    });
  }
}
