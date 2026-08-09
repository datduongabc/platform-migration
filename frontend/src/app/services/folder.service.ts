import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { ApiConfiguration } from '../api/api-configuration';

export interface Folder {
  id: string;
  user_id: string;
  name: string;
  position: number;
  created_at: string;
  updated_at: string;
  myRole: 'owner' | 'editor' | 'viewer';
  ownerUsername: string | null;
  memberCount: number;
}

export interface FolderListResponse {
  folders: Folder[];
}

export interface FolderMember {
  userId: string;
  username: string;
  role: 'editor' | 'viewer';
}

export interface FolderMemberListResponse {
  members: FolderMember[];
}

@Injectable({
  providedIn: 'root',
})
export class FolderService {
  private readonly http = inject(HttpClient);
  private readonly config = inject(ApiConfiguration);

  private get base(): string {
    return this.config.rootUrl;
  }

  listFolders(): Observable<FolderListResponse> {
    return this.http.get<FolderListResponse>(`${this.base}/folders`);
  }

  createFolder(name: string): Observable<Folder> {
    return this.http.post<Folder>(`${this.base}/folders`, { name });
  }

  reorderFolders(order: string[]): Observable<any> {
    return this.http.put(`${this.base}/folders/reorder`, { order });
  }

  renameFolder(folderId: string, name: string): Observable<Folder> {
    return this.http.patch<Folder>(`${this.base}/folders/${folderId}`, { name });
  }

  deleteFolder(folderId: string, deleteMeetings: boolean = false): Observable<any> {
    return this.http.delete(`${this.base}/folders/${folderId}`, {
      params: { deleteMeetings: String(deleteMeetings) },
    });
  }

  listShares(folderId: string): Observable<FolderMemberListResponse> {
    return this.http.get<FolderMemberListResponse>(`${this.base}/folders/${folderId}/shares`);
  }

  addShare(folderId: string, identifier: string, role: 'editor' | 'viewer'): Observable<FolderMember> {
    return this.http.post<FolderMember>(`${this.base}/folders/${folderId}/shares`, {
      identifier,
      role,
    });
  }

  updateShare(folderId: string, granteeId: string, role: 'editor' | 'viewer'): Observable<any> {
    return this.http.patch(`${this.base}/folders/${folderId}/shares/${granteeId}`, { role });
  }

  removeShare(folderId: string, granteeId: string): Observable<any> {
    return this.http.delete(`${this.base}/folders/${folderId}/shares/${granteeId}`);
  }
}
