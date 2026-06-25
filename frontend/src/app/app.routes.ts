import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'library' },
  { path: 'capture', loadComponent: () => import('./pages/capture/capture').then(m => m.CapturePage) },
  { path: 'library', loadComponent: () => import('./pages/library/library').then(m => m.LibraryPage) },
  { path: 'player/:id', loadComponent: () => import('./pages/player/player').then(m => m.PlayerPage) },
  { path: 'tabs/:id', loadComponent: () => import('./pages/tabs/tabs').then(m => m.TabsPage) },
  { path: 'theory', loadComponent: () => import('./pages/theory/theory').then(m => m.TheoryPage) },
  { path: 'practice', loadComponent: () => import('./pages/practice/practice').then(m => m.PracticePage) },
  { path: '**', redirectTo: 'library' }
];
