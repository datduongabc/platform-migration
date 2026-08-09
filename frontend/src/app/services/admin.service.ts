import { inject, Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { ApiConfiguration } from '../api/api-configuration';

export interface PipelineCounts {
  pending: number;
  processing: number;
  done: number;
  failed: number;
  stuck: number;
}

export interface PipelineOverview {
  counts: PipelineCounts;
  avg_processing_secs: number | null;
  stuck_threshold_minutes: number;
  total: number;
}

export interface PipelineJob {
  id: string;
  title: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  duration_seconds: number | null;
  error_message: string | null;
  owner_email: string | null;
  owner_username: string | null;
  is_stuck: boolean;
}

export interface PipelineJobsResponse {
  jobs: PipelineJob[];
  total: number;
  page: number;
  perPage: number;
}

export interface KeyResponse {
  id: string;
  created_at: string;
  updated_at?: string;
  config_key: string;
  label: string;
  last4: string;
  status: 'active' | 'disabled';
  disabled_reason?: string;
  last_used_at?: string;
  health_status?: 'healthy' | 'unhealthy' | 'unknown';
  health_checked_at?: string;
  health_detail?: string;
}

export interface HealthProbeInfo {
  id: string;
  config_key: string;
  label: string;
  status: 'healthy' | 'unhealthy' | 'unknown';
  detail: string | null;
}

export interface HealthCheckResponse {
  ranAt: string;
  summary: {
    total: number;
    healthy: number;
    unhealthy: number;
    unknown: number;
  };
  keys: HealthProbeInfo[];
}

@Injectable({
  providedIn: 'root',
})
export class AdminService {
  private readonly http = inject(HttpClient);
  private readonly config = inject(ApiConfiguration);

  private get base(): string {
    return this.config.rootUrl;
  }

  // ── Pipeline Monitoring ───────────────────────────────────────────────────

  getPipelineOverview(): Observable<PipelineOverview> {
    return this.http.get<PipelineOverview>(`${this.base}/admin/pipeline/overview`);
  }

  getPipelineJobs(status?: string, page = 1, perPage = 20): Observable<PipelineJobsResponse> {
    let params = new HttpParams()
      .set('page', page.toString())
      .set('perPage', perPage.toString());

    if (status && status !== 'all') {
      params = params.set('status', status);
    }

    return this.http.get<PipelineJobsResponse>(`${this.base}/admin/pipeline/jobs`, { params });
  }

  requeueJob(id: string): Observable<any> {
    return this.http.post(`${this.base}/admin/pipeline/${id}/requeue`, {});
  }

  // ── Key Vault ─────────────────────────────────────────────────────────────

  getKeys(): Observable<{ keys: KeyResponse[] }> {
    return this.http.get<{ keys: KeyResponse[] }>(`${this.base}/admin/keys`);
  }

  addKey(payload: { configKey: string; label: string; key: string }): Observable<{ key: KeyResponse }> {
    return this.http.post<{ key: KeyResponse }>(`${this.base}/admin/keys`, payload);
  }

  updateKey(id: string, payload: { status: string; disabled_reason?: string | null }): Observable<{ key: KeyResponse }> {
    return this.http.patch<{ key: KeyResponse }>(`${this.base}/admin/keys/${id}`, payload);
  }

  deleteKey(id: string): Observable<any> {
    return this.http.delete(`${this.base}/admin/keys/${id}`);
  }

  runHealthcheck(): Observable<HealthCheckResponse> {
    return this.http.post<HealthCheckResponse>(`${this.base}/admin/keys/healthcheck`, {});
  }

  // ── Storage Configuration ──────────────────────────────────────────────────

  getStorageConfigs(): Observable<{ storage_configs: any[] }> {
    return this.http.get<{ storage_configs: any[] }>(`${this.base}/admin/storage`);
  }

  createStorageConfig(payload: any): Observable<any> {
    return this.http.post(`${this.base}/admin/storage`, payload);
  }

  updateStorageConfig(id: string, payload: any): Observable<any> {
    return this.http.patch(`${this.base}/admin/storage/${id}`, payload);
  }

  deleteStorageConfig(id: string): Observable<any> {
    return this.http.delete(`${this.base}/admin/storage/${id}`);
  }

  // ── System & Generation Config ─────────────────────────────────────────────

  getAppConfig(): Observable<{ configs: any[] }> {
    return this.http.get<{ configs: any[] }>(`${this.base}/admin/config`);
  }

  updateAppConfig(payload: { key: string; value: any }): Observable<any> {
    return this.http.patch(`${this.base}/admin/config`, payload);
  }

  getGenerationConfig(): Observable<{ systemDefault: any; allowedModels: any[] }> {
    return this.http.get<{ systemDefault: any; allowedModels: any[] }>(`${this.base}/admin/generation-config`);
  }

  updateGenerationConfig(payload: { systemDefault?: any; allowedModels?: any[] }): Observable<any> {
    return this.http.patch(`${this.base}/admin/generation-config`, payload);
  }

  // ── Audit Logs ─────────────────────────────────────────────────────────────

  getAuditLogs(action?: string, targetType?: string, page = 1, perPage = 20): Observable<{ rows: any[]; total: number; page: number; perPage: number }> {
    let params = new HttpParams()
      .set('page', page.toString())
      .set('perPage', perPage.toString());

    if (action) params = params.set('action', action);
    if (targetType) params = params.set('targetType', targetType);

    return this.http.get<{ rows: any[]; total: number; page: number; perPage: number }>(`${this.base}/admin/audit-logs`, { params });
  }

  // ── User Activity Logs ─────────────────────────────────────────────────────

  getActivityLogs(userId?: string, eventType?: string, page = 1, perPage = 20): Observable<{ rows: any[]; total: number; page: number; perPage: number }> {
    let params = new HttpParams()
      .set('page', page.toString())
      .set('perPage', perPage.toString());

    if (userId) params = params.set('userId', userId);
    if (eventType) params = params.set('eventType', eventType);

    return this.http.get<{ rows: any[]; total: number; page: number; perPage: number }>(`${this.base}/admin/activity`, { params });
  }

  // ── AI Usage Telemetry ─────────────────────────────────────────────────────

  getAiUsage(fromDate?: string, toDate?: string, groupBy?: string): Observable<{ from?: string; to?: string; rows: any[]; dailyTotals: any[] }> {
    let params = new HttpParams();
    if (fromDate) params = params.set('from', fromDate);
    if (toDate) params = params.set('to', toDate);
    if (groupBy) params = params.set('groupBy', groupBy);

    return this.http.get<{ from?: string; to?: string; rows: any[]; dailyTotals: any[] }>(`${this.base}/admin/ai-usage`, { params });
  }

  // ── Feature Registry ───────────────────────────────────────────────────────

  getFeatures(modulePrefix?: string, status?: string, search?: string): Observable<{ features: any[] }> {
    let params = new HttpParams();
    if (modulePrefix) params = params.set('modulePrefix', modulePrefix);
    if (status) params = params.set('status', status);
    if (search) params = params.set('search', search);

    return this.http.get<{ features: any[] }>(`${this.base}/admin/features`, { params });
  }

  updateFeature(id: string, payload: any): Observable<any> {
    return this.http.patch(`${this.base}/admin/features/${id}`, payload);
  }

  // ── User Management ──────────────────────────────────────────────────────

  updateUserRole(id: string, role: 'user' | 'admin'): Observable<any> {
    return this.http.patch(`${this.base}/admin/users/${id}/role`, { role });
  }

  updateUserStatus(id: string, disabled: boolean): Observable<any> {
    return this.http.patch(`${this.base}/admin/users/${id}/status`, { disabled });
  }

  resetUserPassword(id: string): Observable<{ temporaryPassword: string }> {
    return this.http.post<{ temporaryPassword: string }>(`${this.base}/admin/users/${id}/reset-password`, {});
  }

  deleteUser(id: string): Observable<{ ok: boolean; storageWarning: string | null }> {
    return this.http.delete<{ ok: boolean; storageWarning: string | null }>(`${this.base}/admin/users/${id}`);
  }
}

