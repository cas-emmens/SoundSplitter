import { Component, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { filter } from 'rxjs/operators';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  private router = inject(Router);
  // The tabs/theory/practice pages want a wide canvas (score / fretboard); every other page stays
  // at the centred narrow column. Track the route so the shell can drop the width cap.
  wide = signal(false);
  private wideRoutes = ['/tabs', '/theory', '/practice'];

  constructor() {
    this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe((e) => this.wide.set(this.wideRoutes.some((r) => e.urlAfterRedirects.startsWith(r))));
  }
}
