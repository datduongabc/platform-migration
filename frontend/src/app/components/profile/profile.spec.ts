import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { ProfileResponse, ProfileService } from '../../services/profile.service';
import { ProfileComponent } from './profile';

function makeProfile(overrides: Partial<ProfileResponse> = {}): ProfileResponse {
  return {
    id: 'user-1',
    email: 'user@example.com',
    username: 'someuser',
    display_name: null,
    avatar_key: null,
    avatar_url: null,
    theme_preference: 'default',
    role: 'user',
    created_at: '2026-07-27T00:00:00Z',
    meeting_count: 0,
    folder_count: 0,
    audio_seconds_remaining: 3600,
    agent_queries_remaining: 50,
    ...overrides,
  };
}

describe('ProfileComponent — AI model preference', () => {
  let component: ProfileComponent;
  let profileService: {
    getProfile: ReturnType<typeof vi.fn>;
    getModelPreferences: ReturnType<typeof vi.fn>;
    updateModelPreferences: ReturnType<typeof vi.fn>;
    applyTheme: ReturnType<typeof vi.fn>;
  };

  function setup(prefs: {
    provider: string | null;
    model: string | null;
    allowedModels: { provider: string; model: string }[];
  }) {
    profileService = {
      getProfile: vi.fn().mockReturnValue(of(makeProfile())),
      getModelPreferences: vi.fn().mockReturnValue(of(prefs)),
      updateModelPreferences: vi.fn().mockReturnValue(of({ ok: true })),
      applyTheme: vi.fn(),
    };

    TestBed.configureTestingModule({
      imports: [ProfileComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ProfileService, useValue: profileService },
      ],
    });

    const fixture = TestBed.createComponent(ProfileComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads allowed models and leaves the picker on system default when no preference is set', () => {
    setup({
      provider: null,
      model: null,
      allowedModels: [
        { provider: 'gemini', model: 'gemini-3.5-flash-lite' },
        { provider: 'gemini', model: 'gemini-3.5-flash' },
      ],
    });

    expect(component.allowedModels()).toEqual([
      { provider: 'gemini', model: 'gemini-3.5-flash-lite' },
      { provider: 'gemini', model: 'gemini-3.5-flash' },
    ]);
    expect(component.selectedModelKey).toBe('');
  });

  it('preselects the saved provider:model when a preference already exists', () => {
    setup({
      provider: 'gemini',
      model: 'gemini-3.5-flash',
      allowedModels: [{ provider: 'gemini', model: 'gemini-3.5-flash' }],
    });

    expect(component.selectedModelKey).toBe('gemini:gemini-3.5-flash');
  });

  it('saveModelPreference splits the selected key into provider/model and persists it', () => {
    setup({ provider: null, model: null, allowedModels: [] });
    component.selectedModelKey = 'gemini:gemini-3.5-flash';

    component.saveModelPreference();

    expect(profileService.updateModelPreferences).toHaveBeenCalledWith('gemini', 'gemini-3.5-flash');
    expect(component.modelPrefBusy()).toBe(false);
    expect(component.modelPrefError()).toBeNull();
  });

  it('saveModelPreference sends null/null when reverting to system default', () => {
    setup({ provider: 'gemini', model: 'gemini-3.5-flash', allowedModels: [] });
    component.selectedModelKey = '';

    component.saveModelPreference();

    expect(profileService.updateModelPreferences).toHaveBeenCalledWith(null, null);
  });

  it('surfaces a disallowed-model error from the backend without clearing the selection', () => {
    setup({ provider: null, model: null, allowedModels: [] });
    profileService.updateModelPreferences.mockReturnValue(
      throwError(() => ({ error: { detail: 'Model is not currently allowed.' } })),
    );
    component.selectedModelKey = 'openai:gpt-4o';

    component.saveModelPreference();

    expect(component.modelPrefError()).toBe('Model is not currently allowed.');
    expect(component.modelPrefBusy()).toBe(false);
  });
});
