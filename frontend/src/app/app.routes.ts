import { Routes } from '@angular/router';
import { UserDetailComponent } from './components/admin/user-detail/user-detail';
import { UserListComponent } from './components/admin/user-list/user-list';
import { LoginComponent } from './components/login/login';
import { MeetingsComponent } from './components/meetings/meetings';
import { RegisterComponent } from './components/register/register';
import { adminGuard, authGuard, noAuthGuard } from './guards/auth.guard';

export const routes: Routes = [
  { path: 'login', component: LoginComponent, canActivate: [noAuthGuard] },
  { path: 'register', component: RegisterComponent, canActivate: [noAuthGuard] },
  { path: 'meetings', component: MeetingsComponent, canActivate: [authGuard] },
  { path: 'admin', redirectTo: 'admin/users', pathMatch: 'full' },
  { path: 'admin/users', component: UserListComponent, canActivate: [adminGuard] },
  { path: 'admin/users/:id', component: UserDetailComponent, canActivate: [adminGuard] },
  { path: '', redirectTo: '/login', pathMatch: 'full' },
];
