import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ProfileService, ProfileResponse } from '../../services/profile.service';
import { AuthService } from '../../services/auth.service';
import { ApiConfiguration } from '../../api/api-configuration';

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './profile.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfileComponent implements OnInit {
  private readonly profileService = inject(ProfileService);
  protected readonly authService = inject(AuthService);
  protected readonly config = inject(ApiConfiguration);

  // States
  readonly profile = signal<ProfileResponse | null>(null);
  readonly loading = signal<boolean>(false);
  readonly error = signal<string | null>(null);

  // Profile Form Edit States
  readonly updating = signal<boolean>(false);
  readonly updateError = signal<string | null>(null);
  readonly updateSuccess = signal<boolean>(false);
  username = '';
  displayName = '';
  themePreference = 'default';

  // Password Form States
  readonly passwordBusy = signal<boolean>(false);
  readonly passwordError = signal<string | null>(null);
  readonly passwordSuccess = signal<boolean>(false);
  currentPassword = '';
  newPassword = '';
  confirmPassword = '';

  // Avatar uploading States
  readonly avatarUploading = signal<boolean>(false);
  readonly avatarError = signal<string | null>(null);

  // Model preference states
  readonly allowedModels = signal<{ provider: string; model: string }[]>([]);
  readonly modelPrefBusy = signal<boolean>(false);
  readonly modelPrefError = signal<string | null>(null);
  selectedModelKey = ''; // "" = use system default, else "provider:model"

  ngOnInit(): void {
    this.loadProfile();
    this.loadModelPreferences();
  }

  loadModelPreferences(): void {
    this.profileService.getModelPreferences().subscribe({
      next: (res) => {
        this.allowedModels.set(res.allowedModels);
        this.selectedModelKey = res.provider && res.model ? `${res.provider}:${res.model}` : '';
      },
      error: () => {
        // Non-fatal: preference picker just stays empty/disabled.
      },
    });
  }

  saveModelPreference(): void {
    this.modelPrefBusy.set(true);
    this.modelPrefError.set(null);
    const [provider, model] = this.selectedModelKey
      ? this.selectedModelKey.split(':')
      : [null, null];
    this.profileService.updateModelPreferences(provider, model).subscribe({
      next: () => this.modelPrefBusy.set(false),
      error: (err) => {
        this.modelPrefError.set(err.error?.detail || 'Failed to save model preference.');
        this.modelPrefBusy.set(false);
      },
    });
  }

  loadProfile(): void {
    this.loading.set(true);
    this.error.set(null);
    this.profileService.getProfile().subscribe({
      next: (res) => {
        this.profile.set(res);
        this.username = res.username;
        this.displayName = res.display_name || '';
        this.themePreference = res.theme_preference || 'luxury';
        this.applyTheme(this.themePreference);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err.error?.detail || 'Failed to load profile.');
        this.loading.set(false);
      },
    });
  }

  applyTheme(theme: string): void {
    this.profileService.applyTheme(theme);
  }

  saveProfile(): void {
    this.updating.set(true);
    this.updateError.set(null);
    this.updateSuccess.set(false);

    this.profileService.updateProfile({
      username: this.username.trim(),
      display_name: this.displayName.trim() || null,
      theme_preference: this.themePreference,
    }).subscribe({
      next: () => {
        this.applyTheme(this.themePreference);
        this.updateSuccess.set(true);
        this.updating.set(false);
        this.loadProfile();
      },
      error: (err) => {
        this.updateError.set(err.error?.detail || 'Failed to update profile.');
        this.updating.set(false);
      },
    });
  }

  changePassword(): void {
    const cp = this.currentPassword.trim();
    const np = this.newPassword.trim();
    const cnp = this.confirmPassword.trim();

    if (!cp || !np || !cnp) return;

    if (np !== cnp) {
      this.passwordError.set('New passwords do not match.');
      return;
    }
    if (np.length < 8) {
      this.passwordError.set('New password must be at least 8 characters.');
      return;
    }

    this.passwordBusy.set(true);
    this.passwordError.set(null);
    this.passwordSuccess.set(false);

    this.profileService.changePassword(cp, np).subscribe({
      next: () => {
        this.passwordSuccess.set(true);
        this.passwordBusy.set(false);
        this.currentPassword = '';
        this.newPassword = '';
        this.confirmPassword = '';
      },
      error: (err) => {
        this.passwordError.set(err.error?.detail || 'Failed to change password.');
        this.passwordBusy.set(false);
      },
    });
  }

  onAvatarSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      const file = input.files[0];
      
      // Limit to ALLOWED types
      const allowed = ['image/jpeg', 'image/png', 'image/webp'];
      if (!allowed.includes(file.type)) {
        this.avatarError.set('Invalid image type. Please select JPEG, PNG, or WEBP.');
        return;
      }

      // Limit size to 2MB
      if (file.size > 2 * 1024 * 1024) {
        this.avatarError.set('Avatar must be smaller than 2 MB.');
        return;
      }

      this.avatarUploading.set(true);
      this.avatarError.set(null);

      // 1. Request presigned upload URL
      this.profileService.requestAvatarUpload(file.type, file.size).subscribe({
        next: (uploadRes) => {
          // 2. Upload file bytes via PUT
          this.profileService.uploadAvatarFile(uploadRes.uploadUrl, file, file.type).subscribe({
            next: () => {
              // 3. Confirm by updating avatar key in profile
              this.profileService.updateProfile({ avatar_key: uploadRes.avatarKey }).subscribe({
                next: () => {
                  this.avatarUploading.set(false);
                  this.loadProfile();
                },
                error: (err) => {
                  this.avatarError.set(err.error?.detail || 'Failed to confirm avatar key.');
                  this.avatarUploading.set(false);
                }
              });
            },
            error: () => {
              this.avatarError.set('Failed to upload avatar image bytes.');
              this.avatarUploading.set(false);
            }
          });
        },
        error: (err) => {
          this.avatarError.set(err.error?.detail || 'Failed to request avatar upload.');
          this.avatarUploading.set(false);
        }
      });
    }
  }

  removeAvatar(): void {
    if (confirm('Are you sure you want to remove your avatar?')) {
      this.avatarUploading.set(true);
      this.profileService.updateProfile({ avatar_key: null }).subscribe({
        next: () => {
          this.avatarUploading.set(false);
          this.loadProfile();
        },
        error: (err) => {
          alert(err.error?.detail || 'Failed to remove avatar.');
          this.avatarUploading.set(false);
        }
      });
    }
  }

  getAvatarUrl(avatarUrl: string | null): string {
    if (!avatarUrl) return '';
    if (avatarUrl.startsWith('http://') || avatarUrl.startsWith('https://')) {
      return avatarUrl;
    }
    const root = this.config.rootUrl.replace(/\/api\/v1\/?$/, '').replace(/\/api\/?$/, '');
    return `${root}${avatarUrl.startsWith('/') ? avatarUrl : '/' + avatarUrl}`;
  }

  getInitials(displayName: string | null, username: string): string {
    const name = displayName?.trim() || username;
    const words = name.split(/\s+/).filter(Boolean);
    if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
  }

  formatMemberSince(iso: string): string {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
  }

  formatHours(seconds: number): string {
    const hrs = seconds / 3600;
    return hrs.toFixed(1);
  }
}
