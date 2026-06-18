import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'library' },
  { path: 'capture', loadComponent: () => import('./pages/capture/capture').then(m => m.CapturePage) },
  { path: 'library', loadComponent: () => import('./pages/library/library').then(m => m.LibraryPage) },
  { path: 'player/:id', loadComponent: () => import('./pages/player/player').then(m => m.PlayerPage) },
  { path: '**', redirectTo: 'library' }
];
