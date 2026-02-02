export interface JobStatus {
  id: string
  status: 'pending' | 'processing' | 'ingesting' | 'peeling' | 'clustering' | 'solving' | 'rescue' | 'completed' | 'failed'
  progress: number
  current_phase: string
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface MatchedPair {
  id: string
  invoice_ids: string[]
  payment_ids: string[]
  total_invoice_cents: number
  total_payment_cents: number
  gap_cents: number
  confidence: 'high' | 'medium' | 'low' | 'ambiguous'
  commit_status: 'shadow' | 'soft' | 'hard' | 'pending' | 'manual_review'
}

export interface PartialMatch {
  id: string
  invoice_id: string
  payment_ids: string[]
  invoice_amount_cents: number
  paid_amount_cents: number
  remainder_cents: number
  percentage_paid: number
}

export interface ManualReviewCase {
  id: string
  invoice_ids: string[]
  payment_ids: string[]
  reason: string
}

export interface ReconciliationSummary {
  total_invoices: number
  total_payments: number
  matched_invoices: number
  matched_payments: number
  unmatched_invoices: number
  unmatched_payments: number
  match_rate_invoices: number
  match_rate_payments: number
  processing_time_seconds: number
}

export interface ReconciliationResult {
  job_id: string
  status: string
  matched_pairs: MatchedPair[]
  partial_matches: PartialMatch[]
  unmatched_invoices: string[]
  unmatched_payments: string[]
  manual_review: ManualReviewCase[]
  summary: ReconciliationSummary
}

export interface AuditEntry {
  id: string
  timestamp: string
  action: string
  message: string
  transaction_ids: string[]
  success: boolean
}
