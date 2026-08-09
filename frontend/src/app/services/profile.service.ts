import { inject, Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { tap } from 'rxjs/operators';
import { ApiConfiguration } from '../api/api-configuration';

export interface ProfileResponse {
  id: string;
  email: string | null;
  username: string;
  display_name: string | null;
  avatar_key: string | null;
  avatar_url: string | null;
  theme_preference: string | null;
  role: 'user' | 'admin';
  created_at: string;
  meeting_count: number;
  folder_count: number;
  audio_seconds_remaining: number;
  agent_queries_remaining: number;
}

export interface AvatarUploadResponse {
  uploadUrl: string;
  avatarKey: string;
}

@Injectable({
  providedIn: 'root',
})
export class ProfileService {
  private readonly http = inject(HttpClient);
  private readonly config = inject(ApiConfiguration);

  constructor() {
    this.initThemeFromStorage();
  }

  private get base(): string {
    return this.config.rootUrl;
  }

  initThemeFromStorage(): void {
    if (typeof window === 'undefined') return;
    try {
      const savedTheme = localStorage.getItem('theme_preference');
      if (savedTheme) {
        this.applyTheme(savedTheme);
      }
    } catch (e) {}
  }

  applyTheme(theme: string | null | undefined): void {
    if (typeof document === 'undefined') return;
    const validThemes = ['luxury', 'default', 'playful'];
    const targetTheme = (theme && validThemes.includes(theme)) ? theme : 'luxury';
    document.documentElement.setAttribute('data-theme', targetTheme);
    try {
      localStorage.setItem('theme_preference', targetTheme);
    } catch (e) {}
  }

  getProfile(): Observable<ProfileResponse> {
    return this.http.get<ProfileResponse>(`${this.base}/profile`).pipe(
      tap((res) => {
        if (res && res.theme_preference) {
          this.applyTheme(res.theme_preference);
        }
      })
    );
  }

  updateProfile(payload: {
    username?: string;
    display_name?: string | null;
    theme_preference?: string | null;
    avatar_key?: string | null;
  }): Observable<any> {
    return this.http.patch(`${this.base}/profile`, payload).pipe(
      tap(() => {
        if (payload.theme_preference !== undefined) {
          this.applyTheme(payload.theme_preference);
        }
      })
    );
  }

  getModelPreferences(): Observable<{
    provider: string | null;
    model: string | null;
    allowedModels: { provider: string; model: string }[];
  }> {
    return this.http.get<any>(`${this.base}/profile/preferences`);
  }

  updateModelPreferences(provider: string | null, model: string | null): Observable<any> {
    return this.http.patch(`${this.base}/profile/preferences`, { provider, model });
  }

  changePassword(currentPassword: string, newPassword: string): Observable<any> {
    return this.http.post(`${this.base}/profile/change-password`, {
      currentPassword,
      newPassword,
    });
  }

  requestAvatarUpload(contentType: string, size: number): Observable<AvatarUploadResponse> {
    return this.http.post<AvatarUploadResponse>(`${this.base}/profile/avatar`, {
      contentType,
      size,
    });
  }

  uploadAvatarFile(uploadUrl: string, file: Blob, contentType: string): Observable<any> {
    // Ensure we send with the correct contentType header
    const headers = new HttpHeaders({ 'Content-Type': contentType });
    let targetUrl = uploadUrl;
    if (!uploadUrl.startsWith('http')) {
      if (uploadUrl.startsWith('/api')) {
        const root = this.base.replace(/\/api\/v1\/?$/, '').replace(/\/api\/?$/, '');
        targetUrl = `${root}${uploadUrl}`;
      } else {
        targetUrl = `${this.base}${uploadUrl.startsWith('/') ? uploadUrl : '/' + uploadUrl}`;
      }
    }
    return this.http.put(targetUrl, file, { headers });
  }
}
