/**
 * Desktop API client for local file processing
 */

// Removed global API_BASE

export interface ClientFolder {
  name: string;
  path: string;
  file_count: number;
  files: string[];
  size_mb: number;
}

export interface ScanResult {
  pdf_clients: ClientFolder[];
  cfdi_clients: ClientFolder[];
  warnings: string[];
  errors: string[];
  matched_clients: string[];
  pdf_only_clients: string[];
  cfdi_only_clients: string[];
}

export interface ValidationResult {
  folders_valid: boolean;
  credentials_valid: boolean;
  pdf_folder_path: string;
  cfdi_folder_path: string;
  credentials_path: string;
  folder_errors: string[];
  credentials_message: string;
}

export interface Match {
  payment_id: string;
  invoice_ids: string[];
  payment_amount: number;
  invoice_total: number;
  remainder: number;
  confidence: number;
  match_type: string;
  text_similarity: number;
}

export interface ReconciliationResult {
  job_id: string;
  client_name: string;
  status: 'completed' | 'failed' | 'partial';
  total_payments: number;
  total_invoices: number;
  matched_count: number;
  unmatched_payments: number;
  unmatched_invoices: number;
  total_reconciled_amount: number;
  total_delta: number;
  matches: Match[];
  unmatched_payment_ids: string[];
  unmatched_invoice_ids: string[];
  processing_time_seconds: number;
  phases_completed: string[];
  warnings: string[];
}

export interface ProcessingStatus {
  job_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  current_phase: string;
  progress: number;
  message: string;
  started_at: string;
  completed_at?: string;
}

class DesktopApi {
  private baseUrl: string = 'http://127.0.0.1:8000';

  setPort(port: number) {
    this.baseUrl = `http://127.0.0.1:${port}`;
    console.log(`[API] Base URL updated to: ${this.baseUrl}`);
  }

