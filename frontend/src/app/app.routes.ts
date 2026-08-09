import { Routes } from '@angular/router';
import { adminGuard, authGuard, noAuthGuard } from './guards/auth.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./components/login/login').then((m) => m.LoginComponent),
    canActivate: [noAuthGuard],
  },
  {
    path: 'register',
    loadComponent: () => import('./components/register/register').then((m) => m.RegisterComponent),
    canActivate: [noAuthGuard],
  },
  {
    path: 'meetings',
    loadComponent: () => import('./components/meetings/meetings').then((m) => m.MeetingsComponent),
    canActivate: [authGuard],
  },
  {
    path: 'meetings/:id',
    loadComponent: () =>
      import('./components/meetings/meeting-detail/meeting-detail').then((m) => m.MeetingDetailComponent),
    canActivate: [authGuard],
  },
  {
    path: 'chat',
    loadComponent: () => import('./components/chat/chat').then((m) => m.ChatComponent),
    canActivate: [authGuard],
  },
  {
    path: 'profile',
    loadComponent: () => import('./components/profile/profile').then((m) => m.ProfileComponent),
    canActivate: [authGuard],
  },
  {
    path: 'record',
    loadComponent: () => import('./components/record/record').then((m) => m.RecordComponent),
    canActivate: [authGuard],
  },
  { path: 'admin', redirectTo: 'admin/users', pathMatch: 'full' },
  {
    path: 'admin/users',
    loadComponent: () => import('./components/admin/user-list/user-list').then((m) => m.UserListComponent),
    canActivate: [adminGuard],
  },
  {
    path: 'admin/users/:id',
    loadComponent: () => import('./components/admin/user-detail/user-detail').then((m) => m.UserDetailComponent),
    canActivate: [adminGuard],
  },
  {
    path: 'admin/pipeline',
    loadComponent: () => import('./components/admin/pipeline/pipeline').then((m) => m.PipelineComponent),
    canActivate: [adminGuard],
  },
  {
    path: 'admin/keys',
    loadComponent: () => import('./components/admin/keys/keys').then((m) => m.KeysComponent),
    canActivate: [adminGuard],
  },
  {
    path: 'admin/storage',
    loadComponent: () => import('./components/admin/storage/storage').then((m) => m.StorageComponent),
    canActivate: [adminGuard],
  },
  {
    path: 'admin/config',
    loadComponent: () => import('./components/admin/config/config').then((m) => m.ConfigComponent),
    canActivate: [adminGuard],
  },
  {
    path: 'admin/audit-logs',
    loadComponent: () => import('./components/admin/audit-logs/audit-logs').then((m) => m.AuditLogsComponent),
    canActivate: [adminGuard],
  },
  {
    path: 'admin/activity',
    loadComponent: () => import('./components/admin/activity/activity').then((m) => m.ActivityComponent),
    canActivate: [adminGuard],
  },
  {
    path: 'admin/usage',
    loadComponent: () => import('./components/admin/usage/usage').then((m) => m.UsageComponent),
    canActivate: [adminGuard],
  },
  {
    path: 'admin/features',
    loadComponent: () => import('./components/admin/features/features').then((m) => m.FeaturesComponent),
    canActivate: [adminGuard],
  },
  { path: '', redirectTo: '/login', pathMatch: 'full' },
];
