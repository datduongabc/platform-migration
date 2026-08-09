import { inject, Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { ApiConfiguration } from '../api/api-configuration';

export interface MeetingCreateRequest {
  durationSeconds?: number;
  startedAt?: string;
  source?: string;
  fileExtension?: string;
  mimeType?: string;
  folderId?: string | null;
}

export interface MeetingCreateResponse {
  meetingId: string;
  uploadUrl: string;
  contentType: string;
}

export interface TranscriptSegment {
  id: string;
  segment_index: number;
  speaker: string | null;
  start_ms: number;
  end_ms: number;
  text: string;
  confidence: number | null;
  created_at: string;
}

export interface Todo {
  id: string;
  content: string;
  assignee: string | null;
  due_date: string | null;
  status: 'open' | 'done' | 'dismissed';
  source_segment_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface CalendarSuggestion {
  id: string;
  title: string;
  proposed_at: string | null;
  raw_mention: string | null;
  source_segment_id: string | null;
  dismissed: boolean;
  created_at: string;
}

export interface MeetingDetail {
  id: string;
  user_id: string;
  title: string;
  status: 'pending' | 'processing' | 'done' | 'failed';
  audio_path: string | null;
  duration_seconds: number | null;
  language: string | null;
  summary: string | null;
  notes: string | null;
  error_message: string | null;
  started_at: string | null;
  created_at: string;
  updated_at: string;
  pinned_at: string | null;
  source: string | null;
  storage_provider: string | null;
  folder_id: string | null;
  segments: TranscriptSegment[];
  todos: Todo[];
  calendar_suggestions: CalendarSuggestion[];
}

@Injectable({
  providedIn: 'root',
})
export class MeetingService {
  private readonly http = inject(HttpClient);
  private readonly config = inject(ApiConfiguration);

  private get base(): string {
    return this.config.rootUrl;
  }

  createMeeting(payload: MeetingCreateRequest): Observable<MeetingCreateResponse> {
    return this.http.post<MeetingCreateResponse>(`${this.base}/meetings`, payload);
  }

  uploadFile(uploadUrl: string, blob: Blob, contentType: string): Observable<any> {
    const headers = new HttpHeaders({ 'Content-Type': contentType });
    return this.http.put(uploadUrl, blob, { headers });
  }

  confirmUploaded(meetingId: string): Observable<any> {
    return this.http.post(`${this.base}/meetings/${meetingId}/uploaded`, {});
  }

  getMeetingDetail(meetingId: string): Observable<MeetingDetail> {
    return this.http.get<MeetingDetail>(`${this.base}/meetings/${meetingId}`);
  }

  updateMeeting(meetingId: string, payload: { title?: string; folder_id?: string | null }): Observable<any> {
    return this.http.patch(`${this.base}/meetings/${meetingId}`, payload);
  }

  pinMeeting(meetingId: string): Observable<any> {
    return this.http.patch(`${this.base}/meetings/${meetingId}/pin`, {});
  }

  deleteMeeting(meetingId: string): Observable<any> {
    return this.http.delete(`${this.base}/meetings/${meetingId}`);
  }

  getAudioUrl(meetingId: string): Observable<{ url: string }> {
    return this.http.get<{ url: string }>(`${this.base}/audio-url/${meetingId}`);
  }

  processMeeting(meetingId: string): Observable<any> {
    return this.http.post(`${this.base}/meetings/${meetingId}/process`, {});
  }

  regenerateAnalysis(meetingId: string): Observable<{ ok: boolean; summary: string; notes: string }> {
    return this.http.post<{ ok: boolean; summary: string; notes: string }>(
      `${this.base}/meetings/${meetingId}/regenerate`,
      {}
    );
  }

  updateTodo(todoId: string, status: 'open' | 'done' | 'dismissed'): Observable<any> {
    return this.http.patch(`${this.base}/todos/${todoId}`, { status });
  }

  dismissCalendarSuggestion(suggestionId: string): Observable<any> {
    return this.http.patch(`${this.base}/calendar-suggestions/${suggestionId}`, { dismissed: true });
  }

  downloadIcs(suggestionId: string): Observable<Blob> {
    return this.http.get(`${this.base}/calendar-suggestions/${suggestionId}/ics`, {
      responseType: 'blob',
    });
  }

  askQuestion(meetingId: string, query: string): Observable<{ answer: string; sources: any[] }> {
    return this.http.post<{ answer: string; sources: any[] }>(`${this.base}/meetings/${meetingId}/ask`, { query });
  }
}
