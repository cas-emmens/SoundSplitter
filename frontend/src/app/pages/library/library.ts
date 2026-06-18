import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api, Song } from '../../services/api';

@Component({
  selector: 'app-library',
  imports: [RouterLink],
  templateUrl: './library.html',
  styleUrl: './library.css',
})
export class LibraryPage implements OnInit, OnDestroy {
  private api = inject(Api);
  songs = signal<Song[]>([]);
  loading = signal(true);
  private timer?: any;

  ngOnInit() {
    this.refresh();
    this.timer = setInterval(() => this.refresh(), 3000);
  }
  ngOnDestroy() { clearInterval(this.timer); }

  refresh() {
    this.api.library().subscribe((r) => {
      this.songs.set(r.songs);
      this.loading.set(false);
    });
  }

  deleting = signal<string | null>(null);

  remove(s: Song, ev: Event) {
    ev.stopPropagation();
    if (!confirm(`Delete "${s.title}" and all its stems? This can't be undone.`)) return;
    this.deleting.set(s.track_id);
    this.api.deleteSong(s.track_id).subscribe({
      next: () => { this.songs.update((list) => list.filter((x) => x.track_id !== s.track_id)); this.deleting.set(null); },
      error: () => { this.deleting.set(null); this.refresh(); },
    });
  }

  statusLabel(s: Song): string {
    switch (s.status) {
      case 'capturing': return 'Recording…';
      case 'queued': return 'Queued';
      case 'separating': return 'Separating…';
      case 'done': return 'Ready';
      case 'error': return 'Error';
      default: return s.status;
    }
  }
}
