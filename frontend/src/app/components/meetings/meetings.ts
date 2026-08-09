import { DatePipe, CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, OnInit, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { ProjectsByUserService } from '../../api/services/projects-by-user.service';
import { AuthService } from '../../services/auth.service';
import { MeetingService } from '../../services/meeting.service';
import { FolderService, Folder, FolderMember } from '../../services/folder.service';

@Component({
  selector: 'app-meetings',
  standalone: true,
  imports: [DatePipe, CommonModule, RouterLink, FormsModule],
  templateUrl: './meetings.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MeetingsComponent implements OnInit {
  protected readonly authService = inject(AuthService);
  private readonly projectService = inject(ProjectsByUserService);
  private readonly meetingService = inject(MeetingService);
  private readonly folderService = inject(FolderService);
  private readonly router = inject(Router);

  // Pagination signals
  skip = signal(0);
  limit = signal(10);

  // File Upload states
  selectedFile = signal<File | null>(null);
  uploadState = signal<'idle' | 'uploading' | 'done' | 'error'>('idle');
  uploadError = signal<string | null>(null);
  uploadedMeetingId = signal<string | null>(null);

  // Folders states
  folders = signal<Folder[]>([]);
  selectedFolderId = signal<string | null>(null); // null = All, 'uncategorized' = Uncategorized, UUID = Folder

  // Folder Operations
  showNewFolderInput = signal<boolean>(false);
  newFolderName = '';
  newFolderError = signal<string | null>(null);
  newFolderBusy = signal<boolean>(false);

  renamingFolder = signal<Folder | null>(null);
  renameFolderName = '';
  renameFolderError = signal<string | null>(null);

  folderConfirmDelete = signal<Folder | null>(null);
  folderBusy = signal<string | null>(null);

  // Sharing states
  showShareModal = signal<boolean>(false);
  sharingFolder = signal<Folder | null>(null);
  shareMembers = signal<FolderMember[]>([]);
  shareBusy = signal<boolean>(false);
  shareError = signal<string | null>(null);
  shareIdentifier = '';
  shareRole = signal<'editor' | 'viewer'>('viewer');
  addShareBusy = signal<boolean>(false);

  // Computed parameters for request
  requestParams = computed(() => ({
    skip: this.skip(),
    limit: this.limit(),
  }));

  // Resource for managing asynchronous data fetching
  meetingsResource = rxResource({
    params: () => this.requestParams(),
    stream: ({ params }) => this.projectService.listUserProjectsProjectsGet(params),
  });

  // Derived signals
  projects = computed(() => this.meetingsResource.value() || []);
  
  // Filtered projects client-side based on selected folder
  filteredProjects = computed(() => {
    const list = this.projects();
    const folderId = this.selectedFolderId();
    if (!folderId) return list;
    if (folderId === 'uncategorized') {
      return list.filter((p: any) => p.folder_id === null);
    }
    return list.filter((p: any) => p.folder_id === folderId);
  });

  loading = computed(() => this.meetingsResource.isLoading());
  error = computed(() => {
    const err: any = this.meetingsResource.error();
    if (!err) return null;
    return err.error?.detail || 'Failed to load meetings.';
  });

  currentPage = computed(() => Math.floor(this.skip() / this.limit()) + 1);

  ngOnInit(): void {
    this.loadFolders();
  }

  loadProjects(): void {
    this.meetingsResource.reload();
  }

  formatDuration(seconds: number | null | undefined): string {
    if (seconds == null) return '00:00';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }

  prevPage(): void {
    if (this.skip() > 0) {
      this.skip.update((s) => Math.max(0, s - this.limit()));
    }
  }

  nextPage(): void {
    this.skip.update((s) => s + this.limit());
  }

  handleLogout(): void {
    this.authService.logout().subscribe(() => {
      this.router.navigate(['/login']);
    });
  }

  // ── Folders I/O ────────────────────────────────────────────────────────────
  loadFolders(): void {
    this.folderService.listFolders().subscribe({
      next: (res) => {
        this.folders.set(res.folders);
      },
      error: (err) => {
        console.error('Failed to load folders:', err);
      },
    });
  }

  createFolder(): void {
    const name = this.newFolderName.trim();
    if (!name) return;
    this.newFolderBusy.set(true);
    this.newFolderError.set(null);

    this.folderService.createFolder(name).subscribe({
      next: (f) => {
        this.folders.update((prev) => [...prev, f]);
        this.newFolderName = '';
        this.showNewFolderInput.set(false);
        this.newFolderBusy.set(false);
      },
      error: (err) => {
        this.newFolderError.set(err.error?.detail || 'Failed to create folder.');
        this.newFolderBusy.set(false);
      },
    });
  }

  startRename(folder: Folder): void {
    this.renamingFolder.set(folder);
    this.renameFolderName = folder.name;
    this.renameFolderError.set(null);
  }

  saveRename(): void {
    const folder = this.renamingFolder();
    const name = this.renameFolderName.trim();
    if (!folder || !name) return;

    this.folderBusy.set(folder.id);
    this.renameFolderError.set(null);

    this.folderService.renameFolder(folder.id, name).subscribe({
      next: (updated) => {
        this.folders.update((prev) =>
          prev.map((f) => (f.id === folder.id ? { ...f, name: updated.name } : f))
        );
        this.renamingFolder.set(null);
        this.folderBusy.set(null);
      },
      error: (err) => {
        this.renameFolderError.set(err.error?.detail || 'Failed to rename folder.');
        this.folderBusy.set(null);
      },
    });
  }

  deleteFolder(deleteMeetings: boolean): void {
    const folder = this.folderConfirmDelete();
    if (!folder) return;

    this.folderBusy.set(folder.id);
    this.folderService.deleteFolder(folder.id, deleteMeetings).subscribe({
      next: () => {
        this.folders.update((prev) => prev.filter((f) => f.id !== folder.id));
        this.folderConfirmDelete.set(null);
        this.folderBusy.set(null);
        this.loadProjects(); // reload meetings in case they changed status/folder
      },
      error: (err) => {
        alert(err.error?.detail || 'Failed to delete folder.');
        this.folderBusy.set(null);
      },
    });
  }

  moveFolderUp(index: number): void {
    if (index === 0) return;
    const list = [...this.folders()];
    const temp = list[index];
    list[index] = list[index - 1];
    list[index - 1] = temp;
    this.folders.set(list);
    this.saveFolderOrder();
  }

  moveFolderDown(index: number): void {
    if (index === this.folders().length - 1) return;
    const list = [...this.folders()];
    const temp = list[index];
    list[index] = list[index + 1];
    list[index + 1] = temp;
    this.folders.set(list);
    this.saveFolderOrder();
  }

  private saveFolderOrder(): void {
    const order = this.folders().map((f) => f.id);
    this.folderService.reorderFolders(order).subscribe({
      error: (err) => console.error('Failed to save folder order:', err),
    });
  }

  // ── Folder Sharing ─────────────────────────────────────────────────────────
  openShareModal(folder: Folder): void {
    this.sharingFolder.set(folder);
    this.showShareModal.set(true);
    this.shareMembers.set([]);
    this.shareError.set(null);
    this.shareIdentifier = '';
    this.shareBusy.set(true);

    this.folderService.listShares(folder.id).subscribe({
      next: (res) => {
        this.shareMembers.set(res.members);
        this.shareBusy.set(false);
      },
      error: (err) => {
        this.shareError.set(err.error?.detail || 'Failed to load shares.');
        this.shareBusy.set(false);
      },
    });
  }

  addShareMember(): void {
    const folder = this.sharingFolder();
    const identifier = this.shareIdentifier.trim();
    if (!folder || !identifier) return;

    this.addShareBusy.set(true);
    this.shareError.set(null);

    this.folderService.addShare(folder.id, identifier, this.shareRole()).subscribe({
      next: (member) => {
        this.shareMembers.update((prev) => [...prev, member]);
        this.shareIdentifier = '';
        this.addShareBusy.set(false);
        this.folders.update((prev) =>
          prev.map((f) => (f.id === folder.id ? { ...f, memberCount: f.memberCount + 1 } : f))
        );
      },
      error: (err) => {
        this.shareError.set(err.error?.detail || 'Failed to share folder.');
        this.addShareBusy.set(false);
      },
    });
  }

  changeShareRole(member: FolderMember, role: 'editor' | 'viewer'): void {
    const folder = this.sharingFolder();
    if (!folder) return;

    this.folderService.updateShare(folder.id, member.userId, role).subscribe({
      next: () => {
        this.shareMembers.update((prev) =>
          prev.map((m) => (m.userId === member.userId ? { ...m, role } : m))
        );
      },
      error: (err) => {
        alert(err.error?.detail || 'Failed to update share role.');
      },
    });
  }

  removeShareMember(member: FolderMember): void {
    const folder = this.sharingFolder();
    if (!folder) return;

    this.folderService.removeShare(folder.id, member.userId).subscribe({
      next: () => {
        this.shareMembers.update((prev) => prev.filter((m) => m.userId !== member.userId));
        this.folders.update((prev) =>
          prev.map((f) => (f.id === folder.id ? { ...f, memberCount: Math.max(0, f.memberCount - 1) } : f))
        );
      },
      error: (err) => {
        alert(err.error?.detail || 'Failed to remove member.');
      },
    });
  }

  // ── Upload Handlers ────────────────────────────────────────────────────────
  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      this.selectedFile.set(input.files[0]);
      this.uploadState.set('idle');
      this.uploadError.set(null);
      this.uploadedMeetingId.set(null);
    }
  }

  triggerUpload(): void {
    const file = this.selectedFile();
    if (!file) return;

    this.uploadState.set('uploading');
    this.uploadError.set(null);

    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();

    const rawFolderId = this.selectedFolderId();
    const folderId = (rawFolderId && rawFolderId !== 'all' && rawFolderId !== 'uncategorized') ? rawFolderId : null;

    this.meetingService.createMeeting({
      durationSeconds: 0,
      startedAt: new Date().toISOString(),
      source: 'uploaded',
      fileExtension: ext,
      mimeType: file.type || 'audio/webm',
      folderId: folderId,
    }).subscribe({
      next: (res) => {
        this.meetingService.uploadFile(res.uploadUrl, file, res.contentType).subscribe({
          next: () => {
            this.meetingService.confirmUploaded(res.meetingId).subscribe({
              next: () => {
                this.uploadState.set('done');
                this.uploadedMeetingId.set(res.meetingId);
                this.selectedFile.set(null);
                this.loadProjects();
              },
              error: (err) => {
                this.uploadState.set('error');
                this.uploadError.set(err.error?.detail || 'Failed to confirm file upload.');
              }
            });
          },
          error: (err) => {
            this.uploadState.set('error');
            this.uploadError.set('Failed to upload file bytes.');
          }
        });
      },
      error: (err) => {
        this.uploadState.set('error');
        this.uploadError.set(err.error?.detail || 'Failed to create meeting metadata.');
      }
    });
  }

  resetUpload(): void {
    this.selectedFile.set(null);
    this.uploadState.set('idle');
    this.uploadError.set(null);
    this.uploadedMeetingId.set(null);
  }

  moveMeeting(meetingId: string, folderIdRaw: string | null): void {
    const folderId = (folderIdRaw === 'null' || !folderIdRaw) ? null : folderIdRaw;
    this.meetingService.updateMeeting(meetingId, { folder_id: folderId }).subscribe({
      next: () => {
        this.loadProjects();
      },
      error: (err) => {
        alert(err.error?.detail || 'Failed to move meeting.');
      }
    });
  }

  deleteMeeting(meetingId: string, event?: Event): void {
    if (event) event.stopPropagation();
    if (confirm('Are you sure you want to delete this meeting? This action cannot be undone.')) {
      this.meetingService.deleteMeeting(meetingId).subscribe({
        next: () => {
          this.loadProjects();
        },
        error: (err) => {
          alert(err.error?.detail || 'Failed to delete meeting.');
        }
      });
    }
  }
}