  private async request<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    console.log(`[API] ${options?.method || 'GET'} ${url}`);

    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...options?.headers,
        },
      });

      console.log(`[API] Response status: ${response.status}`);

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Error desconocido' }));
        throw new Error(error.detail || `HTTP ${response.status}`);
      }

      const data = await response.json();
      console.log(`[API] Response data:`, data);
      return data;
    } catch (error) {
      console.error(`[API] Request failed for ${url}:`, error);
      if (error instanceof TypeError && error.message.includes('fetch')) {
        throw new Error(`No se puede conectar al servidor en ${url}. Verifica que el backend esté corriendo.`);
      }
      throw error;
    }
  }

  /**
   * Validate folder structure and credentials
   */
  async validateSetup(): Promise<ValidationResult> {
    const response = await this.request<{
      is_valid: boolean;
      message: string;
      details: {
        folders_valid: boolean;
        credentials_valid: boolean;
        pdf_folder: string;
        cfdi_folder: string;
        credentials_path: string;
      };
    }>('/api/validate');

    return {
      folders_valid: response.details.folders_valid,
      credentials_valid: response.details.credentials_valid,
      pdf_folder_path: response.details.pdf_folder,
      cfdi_folder_path: response.details.cfdi_folder,
      credentials_path: response.details.credentials_path,
      folder_errors: response.is_valid ? [] : [response.message],
      credentials_message: response.details.credentials_valid ? 'OK' : response.message,
    };
  }

  /**
   * Scan PDF and CFDI folders for clients
   */
  async scanFolders(): Promise<ScanResult> {
    const response = await this.request<{
      pdf_clients: Array<{ name: string; file_count: number; size_mb: number }>;
      cfdi_clients: Array<{ name: string; file_count: number; size_mb: number }>;
      matched_clients: string[];
      pdf_only_clients: string[];
      cfdi_only_clients: string[];
      warnings: string[];
      errors: string[];
    }>('/api/scan');

    return {
      pdf_clients: response.pdf_clients.map(c => ({
        name: c.name,
        path: '',
        file_count: c.file_count,
        files: [],
        size_mb: c.size_mb,
      })),
      cfdi_clients: response.cfdi_clients.map(c => ({
        name: c.name,
        path: '',
        file_count: c.file_count,
        files: [],
        size_mb: c.size_mb,
      })),
      matched_clients: response.matched_clients,
      pdf_only_clients: response.pdf_only_clients,
      cfdi_only_clients: response.cfdi_only_clients,
      warnings: response.warnings,
      errors: response.errors,
    };
  }

  /**
   * Get files for a specific client
   */
  async getClientFiles(_clientName: string): Promise<{
    pdf_files: string[];
    cfdi_files: string[];
  }> {
    // Not implemented in backend - return empty
    return { pdf_files: [], cfdi_files: [] };
  }

  /**
   * Start reconciliation for a client
   */
  async startReconciliation(pdfClient: string, cfdiClient: string): Promise<{ job_id: string }> {
    const response = await this.request<{
      id: string;
      status: string;
      progress: number;
      current_phase: string;
      message: string;
    }>('/api/reconciliation/start', {
      method: 'POST',
      body: JSON.stringify({ pdf_client: pdfClient, cfdi_client: cfdiClient }),
    });
    return { job_id: response.id };
  }

  /**
   * Process client (legacy - calls startReconciliation)
   */
  async processClient(clientName: string): Promise<ReconciliationResult> {
    const { job_id } = await this.startReconciliation(clientName, clientName);

    // Poll for completion
    let status: ProcessingStatus;
    do {
      await new Promise(resolve => setTimeout(resolve, 1000));
      status = await this.getStatus(job_id);
    } while (status.status === 'pending' || status.status === 'processing');

    // Get result
    return this.getResult(job_id);
  }

  /**
   * Get processing status
   */
  async getStatus(jobId: string): Promise<ProcessingStatus> {
    const response = await this.request<{
      id: string;
      status: string;
      progress: number;
      current_phase: string;
      message: string;
    }>(`/api/reconciliation/${jobId}/status`);

    return {
      job_id: response.id,
      status: response.status as ProcessingStatus['status'],
      current_phase: response.current_phase,
      progress: response.progress,
      message: response.message,
      started_at: '',
    };
  }

  /**
   * Get reconciliation result
   */
  async getResult(jobId: string): Promise<ReconciliationResult> {
    const response = await this.request<any>(`/api/reconciliation/${jobId}/result`);

    return {
      job_id: response.job_id,
      client_name: '',
      status: response.status === 'completed' ? 'completed' : 'failed',
      total_payments: response.summary?.total_payments || 0,
      total_invoices: response.summary?.total_invoices || 0,
      matched_count: response.matched_pairs?.length || 0,
      unmatched_payments: response.unmatched_payments || 0,
      unmatched_invoices: response.unmatched_invoices || 0,
      total_reconciled_amount: 0,
      total_delta: 0,
      matches: (response.matched_pairs || []).map((p: any) => ({
        payment_id: p.payment_ids?.[0] || '',
        invoice_ids: p.invoice_ids || [],
        payment_amount: p.total_payment || 0,
        invoice_total: p.total_invoice || 0,
        remainder: p.gap || 0,
        confidence: p.confidence === 'high' ? 0.9 : p.confidence === 'medium' ? 0.7 : 0.5,
        match_type: 'exact',
        text_similarity: 0,
      })),
      unmatched_payment_ids: [],
      unmatched_invoice_ids: [],
      processing_time_seconds: response.summary?.processing_time || 0,
      phases_completed: [],
      warnings: response.warnings || [],
    };
  }

  /**
   * Export results to file
   */
  async exportResults(job_id: string, _format: 'xlsx' | 'csv' | 'pdf'): Promise<Blob> {
    const response = await fetch(`${this.baseUrl}/api/reconciliation/${job_id}/export`);

    if (!response.ok) {
      throw new Error('Error al exportar');
    }

    return response.blob();
  }

  /**
   * Health check
   */
  async healthCheck(): Promise<{ status: string; version: string }> {
    return this.request('/health');
  }

  /**
   * Get application settings
   */
  async getSettings(): Promise<{
    max_abs_delta_cents: number;
    rel_delta_ratio: number;
    solver_timeout_seconds: number;
    max_cluster_size: number;
    google_application_credentials?: string;
  }> {
    return this.request('/settings');
  }

  /**
   * Update application settings
   */
  async updateSettings(settings: {
    max_abs_delta_cents?: number;
    rel_delta_ratio?: number;
    solver_timeout_seconds?: number;
    max_cluster_size?: number;
    google_application_credentials?: string;
  }): Promise<{ status: string; message: string }> {
    return this.request('/settings', {
      method: 'POST',
      body: JSON.stringify(settings),
    });
  }
}

export const api = new DesktopApi();
