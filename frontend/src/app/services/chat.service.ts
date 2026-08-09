import { inject, Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { ApiConfiguration } from '../api/api-configuration';

export interface Citation {
  chunk_id: string;
  meeting_id: string;
  start_ms: number;
  end_ms: number;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[];
  created_at: string;
}

export interface ChatHistoryResponse {
  sessionId: string | null;
  messages: ChatMessage[];
}

export interface ChatResponse {
  sessionId: string;
  message: ChatMessage;
}

@Injectable({
  providedIn: 'root',
})
export class ChatService {
  private readonly http = inject(HttpClient);
  private readonly config = inject(ApiConfiguration);

  private get base(): string {
    return this.config.rootUrl;
  }

  getHistory(meetingId?: string | null, folderId?: string | null): Observable<ChatHistoryResponse> {
    let params = new HttpParams();
    if (meetingId) {
      params = params.set('meetingId', meetingId);
    } else if (folderId) {
      params = params.set('folderId', folderId);
    }
    return this.http.get<ChatHistoryResponse>(`${this.base}/chat/history`, { params });
  }

  sendQuery(
    message: string,
    meetingId?: string | null,
    sessionId?: string | null,
    folderId?: string | null,
  ): Observable<ChatResponse> {
    const payload: any = { message };
    if (meetingId) payload.meetingId = meetingId;
    else if (folderId) payload.folderId = folderId;
    if (sessionId) payload.sessionId = sessionId;
    return this.http.post<ChatResponse>(`${this.base}/chat`, payload);
  }
}
