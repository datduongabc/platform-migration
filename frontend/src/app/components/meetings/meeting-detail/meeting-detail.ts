import { ChangeDetectionStrategy, Component, ElementRef, inject, OnDestroy, OnInit, signal, ViewChild, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { Subscription, interval } from 'rxjs';
import { switchMap, takeWhile } from 'rxjs/operators';
import { MeetingDetail, MeetingService, Todo, CalendarSuggestion } from '../../../services/meeting.service';
import { AuthService } from '../../../services/auth.service';
import { FolderService, Folder } from '../../../services/folder.service';

@Component({
  selector: 'app-meeting-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './meeting-detail.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MeetingDetailComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  readonly meetingService = inject(MeetingService);
  readonly authService = inject(AuthService);
  private readonly folderService = inject(FolderService);

  @ViewChild('audioPlayer') audioPlayer!: ElementRef<HTMLAudioElement>;

  // Folders list
  readonly folders = signal<Folder[]>([]);

  // Component states
  readonly meeting = signal<MeetingDetail | null>(null);
  readonly state = signal<'loading' | 'error' | 'inflight' | 'failed' | 'done'>('loading');
  readonly errorMessage = signal<string | null>(null);
  readonly audioUrl = signal<string | null>(null);

  // UI state variables
  readonly editingTitle = signal<boolean>(false);
  titleDraft: string = '';
  readonly actionBusy = signal<boolean>(false);
  readonly regenLoading = signal<boolean>(false);

  // Chat Q&A state
  readonly chatOpen = signal<boolean>(false);
  chatQuery: string = '';
  readonly chatLoading = signal<boolean>(false);
  readonly chatMessages = signal<Array<{ role: 'user' | 'assistant'; content: string }>>([]);

  // Computed fields
  readonly renderedNotes = computed(() => this.renderMarkdown(this.meeting()?.notes));
  
  readonly activeTodos = computed(() => {
    const m = this.meeting();
    if (!m || !m.todos) return [];
    return m.todos.filter((t) => t.status !== 'dismissed');
  });

  readonly activeSuggestions = computed(() => {
    const m = this.meeting();
    if (!m || !m.calendar_suggestions) return [];
    return m.calendar_suggestions.filter((s) => !s.dismissed);
  });

  private meetingId: string | null = null;
  private pollerSubscription?: Subscription;

  ngOnInit(): void {
    this.meetingId = this.route.snapshot.paramMap.get('id');
    if (!this.meetingId) {
      this.state.set('error');
      this.errorMessage.set('Meeting ID is missing from path.');
      return;
    }
    this.loadMeetingData();
    this.loadFolders();
  }

  ngOnDestroy(): void {
    this.stopPoller();
  }

  loadMeetingData(): void {
    if (!this.meetingId) return;

    this.meetingService.getMeetingDetail(this.meetingId).subscribe({
      next: (m) => {
        this.meeting.set(m);
        this.titleDraft = m.title;

        if (m.status === 'pending' || m.status === 'processing') {
          this.state.set('inflight');
          this.startPoller();
        } else if (m.status === 'failed') {
          this.state.set('failed');
          this.stopPoller();
        } else {
          this.state.set('done');
          this.stopPoller();
          this.loadAudioUrl();
        }
      },
      error: (err) => {
        console.error('Failed to load meeting details:', err);
        this.state.set('error');
        this.errorMessage.set(err.error?.detail || 'Failed to load meeting details.');
      },
    });
  }

  private loadAudioUrl(): void {
    if (!this.meetingId) return;
    this.meetingService.getAudioUrl(this.meetingId).subscribe({
      next: (res) => {
        this.audioUrl.set(res.url);
      },
      error: (err) => {
        console.warn('Failed to load audio playback URL:', err);
      },
    });
  }

  private startPoller(): void {
    if (this.pollerSubscription) return;

    this.pollerSubscription = interval(4000)
      .pipe(
        switchMap(() => this.meetingService.getMeetingDetail(this.meetingId!))
      )
      .subscribe({
        next: (m) => {
          this.meeting.set(m);
          if (m.status === 'done') {
            this.state.set('done');
            this.stopPoller();
            this.loadAudioUrl();
          } else if (m.status === 'failed') {
            this.state.set('failed');
            this.stopPoller();
          }
        },
        error: (err) => {
          console.error('Polling error:', err);
        },
      });
  }

  private stopPoller(): void {
    if (this.pollerSubscription) {
      this.pollerSubscription.unsubscribe();
      this.pollerSubscription = undefined;
    }
  }

  // Seek audio player to time
  seekTo(ms: number): void {
    if (this.audioPlayer && this.audioPlayer.nativeElement) {
      this.audioPlayer.nativeElement.currentTime = ms / 1000;
      this.audioPlayer.nativeElement.play().catch(() => {});
    }
  }

  formatTimeMs(ms: number): string {
    const totalSeconds = Math.floor(ms / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    const pad = (n: number) => n.toString().padStart(2, '0');
    if (hours > 0) {
      return `${hours}:${pad(minutes)}:${pad(seconds)}`;
    }
    return `${minutes}:${pad(seconds)}`;
  }

  formatDuration(seconds: number | null): string {
    if (seconds == null) return '';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) {
      return `${h}h ${m}m`;
    }
    if (m > 0) {
      return `${m}m ${s}s`;
    }
    return `${s}s`;
  }

  startEditingTitle(): void {
    const m = this.meeting();
    if (m) {
      this.titleDraft = m.title;
      this.editingTitle.set(true);
    }
  }

  saveTitle(): void {
    if (!this.meetingId || !this.titleDraft.trim()) return;
    this.actionBusy.set(true);
    this.meetingService.updateMeeting(this.meetingId, { title: this.titleDraft }).subscribe({
      next: () => {
        const m = this.meeting();
        if (m) {
          this.meeting.set({ ...m, title: this.titleDraft });
        }
        this.editingTitle.set(false);
        this.actionBusy.set(false);
      },
      error: (err) => {
        alert(err.error?.detail || 'Failed to rename meeting.');
        this.actionBusy.set(false);
      },
    });
  }

  togglePin(): void {
    if (!this.meetingId) return;
    this.actionBusy.set(true);
    this.meetingService.pinMeeting(this.meetingId).subscribe({
      next: (res) => {
        const m = this.meeting();
        if (m) {
          this.meeting.set({ ...m, pinned_at: res.pinned ? new Date().toISOString() : null });
        }
        this.actionBusy.set(false);
      },
      error: (err) => {
        alert(err.error?.detail || 'Failed to toggle pin.');
        this.actionBusy.set(false);
      },
    });
  }

  confirmDelete(): void {
    if (!this.meetingId) return;
    if (confirm('Are you sure you want to delete this meeting? This cannot be undone.')) {
      this.actionBusy.set(true);
      this.meetingService.deleteMeeting(this.meetingId).subscribe({
        next: () => {
          this.router.navigate(['/meetings']);
        },
        error: (err) => {
          alert(err.error?.detail || 'Failed to delete meeting.');
          this.actionBusy.set(false);
        },
      });
    }
  }

  rerunProcessing(): void {
    if (!this.meetingId) return;
    this.actionBusy.set(true);
    this.meetingService.processMeeting(this.meetingId).subscribe({
      next: () => {
        this.actionBusy.set(false);
        this.loadMeetingData();
      },
      error: (err) => {
        alert(err.error?.detail || 'Failed to start processing.');
        this.actionBusy.set(false);
      },
    });
  }

  regenerateAnalysis(): void {
    if (!this.meetingId) return;
    this.regenLoading.set(true);
    this.meetingService.regenerateAnalysis(this.meetingId).subscribe({
      next: (res) => {
        this.regenLoading.set(false);
        this.loadMeetingData();
      },
      error: (err) => {
        alert(err.error?.detail || 'Failed to regenerate analysis.');
        this.regenLoading.set(false);
      },
    });
  }

  toggleTodo(todo: Todo): void {
    const newStatus: 'open' | 'done' = todo.status === 'done' ? 'open' : 'done';
    this.meetingService.updateTodo(todo.id, newStatus).subscribe({
      next: () => {
        const m = this.meeting();
        if (m) {
          const updatedTodos = m.todos.map((t) => (t.id === todo.id ? { ...t, status: newStatus } : t));
          this.meeting.set({ ...m, todos: updatedTodos });
        }
      },
      error: (err) => {
        alert('Failed to update action item status.');
      },
    });
  }

  dismissTodo(todoId: string): void {
    this.meetingService.updateTodo(todoId, 'dismissed').subscribe({
      next: () => {
        const m = this.meeting();
        if (m) {
          const updatedTodos = m.todos.map((t) => (t.id === todoId ? { ...t, status: 'dismissed' as const } : t));
          this.meeting.set({ ...m, todos: updatedTodos });
        }
      },
      error: (err) => {
        alert('Failed to dismiss action item.');
      },
    });
  }

  dismissSuggestion(suggestionId: string): void {
    this.meetingService.dismissCalendarSuggestion(suggestionId).subscribe({
      next: () => {
        const m = this.meeting();
        if (m) {
          const updatedSug = m.calendar_suggestions.map((s) => (s.id === suggestionId ? { ...s, dismissed: true } : s));
          this.meeting.set({ ...m, calendar_suggestions: updatedSug });
        }
      },
      error: (err) => {
        alert('Failed to dismiss suggestion.');
      },
    });
  }

  downloadIcs(sug: CalendarSuggestion): void {
    this.meetingService.downloadIcs(sug.id).subscribe({
      next: (blob) => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `event-${sug.id}.ics`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
      },
      error: (err) => {
        alert('Failed to download calendar invite.');
      },
    });
  }

  toggleChat(): void {
    this.chatOpen.update((v) => !v);
  }

  sendQuestion(event: Event): void {
    event.preventDefault();
    if (!this.meetingId || !this.chatQuery.trim() || this.chatLoading()) return;

    const query = this.chatQuery.trim();
    this.chatQuery = '';

    // Append user message
    this.chatMessages.update((msgs) => [...msgs, { role: 'user', content: query }]);
    this.chatLoading.set(true);

    this.meetingService.askQuestion(this.meetingId, query).subscribe({
      next: (res) => {
        this.chatMessages.update((msgs) => [...msgs, { role: 'assistant', content: res.answer }]);
        this.chatLoading.set(false);
      },
      error: (err) => {
        this.chatMessages.update((msgs) => [
          ...msgs,
          { role: 'assistant', content: 'Sorry, I failed to connect to the Q&A service. Please check your network connection.' },
        ]);
        this.chatLoading.set(false);
      },
    });
  }

  renderMarkdown(md: string | null | undefined): string {
    if (!md) return '';
    // Simple escapes
    let html = md
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Bold: **text**
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Headers: # Header
    html = html.replace(/^# (.*?)$/gm, '<h1 class="text-xl font-bold font-serif my-3">$1</h1>');
    html = html.replace(/^## (.*?)$/gm, '<h2 class="text-lg font-bold font-serif my-2">$1</h2>');
    html = html.replace(/^### (.*?)$/gm, '<h3 class="text-md font-bold font-serif my-2">$1</h3>');

    // Lists: - item or * item
    html = html.replace(/^\s*[-*]\s+(.*?)$/gm, '<li class="ml-4 list-disc">$1</li>');

    // Line breaks
    html = html.replace(/\n/g, '<br/>');

    return html;
  }

  loadFolders(): void {
    this.folderService.listFolders().subscribe({
      next: (res) => {
        // Only allow folders where user has access (owner or editor)
        this.folders.set(res.folders.filter((f) => f.myRole === 'owner' || f.myRole === 'editor'));
      },
      error: (err) => console.warn('Failed to load folders for dropdown:', err)
    });
  }

  moveToFolder(targetFolderId: string | null): void {
    if (!this.meetingId) return;
    this.actionBusy.set(true);
    this.meetingService.updateMeeting(this.meetingId, { folder_id: targetFolderId }).subscribe({
      next: () => {
        const m = this.meeting();
        if (m) {
          this.meeting.set({ ...m, folder_id: targetFolderId });
        }
        this.actionBusy.set(false);
      },
      error: (err) => {
        alert(err.error?.detail || 'Failed to move meeting to folder.');
        this.actionBusy.set(false);
      }
    });
  }
}
