import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';

import { provideApiConfiguration } from './api/api-configuration';
import { routes } from './app.routes';
import { authInterceptor } from './interceptors/auth.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    provideHttpClient(withInterceptors([authInterceptor])),
    // Relative path, not an absolute host — nginx reverse-proxies /api/ to the
    // backend container (see frontend/nginx.conf), so the compiled bundle works
    // on any deploy domain without hardcoding a backend host at build time.
    provideApiConfiguration('/api/v1'),
  ],
};
