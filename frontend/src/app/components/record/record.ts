import { ChangeDetectionStrategy, ChangeDetectorRef, Component, inject, OnInit, OnDestroy, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink, ActivatedRoute } from '@angular/router';
import { RecorderService, TrackInfo } from '../../services/recorder.service';
import { MeetingService } from '../../services/meeting.service';
import { FolderService, Folder, FolderListResponse } from '../../services/folder.service';

export type RecordingUIState = 'idle' | 'recording' | 'stopped' | 'error';
export type UploadUIState = 'idle' | 'uploading' | 'done' | 'error';

@Component({
  selector: 'app-record',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './record.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RecordComponent implements OnInit, OnDestroy {
  private readonly recorderService = inject(RecorderService);
  private readonly meetingService = inject(MeetingService);
  private readonly folderService = inject(FolderService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly cdr = inject(ChangeDetectorRef);

  // Recorder states
  readonly state = signal<RecordingUIState>('idle');
  readonly elapsedSeconds = signal<number>(0);
  readonly blob = signal<Blob | null>(null);
  readonly objectUrl = signal<string | null>(null);
  readonly mimeType = signal<string | null>(null);
  readonly trackInfo = signal<TrackInfo | null>(null);
  readonly error = signal<string | null>(null);
  readonly supported = signal<boolean>(false);
  missingCapabilities: string[] = [];

  // Upload/Saving states
  readonly uploadState = signal<UploadUIState>('idle');
  readonly uploadError = signal<string | null>(null);
  readonly createdMeetingId = signal<string | null>(null);
  
  // Folder pick
  folders = signal<Folder[]>([]);
  folderId: string | null = null;
  startedAt: string | null = null;

  // MediaRecorder refs
  private mediaRecorder: MediaRecorder | null = null;
  private getBlobFn: (() => Blob) | null = null;
  private micStream: MediaStream | null = null;
  private displayStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private timer: any = null;
  private startTime = 0;

  ngOnInit(): void {
    const support = this.recorderService.checkRecordingSupport();
    this.supported.set(support.supported);
    this.missingCapabilities = support.missingCapabilities;

    // Read initial folder from query param. folderId is a plain (non-signal)
    // field, and under OnPush a later emission on this route (no full component
    // recreation) wouldn't otherwise be picked up by change detection.
    this.route.queryParams.subscribe((params) => {
      if (params['folder']) {
        this.folderId = params['folder'];
        this.cdr.markForCheck();
      }
    });

    this.loadFolders();
  }

  loadFolders(): void {
    this.folderService.listFolders().subscribe({
      next: (res: FolderListResponse) => {
        // Filter folders where user has owner or editor role to allow adding meetings
        const writeable = res.folders.filter((f: Folder) => f.myRole === 'owner' || f.myRole === 'editor');
        this.folders.set(writeable);
      }
    });
  }

  async startRecording(): Promise<void> {
    if (this.state() !== 'idle') return;
    this.error.set(null);
    this.blob.set(null);
    this.objectUrl.set(null);
    this.elapsedSeconds.set(0);
    this.startedAt = new Date().toISOString();

    try {
      const { micStream, displayStream } = await this.recorderService.startCapture();
      this.micStream = micStream;
      this.displayStream = displayStream;

      const mix = this.recorderService.mixToMonoAudioStream(displayStream, micStream);
      this.audioContext = mix.audioContext;

      if (mix.audioContext.state === 'suspended') {
        await mix.audioContext.resume();
      }

      this.trackInfo.set({
        hasMic: micStream.getAudioTracks().length > 0,
        hasDisplayAudio: mix.hasDisplayAudio,
      });

      const kit = this.recorderService.createRecorder(mix.mixedStream);
      this.mediaRecorder = kit.recorder;
      this.getBlobFn = kit.getBlob;
      this.mimeType.set(kit.mimeType);

      // Handle recorder stopped
      this.mediaRecorder.onstop = () => {
        const result = this.getBlobFn ? this.getBlobFn() : new Blob();
        const url = URL.createObjectURL(result);
        
        this.blob.set(result);
        this.objectUrl.set(url);
        this.cleanup();
        this.state.set('stopped');
      };

      // Native "Stop sharing" event listener
      const handleEnded = () => {
        if (this.mediaRecorder?.state === 'recording') {
          this.stopRecording();
        }
      };

      displayStream.getTracks().forEach((t) => {
        t.addEventListener('ended', handleEnded);
      });

      this.mediaRecorder.start(250);
      this.startTime = Date.now();
      this.state.set('recording');

      this.timer = setInterval(() => {
        this.elapsedSeconds.set(Math.floor((Date.now() - this.startTime) / 1000));
      }, 500);
    } catch (err: any) {
      this.cleanup();
      const msg = this.formatError(err);
      this.error.set(msg);
      this.state.set('error');
    }
  }

  stopRecording(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    if (this.mediaRecorder?.state === 'recording') {
      this.mediaRecorder.stop();
    }
  }

  resetRecorder(): void {
    this.revokeUrl();
    this.blob.set(null);
    this.mimeType.set(null);
    this.trackInfo.set(null);
    this.error.set(null);
    this.elapsedSeconds.set(0);
    this.createdMeetingId.set(null);
    this.uploadState.set('idle');
    this.uploadError.set(null);
    this.state.set('idle');
  }

  saveRecording(): void {
    const fileBlob = this.blob();
    if (!fileBlob) return;

    this.uploadState.set('uploading');
    this.uploadError.set(null);

    const ext = this.mimeType()?.split('/')[1]?.split(';')[0] || 'webm';

    const cleanFolderId = (this.folderId && this.folderId !== 'null' && this.folderId !== 'uncategorized') ? this.folderId : null;

    this.meetingService.createMeeting({
      durationSeconds: this.elapsedSeconds(),
      startedAt: this.startedAt || new Date().toISOString(),
      source: 'recorded',
      fileExtension: ext,
      mimeType: this.mimeType() || 'audio/webm',
      folderId: cleanFolderId,
    }).subscribe({
      next: (res) => {
        this.meetingService.uploadFile(res.uploadUrl, fileBlob, res.contentType).subscribe({
          next: () => {
            this.meetingService.confirmUploaded(res.meetingId).subscribe({
              next: () => {
                this.createdMeetingId.set(res.meetingId);
                this.uploadState.set('done');
              },
              error: (err) => {
                this.uploadState.set('error');
                this.uploadError.set(err.error?.detail || 'Failed to confirm uploaded file.');
              }
            });
          },
          error: () => {
            this.uploadState.set('error');
            this.uploadError.set('Failed to upload recording audio file bytes.');
          }
        });
      },
      error: (err) => {
        this.uploadState.set('error');
        this.uploadError.set(err.error?.detail || 'Failed to create meeting metadata.');
      }
    });
  }

  changeRecordingFolder(targetFolderId: string | null): void {
    const meetingId = this.createdMeetingId();
    if (!meetingId) return;

    const folderVal = targetFolderId === 'null' ? null : targetFolderId;
    this.folderId = folderVal;

    this.meetingService.updateMeeting(meetingId, { folder_id: folderVal }).subscribe({
      error: (err) => alert(err.error?.detail || 'Failed to move meeting to folder.')
    });
  }

  formatTime(seconds: number): string {
    const m = Math.floor(seconds / 60).toString().padStart(2, '0');
    const s = (seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  }

  private revokeUrl(): void {
    const url = this.objectUrl();
    if (url) {
      URL.revokeObjectURL(url);
      this.objectUrl.set(null);
    }
  }

  private cleanup(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.micStream?.getTracks().forEach((t) => t.stop());
    this.displayStream?.getTracks().forEach((t) => t.stop());
    void this.audioContext?.close();
    
    this.micStream = null;
    this.displayStream = null;
    this.audioContext = null;
  }

  private formatError(err: any): string {
    if (!err || !err.name) return String(err);
    switch (err.name) {
      case 'NotAllowedError':
        return 'Permission denied — allow microphone and screen audio sharing, then try again.';
      case 'NotFoundError':
        return 'No microphone found — connect a microphone and try again.';
      case 'AbortError':
        return 'Screen sharing was cancelled.';
      case 'InvalidStateError':
        return 'Media recorder entered an invalid state — reset and try again.';
      default:
        return err.message || 'An unexpected error occurred.';
    }
  }

  ngOnDestroy(): void {
    this.revokeUrl();
    this.cleanup();
  }
}
