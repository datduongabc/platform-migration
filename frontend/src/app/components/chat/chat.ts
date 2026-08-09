import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ChatService, ChatMessage, Citation } from '../../services/chat.service';
import { FolderService, Folder } from '../../services/folder.service';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './chat.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatComponent implements OnInit {
  private readonly chatService = inject(ChatService);
  private readonly folderService = inject(FolderService);
  protected readonly authService = inject(AuthService);
  private readonly router = inject(Router);

  // Chat states
  readonly sessionId = signal<string | null>(null);
  readonly messages = signal<ChatMessage[]>([]);
  readonly chatLoading = signal<boolean>(false);
  readonly chatError = signal<string | null>(null);

  // Scope: '' = global (every accessible meeting), else a folder id
  readonly folders = signal<Folder[]>([]);
  selectedFolderId = '';

  chatQuery: string = '';

  ngOnInit(): void {
    this.folderService.listFolders().subscribe({
      next: (res) => this.folders.set(res.folders),
      error: () => {
        // Non-fatal: scope picker just stays global-only.
      },
    });
    this.loadHistory();
  }

  onScopeChange(): void {
    this.sessionId.set(null);
    this.messages.set([]);
    this.loadHistory();
  }

  loadHistory(): void {
    this.chatLoading.set(true);
    this.chatError.set(null);
    this.chatService.getHistory(null, this.selectedFolderId || null).subscribe({
      next: (res) => {
        this.sessionId.set(res.sessionId);
        this.messages.set(res.messages);
        this.chatLoading.set(false);
      },
      error: (err) => {
        this.chatError.set(err.error?.detail || 'Failed to load chat history.');
        this.chatLoading.set(false);
      },
    });
  }

  sendMessage(): void {
    const text = this.chatQuery.trim();
    if (!text || this.chatLoading()) return;

    // Optimistically push user message
    const tempUserMsg: ChatMessage = {
      id: '',
      session_id: this.sessionId() || '',
      role: 'user',
      content: text,
      citations: [],
      created_at: new Date().toISOString(),
    };
    this.messages.update((prev) => [...prev, tempUserMsg]);
    this.chatQuery = '';

    this.chatLoading.set(true);
    this.chatError.set(null);

    this.chatService.sendQuery(text, null, this.sessionId(), this.selectedFolderId || null).subscribe({
      next: (res) => {
        this.sessionId.set(res.sessionId);
        // Replace temp messages and add real assistant message
        this.messages.update((prev) => {
          const filtered = prev.filter((m) => m.id !== ''); // clear temp msg
          // Push real user message
          const realUser: ChatMessage = {
            id: 'real-user',
            session_id: res.sessionId,
            role: 'user',
            content: text,
            citations: [],
            created_at: new Date().toISOString(),
          };
          return [...filtered, realUser, res.message];
        });
        this.chatLoading.set(false);
      },
      error: (err) => {
        this.chatError.set(err.error?.detail || 'Failed to send query.');
        this.chatLoading.set(false);
      },
    });
  }

  formatTime(ms: number): string {
    const totalSecs = Math.floor(ms / 1000);
    const mins = Math.floor(totalSecs / 60);
    const secs = totalSecs % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }

  handleCitationClick(cite: Citation): void {
    // Navigate user directly to meeting details view
    this.router.navigate(['/meetings', cite.meeting_id]);
  }

  renderMarkdown(md: string | null | undefined): string {
    if (!md) return '';
    let html = md
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Line breaks
    html = html.replace(/\n/g, '<br/>');

    return html;
  }
}
